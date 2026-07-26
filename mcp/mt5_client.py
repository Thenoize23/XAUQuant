"""Thin wrapper over the MetaTrader5 Python package.

Reads prices/indicators and (optionally) places & manages orders directly
through the running MT5 terminal — no chart-attached EA required.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

try:
    import MetaTrader5 as mt5
except ImportError:  # allow import on non-Windows for tests
    mt5 = None

import indicators as ind
from config import Config
from strategy import Basket

_TF = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 16385, "H4": 16388, "D1": 16408,
}


class MT5Error(RuntimeError):
    pass


def _require():
    if mt5 is None:
        raise MT5Error("MetaTrader5 package not installed (Windows only). pip install MetaTrader5")


class MT5Client:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._connected = False

    # ----------------------------------------------------------- lifecycle ---
    def connect(self) -> dict:
        _require()
        ok = mt5.initialize(self.cfg.mt5_path) if self.cfg.mt5_path else mt5.initialize()
        if not ok:
            raise MT5Error(f"mt5.initialize() failed: {mt5.last_error()}")
        if not mt5.symbol_select(self.cfg.symbol, True):
            raise MT5Error(f"cannot select symbol {self.cfg.symbol}: {mt5.last_error()}")
        self._connected = True
        info = mt5.account_info()
        term = mt5.terminal_info()
        return {
            "connected": True,
            "symbol": self.cfg.symbol,
            "login": getattr(info, "login", None),
            "server": getattr(info, "server", None),
            "balance": getattr(info, "balance", None),
            "equity": getattr(info, "equity", None),
            "currency": getattr(info, "currency", None),
            "trade_allowed": getattr(term, "trade_allowed", None),
            "trade_expert": getattr(info, "trade_expert", None),  # False = broker blocks automation
        }

    def shutdown(self):
        if mt5 is not None and self._connected:
            mt5.shutdown()
            self._connected = False

    # ------------------------------------------------------------- reading ---
    def _tf(self) -> int:
        return _TF.get(self.cfg.timeframe.upper(), 1)

    def _point(self) -> float:
        return mt5.symbol_info(self.cfg.symbol).point

    def snapshot(self) -> dict:
        """Price + indicators computed on closed bars."""
        _require()
        cfg = self.cfg
        n = max(cfg.adx_period, cfg.rsi_period, cfg.bb_period,
                cfg.atr_period, cfg.mom_period, cfg.ma_period) * 6 + 50
        rates = mt5.copy_rates_from_pos(cfg.symbol, self._tf(), 0, n)
        if rates is None or len(rates) < 50:
            raise MT5Error(f"not enough history for {cfg.symbol}: {mt5.last_error()}")

        # use closed bars (drop the still-forming bar 0)
        high = rates["high"][:-1]
        low = rates["low"][:-1]
        close = rates["close"][:-1]

        adx_val, plus_di, minus_di = ind.adx(high, low, close, cfg.adx_period)
        rsi_val = ind.rsi(close, cfg.rsi_period)
        bb_mid, bb_up, bb_low = ind.bollinger(close, cfg.bb_period, cfg.bb_dev)
        atr_val = ind.atr(high, low, close, cfg.atr_period)
        mom = ind.momentum(close, cfg.mom_period)

        tick = mt5.symbol_info_tick(cfg.symbol)
        point = self._point()
        spread_points = (tick.ask - tick.bid) / point
        return {
            "bid": tick.bid, "ask": tick.ask, "spread_points": round(spread_points, 1),
            "point": point, "last_close": float(close[-1]),
            "adx": round(adx_val, 2), "plus_di": round(plus_di, 2), "minus_di": round(minus_di, 2),
            "rsi": round(rsi_val, 2),
            "bb_mid": bb_mid, "bb_upper": bb_up, "bb_lower": bb_low,
            "atr": atr_val, "momentum": round(mom, 2),
        }

    def account(self) -> dict:
        info = mt5.account_info()
        return {
            "balance": info.balance, "equity": info.equity,
            "margin": info.margin, "free_margin": info.margin_free,
            "currency": info.currency,
        }

    def basket(self, direction: str) -> Basket:
        """Aggregate open positions (this symbol+magic+direction) into a Basket."""
        _require()
        want = mt5.POSITION_TYPE_BUY if direction == "BUY" else mt5.POSITION_TYPE_SELL
        positions = mt5.positions_get(symbol=self.cfg.symbol) or []
        b = Basket(direction=direction)
        weighted = 0.0
        worst = None
        for p in positions:
            if p.magic != self.cfg.magic or p.type != want:
                continue
            b.levels += 1
            b.volume += p.volume
            weighted += p.volume * p.price_open
            b.pl += p.profit + p.swap
            if direction == "BUY":
                worst = p.price_open if worst is None else min(worst, p.price_open)
            else:
                worst = p.price_open if worst is None else max(worst, p.price_open)
        if b.volume > 0:
            b.avg_price = weighted / b.volume
            b.worst_price = worst
        return b

    # ----------------------------------------------------------- executing ---
    def _filling(self):
        """Pick a filling mode the symbol actually supports (avoids retcode 10030)."""
        fm = mt5.symbol_info(self.cfg.symbol).filling_mode
        if fm & 1:   # SYMBOL_FILLING_FOK
            return mt5.ORDER_FILLING_FOK
        if fm & 2:   # SYMBOL_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def _norm_lot(self, lot: float) -> float:
        si = mt5.symbol_info(self.cfg.symbol)
        step = si.volume_step or 0.01
        lot = min(lot, self.cfg.max_lot_per_order, si.volume_max)
        lot = max(lot, si.volume_min)
        return round(round(lot / step) * step, 2)

    def open_order(self, direction: str, lots: float, comment: str = "xq") -> dict:
        _require()
        if not self.cfg.auto_trade:
            return {"sent": False, "reason": "auto_trade disabled (safety)"}
        si = mt5.symbol_info(self.cfg.symbol)
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        is_buy = direction == "BUY"
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.cfg.symbol,
            "volume": self._norm_lot(lots),
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if is_buy else tick.bid,
            "deviation": self.cfg.deviation_points,
            "magic": self.cfg.magic,
            "comment": comment,
            "type_filling": self._filling(),
            "type_time": mt5.ORDER_TIME_GTC,
        }
        res = mt5.order_send(req)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        return {
            "sent": True, "ok": ok,
            "retcode": getattr(res, "retcode", None),
            "comment": getattr(res, "comment", None),
            "volume": getattr(res, "volume", None),
            "price": getattr(res, "price", None),
        }

    def close_basket(self, direction: str) -> dict:
        _require()
        if not self.cfg.auto_trade:
            return {"sent": False, "reason": "auto_trade disabled (safety)"}
        want = mt5.POSITION_TYPE_BUY if direction == "BUY" else mt5.POSITION_TYPE_SELL
        positions = mt5.positions_get(symbol=self.cfg.symbol) or []
        closed, errors = 0, []
        for p in positions:
            if p.magic != self.cfg.magic or p.type != want:
                continue
            tick = mt5.symbol_info_tick(self.cfg.symbol)
            is_buy = p.type == mt5.POSITION_TYPE_BUY
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.cfg.symbol,
                "volume": p.volume,
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": p.ticket,
                "price": tick.bid if is_buy else tick.ask,
                "deviation": self.cfg.deviation_points,
                "magic": self.cfg.magic,
                "comment": "xq-close",
                "type_filling": self._filling(),
                "type_time": mt5.ORDER_TIME_GTC,
            }
            res = mt5.order_send(req)
            if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1
            else:
                errors.append(getattr(res, "retcode", "no-result"))
        return {"sent": True, "closed": closed, "errors": errors}
