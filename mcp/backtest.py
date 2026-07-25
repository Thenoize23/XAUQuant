"""Bar-based backtester for the XAUQuant strategy (the MCP/EA engine).

Because the MQL5 EA and the Python MCP share the SAME strategy logic, this
backtests both. It walks XAUUSD OHLC bars, reuses the live signal engine
(strategy.compute_signal) and the same cfg thresholds, and simulates the
martingale basket intrabar (grid adds on the adverse extreme, basket take-
profit on the favourable extreme), with spread, commission, leverage/margin
and a broker stop-out (blow-up) check.

Usage:
    python backtest.py data.csv                # CSV: time,open,high,low,close
    python backtest.py --generate 20000        # synthetic random-walk (demo only)
    XQ_MAX_LEVELS=6 python backtest.py data.csv

CSV backtests real broker data; synthetic is only to prove the machinery.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from typing import List

import numpy as np

import indicators as ind
import calendar_filter as cal
from config import Config
from strategy import compute_signal, grid_step_price, next_level_lot, REGIME_TREND_UP, REGIME_TREND_DOWN

# --- instrument / account model (XAUUSD defaults) ---
CONTRACT = 100.0        # 1 lot = 100 oz  -> P/L = (dp) * CONTRACT * lots
POINT = 0.01
SPREAD_POINTS = 20      # round-trip spread assumption (points)
COMMISSION_PER_LOT = 0.0  # per side, account currency
LEVERAGE = 100.0
STOP_OUT_LEVEL = 0.5    # equity < 50% of used margin -> broker stop-out
HALT_AFTER_STOP = True  # match EA InpHaltAfterStop: stop trading after the DD guard fires


@dataclass
class Pos:
    entry: float
    volume: float


@dataclass
class Side:
    direction: str          # BUY | SELL
    positions: List[Pos] = field(default_factory=list)

    @property
    def levels(self): return len(self.positions)
    @property
    def volume(self): return sum(p.volume for p in self.positions)
    @property
    def avg(self):
        v = self.volume
        return sum(p.entry * p.volume for p in self.positions) / v if v else 0.0
    @property
    def worst(self):
        if not self.positions:
            return 0.0
        return min(p.entry for p in self.positions) if self.direction == "BUY" \
            else max(p.entry for p in self.positions)

    def floating(self, price: float) -> float:
        s = 1 if self.direction == "BUY" else -1
        return sum(s * (price - p.entry) * CONTRACT * p.volume for p in self.positions)

    def used_margin(self, price: float) -> float:
        return price * CONTRACT * self.volume / LEVERAGE


def load_csv(path: str):
    t, o, h, l, c = [], [], [], [], []
    with open(path, newline="") as f:
        r = csv.reader(f)
        header = next(r)
        # tolerate time,open,high,low,close[,volume] with/without header
        def looks_num(s):
            try: float(s); return True
            except ValueError: return False
        if looks_num(header[1]):
            rows = [header] + list(r)
        else:
            rows = list(r)
        for row in rows:
            if len(row) < 5:
                continue
            t.append(row[0]); o.append(float(row[1])); h.append(float(row[2]))
            l.append(float(row[3])); c.append(float(row[4]))
    return t, np.array(o), np.array(h), np.array(l), np.array(c)


def generate(n: int, seed: int = 42):
    rng = np.random.default_rng(seed)
    # gold-like random walk with mild drift + vol clustering
    ret = rng.normal(0.0, 0.6, n)
    ret[::500] += rng.normal(0, 4, len(ret[::500]))  # occasional shocks
    close = 2000 + np.cumsum(ret)
    high = close + np.abs(rng.normal(0, 0.4, n))
    low = close - np.abs(rng.normal(0, 0.4, n))
    t = [str(i) for i in range(n)]
    return t, close.copy(), high, low, close


def run(cfg: Config, t, o, h, l, c, initial_balance=10000.0, verbose=True):
    n = len(c)
    spread = SPREAD_POINTS * POINT

    # precompute indicators once
    adx_a, pdi_a, mdi_a = ind.adx_series(h, l, c, cfg.adx_period)
    rsi_a = ind.rsi_series(c, cfg.rsi_period)
    bmid, bup, blo = ind.bollinger_series(c, cfg.bb_period, cfg.bb_dev)
    atr_a = ind.atr_series(h, l, c, cfg.atr_period)
    mom_a = ind.momentum_series(c, cfg.mom_period)

    warmup = max(cfg.adx_period, cfg.rsi_period, cfg.bb_period, cfg.atr_period, cfg.ma_period) + 5

    balance = initial_balance
    peak_equity = initial_balance
    long = Side("BUY"); short = Side("SELL")

    # time-based anti-shock masks (precomputed once)
    news_mask = cal.news_blackout_mask(t, cfg.news_pre_min, cfg.news_post_min,
                                       cfg.news_use_nfp) if cfg.news_filter else None
    gap_mask = cal.weekend_flatten_mask(t, cfg.weekend_gap_hours) if cfg.weekend_gap_guard else None

    closed = 0; wins = 0; stops = 0; flats = 0; max_levels = 0; max_vol = 0.0
    max_dd = 0.0; blew_up = False; halted = False; halt_time = None
    cooldown = 0

    def close_side(side: Side, price: float, kind: str = "auto"):
        nonlocal balance, closed, wins, stops, flats
        pl = side.floating(price) - COMMISSION_PER_LOT * side.volume
        balance += pl
        closed += 1
        if kind == "stop": stops += 1
        elif kind == "flat": flats += 1
        elif pl > 0: wins += 1
        side.positions.clear()

    for i in range(warmup, n):
        if np.isnan(bmid[i]) or np.isnan(atr_a[i]):
            continue
        step = grid_step_price(cfg, atr_a[i], POINT)
        atrv = atr_a[i]
        bar_range = h[i] - l[i]
        shock_candle = cfg.shock_guard and atrv > 0 and bar_range > cfg.shock_atr_mult * atrv
        if cooldown > 0:
            cooldown -= 1

        # ---- time-based anti-shock: flatten & pause inside news/weekend windows ----
        blocked = (news_mask is not None and news_mask[i]) or (gap_mask is not None and gap_mask[i])
        if blocked:
            if long.positions:  close_side(long,  c[i] - spread, kind="flat")
            if short.positions: close_side(short, c[i] + spread, kind="flat")
            equity = balance
            peak_equity = max(peak_equity, equity)
            continue  # no adds, no entries while inside a protected window

        # ---- manage open baskets intrabar (stop, adds, TP) ----
        for side in (long, short):
            if not side.positions:
                continue
            is_buy = side.direction == "BUY"
            adverse = l[i] if is_buy else h[i]          # worst price this bar for the basket

            # --- ANTI-SHOCK basket stop (controlled loss instead of a margin call) ---
            if cfg.shock_guard:
                stop_hit = False
                if cfg.basket_stop_atr > 0 and atrv > 0:
                    dist = (side.avg - adverse) if is_buy else (adverse - side.avg)
                    if dist >= cfg.basket_stop_atr * atrv:
                        stop_hit = True
                if cfg.basket_stop_pct > 0:
                    fl = side.floating(adverse - spread if is_buy else adverse + spread)
                    if fl <= -cfg.basket_stop_pct / 100.0 * balance:
                        stop_hit = True
                if stop_hit:
                    px = adverse - spread if is_buy else adverse + spread
                    close_side(side, px, kind="stop")
                    cooldown = cfg.shock_cooldown_bars
                    continue

            # grid adds: adverse extreme reaches worst -/+ step (frozen during a shock candle)
            if step > 0 and not (shock_candle and cfg.freeze_adds_on_shock):
                while side.levels < cfg.max_levels:
                    trig = side.worst - step if is_buy else side.worst + step
                    reached = (l[i] <= trig) if is_buy else (h[i] >= trig)
                    if not reached:
                        break
                    lot = next_level_lot(cfg, side.levels)
                    fill = trig + spread if is_buy else trig - spread
                    side.positions.append(Pos(fill, lot))

            # basket take-profit at favourable extreme
            fav = h[i] if is_buy else l[i]
            exit_price = fav - spread if is_buy else fav + spread
            if cfg.target_mode == "money":
                if side.floating(exit_price) >= cfg.target_money:
                    close_side(side, exit_price)
            else:
                pts = (exit_price - side.avg) / POINT if is_buy else (side.avg - exit_price) / POINT
                if pts >= cfg.target_points:
                    close_side(side, exit_price)

            max_levels = max(max_levels, side.levels)
            max_vol = max(max_vol, side.volume)

        # ---- new entry decision from the signal (only if that side is flat) ----
        sig = compute_signal(
            cfg, adx_val=adx_a[i], plus_di=pdi_a[i], minus_di=mdi_a[i], rsi_val=rsi_a[i],
            bb_mid=bmid[i], bb_up=bup[i], bb_low=blo[i], price=c[i], mom=mom_a[i],
        )
        if not halted and cooldown == 0 and SPREAD_POINTS <= cfg.max_spread_points:
            if not long.positions and cfg.allow_long and sig.buy_conf >= cfg.conf_threshold \
                    and sig.regime != REGIME_TREND_DOWN:
                long.positions.append(Pos(c[i] + spread, cfg.base_lot))
            if not short.positions and cfg.allow_short and sig.sell_conf >= cfg.conf_threshold \
                    and sig.regime != REGIME_TREND_UP:
                short.positions.append(Pos(c[i] - spread, cfg.base_lot))

        # ---- mark to market, guardrail, stop-out ----
        equity = balance + long.floating(c[i]) + short.floating(c[i])
        peak_equity = max(peak_equity, equity)
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        max_dd = max(max_dd, dd)

        # emergency drawdown guardrail (strategy) — fires once, then halts like the EA
        if not halted and dd >= cfg.max_drawdown_pct and (long.positions or short.positions):
            close_side(long, c[i] - spread) if long.positions else None
            close_side(short, c[i] + spread) if short.positions else None
            if HALT_AFTER_STOP:
                halted = True
                halt_time = t[i]

        # broker stop-out (blow up)
        used = long.used_margin(c[i]) + short.used_margin(c[i])
        if used > 0 and equity < STOP_OUT_LEVEL * used:
            close_side(long, c[i] - spread) if long.positions else None
            close_side(short, c[i] + spread) if short.positions else None
            blew_up = True
            break

    final_equity = balance + long.floating(c[-1]) + short.floating(c[-1])
    result = {
        "bars": n,
        "initial_balance": round(initial_balance, 2),
        "final_balance": round(balance, 2),
        "final_equity": round(final_equity, 2),
        "net_profit": round(final_equity - initial_balance, 2),
        "return_pct": round((final_equity - initial_balance) / initial_balance * 100, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "baskets_closed": closed,
        "win_rate_pct": round(wins / closed * 100, 1) if closed else 0.0,
        "stop_outs": stops,
        "news_flats": flats,
        "max_grid_levels": max_levels,
        "max_basket_lots": round(max_vol, 2),
        "blew_up": blew_up,
        "halted": halted,
        "halt_time": halt_time,
    }
    if verbose:
        print("\n=== XAUQuant backtest ===")
        for k, v in result.items():
            print(f"  {k:20} {v}")
        verdict = "BLEW UP (margin call)" if blew_up else \
                  ("profitable" if result["net_profit"] > 0 else "unprofitable")
        print(f"  {'verdict':20} {verdict}")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", help="CSV time,open,high,low,close")
    ap.add_argument("--generate", type=int, metavar="N", help="use N synthetic bars (demo)")
    ap.add_argument("--balance", type=float, default=10000.0)
    args = ap.parse_args()

    cfg = Config.from_env()
    if args.csv:
        t, o, h, l, c = load_csv(args.csv)
        print(f"loaded {len(c)} bars from {args.csv}")
    elif args.generate:
        t, o, h, l, c = generate(args.generate)
        print(f"generated {len(c)} synthetic bars (NOT real data)")
    else:
        ap.error("provide a CSV path or --generate N")
    run(cfg, t, o, h, l, c, initial_balance=args.balance)


if __name__ == "__main__":
    main()
