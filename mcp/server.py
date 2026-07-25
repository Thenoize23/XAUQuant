"""XAUQuant MCP server.

Exposes the XAUQuant grid/martingale strategy as MCP tools so an MCP client
(Claude Desktop, Claude Code, ...) can read live signals from MetaTrader 5 and
optionally execute — without any chart-attached EA.

Run:  python server.py           (stdio transport)
Deps: pip install -r requirements.txt   (needs a running, logged-in MT5 terminal)
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from config import Config
from mt5_client import MT5Client, MT5Error
from strategy import compute_signal, plan_actions

cfg = Config.from_env()
client = MT5Client(cfg)
mcp = FastMCP("xauquant")

# runtime state kept across tool calls
_state = {"peak_equity": 0.0, "connected": False}


def _ensure_connected():
    if not _state["connected"]:
        info = client.connect()
        _state["connected"] = True
        _state["peak_equity"] = info.get("equity") or 0.0
    return _state


def _signal_from_snapshot(snap: dict):
    return compute_signal(
        cfg,
        adx_val=snap["adx"], plus_di=snap["plus_di"], minus_di=snap["minus_di"],
        rsi_val=snap["rsi"], bb_mid=snap["bb_mid"], bb_up=snap["bb_upper"],
        bb_low=snap["bb_lower"], price=snap["last_close"], mom=snap["momentum"],
    )


@mcp.tool()
def status() -> dict:
    """Connection + account + config summary. Call this first."""
    try:
        info = _ensure_connected()
        acct = client.account()
        _state["peak_equity"] = max(_state["peak_equity"], acct["equity"])
        return {
            "connected": True,
            "symbol": cfg.symbol,
            "timeframe": cfg.timeframe,
            "auto_trade": cfg.auto_trade,
            "account": acct,
            "peak_equity": _state["peak_equity"],
            "config": cfg.to_dict(),
        }
    except MT5Error as e:
        return {"connected": False, "error": str(e)}


@mcp.tool()
def market_snapshot() -> dict:
    """Live bid/ask/spread and indicator values (ADX, RSI, Bollinger, ATR, momentum)."""
    _ensure_connected()
    return client.snapshot()


@mcp.tool()
def compute_current_signal() -> dict:
    """Regime (RANGE/TREND_UP/TREND_DOWN) and BUY/SELL confidence (0-100)."""
    _ensure_connected()
    snap = client.snapshot()
    sig = _signal_from_snapshot(snap)
    return {
        "regime": sig.regime,
        "buy_conf": sig.buy_conf,
        "sell_conf": sig.sell_conf,
        "momentum": sig.momentum,
        "conf_threshold": cfg.conf_threshold,
    }


@mcp.tool()
def basket_state() -> dict:
    """Current LONG/SHORT baskets: levels, avg price, volume, floating P/L."""
    _ensure_connected()
    long_b = client.basket("BUY")
    short_b = client.basket("SELL")
    return {
        "long": {"levels": long_b.levels, "avg": round(long_b.avg_price, 3),
                 "volume": round(long_b.volume, 2), "pl": round(long_b.pl, 2)},
        "short": {"levels": short_b.levels, "avg": round(short_b.avg_price, 3),
                  "volume": round(short_b.volume, 2), "pl": round(short_b.pl, 2)},
    }


@mcp.tool()
def plan_next_action() -> dict:
    """What the strategy would do right now (does NOT execute): OPEN/ADD/CLOSE/HOLD."""
    _ensure_connected()
    snap = client.snapshot()
    sig = _signal_from_snapshot(snap)
    acct = client.account()
    _state["peak_equity"] = max(_state["peak_equity"], acct["equity"])
    long_b = client.basket("BUY")
    short_b = client.basket("SELL")
    actions = plan_actions(
        cfg, sig, bid=snap["bid"], ask=snap["ask"], spread_points=snap["spread_points"],
        atr_value=snap["atr"], point=snap["point"], long_basket=long_b, short_basket=short_b,
        equity=acct["equity"], peak_equity=_state["peak_equity"],
    )
    return {
        "regime": sig.regime, "buy_conf": sig.buy_conf, "sell_conf": sig.sell_conf,
        "actions": [a.to_dict() for a in actions],
        "auto_trade": cfg.auto_trade,
    }


@mcp.tool()
def execute_plan(confirm: bool = False) -> dict:
    """Execute the strategy's recommended actions. Requires confirm=True AND
    auto_trade enabled. CLOSE/EMERGENCY_CLOSE run even with confirm=False for safety."""
    _ensure_connected()
    plan = plan_next_action()
    results = []
    for a in plan["actions"]:
        act, direction, lots = a["action"], a["direction"], a["lots"]
        if act in ("CLOSE", "EMERGENCY_CLOSE"):
            results.append({"action": a, "result": client.close_basket(direction)})
        elif act in ("OPEN", "ADD"):
            if not confirm:
                results.append({"action": a, "result": {"sent": False, "reason": "confirm=False"}})
            else:
                results.append({"action": a, "result": client.open_order(direction, lots, "xq-"+act.lower())})
        else:  # HOLD
            results.append({"action": a, "result": {"sent": False, "reason": "hold"}})
    return {"executed": results, "auto_trade": cfg.auto_trade}


@mcp.tool()
def place_order(direction: str, lots: float) -> dict:
    """Manually place a single market order (BUY/SELL). Honors auto_trade + lot caps."""
    _ensure_connected()
    d = direction.upper()
    if d not in ("BUY", "SELL"):
        return {"error": "direction must be BUY or SELL"}
    return client.open_order(d, lots, "xq-manual")


@mcp.tool()
def close_basket(direction: str) -> dict:
    """Close the entire LONG or SELL basket now."""
    _ensure_connected()
    d = direction.upper()
    if d not in ("BUY", "SELL"):
        return {"error": "direction must be BUY or SELL"}
    return client.close_basket(d)


@mcp.tool()
def emergency_close_all() -> dict:
    """Flatten both baskets immediately (panic button)."""
    _ensure_connected()
    return {"long": client.close_basket("BUY"), "short": client.close_basket("SELL")}


@mcp.tool()
def set_auto_trade(enabled: bool) -> dict:
    """Enable/disable live order execution for this session (default OFF)."""
    cfg.auto_trade = bool(enabled)
    return {"auto_trade": cfg.auto_trade}


if __name__ == "__main__":
    mcp.run()
