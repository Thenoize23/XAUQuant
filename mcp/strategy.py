"""Broker-agnostic strategy engine — a faithful Python port of the MQL5 EA.

Given market indicators and the current basket state it produces:
  * a Signal   (regime + buy/sell confidence + momentum)
  * a plan     (ordered list of actions the strategy would take right now)

No MetaTrader / IO here — this module is pure and unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from config import Config

REGIME_RANGE = "RANGE"
REGIME_TREND_UP = "TREND_UP"
REGIME_TREND_DOWN = "TREND_DOWN"


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass
class Signal:
    regime: str
    buy_conf: int
    sell_conf: int
    momentum: float


@dataclass
class Basket:
    direction: str          # "BUY" | "SELL"
    levels: int = 0
    volume: float = 0.0
    avg_price: float = 0.0
    pl: float = 0.0
    worst_price: float = 0.0   # deepest price into drawdown (last grid level)

    @property
    def is_open(self) -> bool:
        return self.levels > 0


@dataclass
class Action:
    action: str             # OPEN | ADD | CLOSE | EMERGENCY_CLOSE | HOLD
    direction: str = ""     # BUY | SELL
    lots: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "direction": self.direction,
            "lots": round(self.lots, 2),
            "reason": self.reason,
        }


# ------------------------------------------------------------------ signal ---
def compute_signal(cfg: Config, *, adx_val: float, plus_di: float, minus_di: float,
                   rsi_val: float, bb_mid: float, bb_up: float, bb_low: float,
                   price: float, mom: float) -> Signal:
    # --- regime ---
    if adx_val < cfg.adx_trend_level:
        regime = REGIME_RANGE
    else:
        regime = REGIME_TREND_UP if plus_di >= minus_di else REGIME_TREND_DOWN

    # --- mean-reversion confidence ---
    bb_buy = (bb_mid - price) / (bb_mid - bb_low) if bb_mid > bb_low else 0.0
    bb_sell = (price - bb_mid) / (bb_up - bb_mid) if bb_up > bb_mid else 0.0
    bb_buy = _clamp(bb_buy, 0.0, 1.5)
    bb_sell = _clamp(bb_sell, 0.0, 1.5)

    rsi_buy = _clamp((50.0 - rsi_val) / 30.0, 0.0, 1.0)
    rsi_sell = _clamp((rsi_val - 50.0) / 30.0, 0.0, 1.0)

    # trend mode = buy strength / sell weakness (flip the reversion components)
    if cfg.signal_mode == "trend":
        bb_buy, bb_sell = bb_sell, bb_buy
        rsi_buy, rsi_sell = rsi_sell, rsi_buy

    buy_raw = 0.6 * _clamp(bb_buy, 0, 1) + 0.4 * rsi_buy
    sell_raw = 0.6 * _clamp(bb_sell, 0, 1) + 0.4 * rsi_sell

    if regime == REGIME_TREND_UP:
        buy_raw *= 1.15
        sell_raw *= 0.60
    elif regime == REGIME_TREND_DOWN:
        sell_raw *= 1.15
        buy_raw *= 0.60

    return Signal(
        regime=regime,
        buy_conf=int(round(_clamp(buy_raw, 0, 1) * 100)),
        sell_conf=int(round(_clamp(sell_raw, 0, 1) * 100)),
        momentum=mom,
    )


# ------------------------------------------------------------------- lots ---
def next_level_lot(cfg: Config, level: int) -> float:
    lot = cfg.base_lot
    if cfg.lot_mode == "multiplier":
        lot = cfg.base_lot * (cfg.lot_multiplier ** level)
    return min(lot, cfg.max_lot_per_order)


def grid_step_price(cfg: Config, atr_value: float, point: float) -> float:
    if cfg.step_mode == "fixed":
        return cfg.grid_step_points * point
    return atr_value * cfg.atr_step_mult


# ------------------------------------------------------------------ plan ---
def plan_actions(cfg: Config, sig: Signal, *, bid: float, ask: float,
                 spread_points: float, atr_value: float, point: float,
                 long_basket: Basket, short_basket: Basket,
                 equity: float, peak_equity: float) -> List[Action]:
    """Return the ordered list of actions the strategy would take right now."""
    actions: List[Action] = []

    # 1) GUARDRAIL: emergency equity drawdown -> flatten everything, stop.
    if peak_equity > 0:
        dd = (peak_equity - equity) / peak_equity * 100.0
        if dd >= cfg.max_drawdown_pct:
            for b in (long_basket, short_basket):
                if b.is_open:
                    actions.append(Action("EMERGENCY_CLOSE", b.direction, b.volume,
                                          f"equity drawdown {dd:.1f}% >= {cfg.max_drawdown_pct}%"))
            return actions or [Action("HOLD", reason=f"drawdown {dd:.1f}% (nothing open)")]

    step = grid_step_price(cfg, atr_value, point)

    for b in (long_basket, short_basket):
        is_buy = b.direction == "BUY"

        # 2) EXIT: close whole basket at target
        if b.is_open:
            if cfg.target_mode == "money":
                if b.pl >= cfg.target_money:
                    actions.append(Action("CLOSE", b.direction, b.volume,
                                          f"basket P/L {b.pl:.2f} >= target {cfg.target_money}"))
                    continue
            else:
                price = bid if is_buy else ask
                pts = (price - b.avg_price) / point if is_buy else (b.avg_price - price) / point
                if pts >= cfg.target_points:
                    actions.append(Action("CLOSE", b.direction, b.volume,
                                          f"basket {pts:.0f} pts >= target {cfg.target_points}"))
                    continue

            # 3) GRID ADD: price moved against basket by one step
            if b.levels < cfg.max_levels and step > 0:
                add = (is_buy and ask <= b.worst_price - step) or \
                      (not is_buy and bid >= b.worst_price + step)
                if add:
                    lot = next_level_lot(cfg, b.levels)
                    actions.append(Action("ADD", b.direction, lot,
                                          f"grid level {b.levels + 1} (step {step:.3f})"))
            elif b.levels >= cfg.max_levels:
                actions.append(Action("HOLD", b.direction, reason=f"max levels {cfg.max_levels} reached"))
            continue

        # 4) ENTRY: open first level of an empty basket
        allow = cfg.allow_long if is_buy else cfg.allow_short
        conf = sig.buy_conf if is_buy else sig.sell_conf
        if not allow:
            continue
        if spread_points > cfg.max_spread_points:
            actions.append(Action("HOLD", b.direction, reason=f"spread {spread_points:.0f} too wide"))
            continue
        if conf < cfg.conf_threshold:
            continue
        # regime gate
        if is_buy and sig.regime == REGIME_TREND_DOWN:
            continue
        if not is_buy and sig.regime == REGIME_TREND_UP:
            continue
        actions.append(Action("OPEN", b.direction, cfg.base_lot,
                              f"{b.direction} conf {conf} >= {cfg.conf_threshold}, regime {sig.regime}"))

    return actions or [Action("HOLD", reason="no signal")]
