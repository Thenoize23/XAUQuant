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

    # --- confidence signal ---
    rsi_period: int = 14
    bb_period: int = 20
    bb_dev: float = 2.0
    conf_threshold: int = 60       # 0-100 needed to open a basket
    mom_period: int = 14

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
