"""Strategy + runtime configuration for the XAUQuant MCP server.

Mirrors the input parameters of the MQL5 EA (Experts/XAUQuant.mq5) so the
Python engine behaves the same. Values can be overridden with environment
variables prefixed with ``XQ_`` (e.g. ``XQ_MAX_LEVELS=6``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict, fields


def _env(name: str, default):
    raw = os.environ.get("XQ_" + name.upper())
    if raw is None:
        return default
    t = type(default)
    if t is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    try:
        return t(raw)
    except (ValueError, TypeError):
        return default


@dataclass
class Config:
    # --- market ---
    symbol: str = "XAUUSD"
    timeframe: str = "M1"          # M1, M5, M15, H1 ...

    # --- direction / regime ---
    allow_long: bool = True
    allow_short: bool = True
    adx_period: int = 14
    adx_trend_level: float = 25.0
    ma_period: int = 50
    regime_use_slope: bool = False   # direction from recent price slope (reactive) vs DI (laggy)
    regime_slope_bars: int = 5       # lookback bars for the slope

    # --- confidence signal ---
    rsi_period: int = 14
    bb_period: int = 20
    bb_dev: float = 2.0
    conf_threshold: int = 60       # 0-100 needed to open a basket
    mom_period: int = 14
    signal_mode: str = "reversion" # "reversion" (buy dips) | "trend" (buy strength)
    trend_exit: bool = True        # close a basket (stop averaging) if regime turns against it

    # --- basket / grid (martingale) ---
    lot_mode: str = "multiplier"   # "fixed" | "multiplier"
    base_lot: float = 0.01
    lot_multiplier: float = 1.5
    max_lot_per_order: float = 5.0
    step_mode: str = "atr"         # "fixed" | "atr"
    grid_step_points: int = 400
    atr_period: int = 14
    atr_step_mult: float = 1.0
    max_levels: int = 15           # GUARDRAIL

    # --- basket exit ---
    target_mode: str = "money"     # "money" | "points"
    target_money: float = 50.0
    target_points: int = 250

    # --- guardrails ---
    max_drawdown_pct: float = 25.0
    max_spread_points: int = 60

    # --- anti-shock system (per-basket protection against runaway moves) ---
    shock_guard: bool = False        # master switch for the anti-shock layer
    basket_stop_pct: float = 0.0     # close basket if floating loss >= this % of balance (0=off)
    basket_stop_atr: float = 0.0     # close basket if adverse move >= this*ATR beyond avg (0=off)
    freeze_adds_on_shock: bool = True  # stop adding levels during a shock candle
    shock_atr_mult: float = 3.0      # a bar whose range > this*ATR is a "shock candle"
    shock_cooldown_bars: int = 0     # after a stop-out, pause new entries for this many bars

    # --- time-based anti-shock (flatten + pause around scheduled events) ---
    news_filter: bool = False        # flatten & pause around high-impact news
    news_pre_min: int = 30           # blackout starts this many minutes before the event
    news_post_min: int = 30          # blackout ends this many minutes after
    news_use_nfp: bool = True         # include NFP (first Friday 13:30 UTC) automatically
    weekend_gap_guard: bool = False  # flatten before the weekend market-closed gap
    weekend_gap_hours: int = 8       # a forward time gap > this = market closed

    # --- weekend flatten for LIVE trading (schedule-based, UTC) ---
    weekend_flatten: bool = True     # live: flatten & pause around the weekend
    weekend_fri_close_hour: int = 20 # UTC hour gold stops on Friday
    weekend_pre_min: int = 60        # start flattening this many minutes before Friday close
    weekend_sun_reopen_hour: int = 22  # UTC hour gold reopens on Sunday
    weekend_reopen_buffer_min: int = 30  # wait this many min after reopen (let spread/gap settle)

    # --- execution safety ---
    auto_trade: bool = False       # master switch; False = never sends live orders
    magic: int = 990045
    deviation_points: int = 30

    @classmethod
    def from_env(cls) -> "Config":
        kwargs = {f.name: _env(f.name, f.default) for f in fields(cls)}
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return asdict(self)
