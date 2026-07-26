"""XAUQuant live runner — rotates instrument by market session and runs the
plan->execute loop while it's running (launch it; it trades until you stop it).

  * Weekdays / gold session open  -> XAUUSD  (the validated setup)
  * Weekend (gold closed)         -> BTCUSD  (crypto, 24/7)

SAFETY:
  * DEMO ONLY by default. Refuses to send orders on a real account unless you
    set XQ_ALLOW_REAL=true (the "real later" switch — double confirmation).
  * Per-symbol circuit-breaker halt; martingale risk is real — see docs/BACKTEST.md.
  * ETH is intentionally excluded (backtests negative).

Run (demo, auto-execute):   XQ_AUTO_TRADE=true python runner.py
Run (dry, just watch):      python runner.py
Stop:                       Ctrl+C
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import protection
from config import Config
from mt5_client import MT5Client, MT5Error
from strategy import compute_signal, plan_actions

# ---- per-instrument profiles (MARTINGALE: opens often, lots MULTIPLY per level) ----
# Aggressive by request: a basket every ~30-60 min, up to 10 grid levels whose lot
# size grows x1.5 each level (classic martingale averaging-down). Higher return,
# higher blow-up risk — the circuit-breaker (max_drawdown_pct) is the backstop.
GOLD = dict(symbol="XAUUSD", timeframe="M1", base_lot=0.01, lot_mode="multiplier",
            lot_multiplier=1.5, conf_threshold=15, max_levels=10, step_mode="atr",
            atr_step_mult=0.4, target_money=50.0, max_spread_points=60,
            weekend_flatten=True, max_drawdown_pct=25.0)
BTC  = dict(symbol="BTCUSD", timeframe="M1", base_lot=0.10, lot_mode="multiplier",
            lot_multiplier=1.5, conf_threshold=15, max_levels=10, step_mode="atr",
            atr_step_mult=0.4, target_money=50.0, max_spread_points=2000,
            weekend_flatten=False, max_drawdown_pct=25.0)

INTERVAL = int(os.environ.get("XQ_INTERVAL", "30"))          # seconds between checks
AUTO = os.environ.get("XQ_AUTO_TRADE", "false").lower() in ("1", "true", "yes")
ALLOW_REAL = os.environ.get("XQ_ALLOW_REAL", "false").lower() in ("1", "true", "yes")

# per-symbol runtime state (halt + peak equity persist across iterations)
_state: dict[str, dict] = {}


def _now():
    return datetime.now(timezone.utc)


def pick_profile(now):
    """Gold when its market is open; BTC during the gold weekend gap."""
    gold_cfg = Config(**GOLD)
    return BTC if protection.weekend_block(now, gold_cfg) else GOLD


def build_cfg(profile) -> Config:
    return Config(auto_trade=AUTO, **profile)


def run_once(client: Config, cfg: Config) -> str:
    """One decision cycle for the active symbol. Returns a status line."""
    st = _state.setdefault(cfg.symbol, {"halted": False, "peak": 0.0})
    snap = client.snapshot()
    sig = compute_signal(
        cfg, adx_val=snap["adx"], plus_di=snap["plus_di"], minus_di=snap["minus_di"],
        rsi_val=snap["rsi"], bb_mid=snap["bb_mid"], bb_up=snap["bb_upper"],
        bb_low=snap["bb_lower"], price=snap["last_close"], mom=snap["momentum"],
    )
    acct = client.account()
    st["peak"] = max(st["peak"], acct["equity"])
    long_b, short_b = client.basket("BUY"), client.basket("SELL")

    # protection window -> flatten & pause
    block = protection.protection_reason(_now(), cfg)
    if block:
        if long_b.levels:  client.close_basket("BUY")
        if short_b.levels: client.close_basket("SELL")
        return f"{cfg.symbol} PROTECTED ({block}) — flat"

    actions = plan_actions(
        cfg, sig, bid=snap["bid"], ask=snap["ask"], spread_points=snap["spread_points"],
        atr_value=snap["atr"], point=snap["point"], long_basket=long_b, short_basket=short_b,
        equity=acct["equity"], peak_equity=st["peak"],
    )
    did = []
    for a in actions:
        if a.action == "EMERGENCY_CLOSE":
            client.close_basket(a.direction); st["halted"] = True; did.append("EMERGENCY_CLOSE")
        elif a.action == "CLOSE":
            client.close_basket(a.direction); did.append(f"CLOSE {a.direction}")
        elif a.action in ("OPEN", "ADD"):
            if st["halted"]:
                did.append(f"skip {a.action} (halted)")
            elif not cfg.auto_trade:
                did.append(f"would {a.action} {a.direction} {a.lots}")
            else:
                r = client.open_order(a.direction, a.lots, "xq-" + a.action.lower())
                did.append(f"{a.action} {a.direction} {a.lots} -> {r.get('retcode')}")
    halt = "  [HALTED]" if st["halted"] else ""
    tag = "" if cfg.auto_trade else "  (dry-run)"
    return (f"{cfg.symbol} {sig.regime} B{sig.buy_conf}/S{sig.sell_conf} "
            f"L{long_b.levels}/S{short_b.levels} eq={acct['equity']:.0f} "
            f"-> {', '.join(did) if did else 'hold'}{halt}{tag}")


def main():
    if mt5 is None:
        raise SystemExit("MetaTrader5 package required (Windows).")

    active = None
    client = None
    print(f"XAUQuant runner | auto_trade={AUTO} allow_real={ALLOW_REAL} interval={INTERVAL}s")
    print("Ctrl+C to stop.\n")
    try:
        while True:
            profile = pick_profile(_now())
            if profile is not active:
                cfg = build_cfg(profile)
                client = MT5Client(cfg)
                try:
                    info = client.connect()
                except MT5Error as e:
                    print(f"[{_now():%H:%M:%S}] MT5 not ready ({e}) — open MT5, log in, "
                          f"enable Algo Trading. Retrying in {INTERVAL}s.")
                    active = None
                    time.sleep(INTERVAL)
                    continue
                active = profile
                is_demo = "DEMO" in str(info.get("server", "")).upper()
                if AUTO and not is_demo and not ALLOW_REAL:
                    print(f"[{_now():%H:%M}] REAL account + auto_trade without XQ_ALLOW_REAL "
                          f"-> forcing DRY-RUN for safety.")
                    cfg.auto_trade = False
                    client.cfg = cfg
                if AUTO and not info.get("trade_expert"):
                    print(f"[{_now():%H:%M}] broker blocks automation (trade_expert=False) "
                          f"-> DRY-RUN.")
                    cfg.auto_trade = False
                    client.cfg = cfg
                mt5.symbol_select(cfg.symbol, True)
                print(f"[{_now():%H:%M}] switched to {cfg.symbol} "
                      f"({info.get('server')}, demo={is_demo}, exec={cfg.auto_trade})")

            try:
                line = run_once(client, client.cfg)
                print(f"[{_now():%H:%M:%S}] {line}")
            except MT5Error as e:
                print(f"[{_now():%H:%M:%S}] MT5 error: {e}")

            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        if client:
            client.shutdown()


if __name__ == "__main__":
    main()
