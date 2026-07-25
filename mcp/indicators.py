"""Minimal, dependency-light technical indicators (numpy only).

Two APIs per indicator:
  * ``*_series`` returns the full aligned array (used by the backtester)
  * scalar wrapper returns the latest value (used by the live engine)

Smoothing uses Wilder's RMA to match MetaTrader.
"""
from __future__ import annotations

import numpy as np


def _rma(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothed moving average (a.k.a. RMA), full series."""
    values = np.asarray(values, dtype=float)
    out = np.full_like(values, np.nan)
    if len(values) < period:
        return out
    out[period - 1] = values[:period].mean()
    alpha = 1.0 / period
    for i in range(period, len(values)):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])
    return out


def _rolling_mean(x: np.ndarray, w: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[w - 1:] = (c[w:] - c[:-w]) / w
    return out


def _rolling_std(x: np.ndarray, w: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        c1 = np.cumsum(np.insert(x, 0, 0.0))
        c2 = np.cumsum(np.insert(x * x, 0, 0.0))
        s = c1[w:] - c1[:-w]
        s2 = c2[w:] - c2[:-w]
        var = np.maximum(s2 / w - (s / w) ** 2, 0.0)
        out[w - 1:] = np.sqrt(var)
    return out


# ----------------------------------------------------------------- RSI ---
def rsi_series(close: np.ndarray, period: int) -> np.ndarray:
    close = np.asarray(close, dtype=float)
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    ag = _rma(gain, period)
    al = _rma(loss, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
        out = 100.0 - 100.0 / (1.0 + rs)
    out = np.where(al == 0, 100.0, out)
    return out


def rsi(close, period): return float(rsi_series(close, period)[-1])


# ----------------------------------------------------------------- ATR ---
def atr_series(high, low, close, period) -> np.ndarray:
    high = np.asarray(high, float); low = np.asarray(low, float); close = np.asarray(close, float)
    prev = np.roll(close, 1)
    tr = np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)])
    tr[0] = high[0] - low[0]
    return _rma(tr, period)


def atr(high, low, close, period): return float(atr_series(high, low, close, period)[-1])


# ---------------------------------------------------------- Bollinger ---
def bollinger_series(close, period, dev):
    close = np.asarray(close, float)
    mid = _rolling_mean(close, period)
    sd = _rolling_std(close, period)
    return mid, mid + dev * sd, mid - dev * sd


def bollinger(close, period, dev):
    mid, up, lo = bollinger_series(close, period, dev)
    return float(mid[-1]), float(up[-1]), float(lo[-1])


# ----------------------------------------------------------- Momentum ---
def momentum_series(close, period) -> np.ndarray:
    close = np.asarray(close, float)
    out = np.full(len(close), 100.0)
    if len(close) > period:
        out[period:] = close[period:] / close[:-period] * 100.0
    return out


def momentum(close, period): return float(momentum_series(close, period)[-1])


# ----------------------------------------------------------------- ADX ---
def adx_series(high, low, close, period):
    """Returns (adx, plus_di, minus_di) arrays aligned to the close index."""
    high = np.asarray(high, float); low = np.asarray(low, float); close = np.asarray(close, float)
    n = len(close)
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    prev = close[:-1]
    tr = np.maximum.reduce([high[1:] - low[1:], np.abs(high[1:] - prev), np.abs(low[1:] - prev)])

    atr_s = _rma(tr, period)
    plus_s = _rma(plus_dm, period)
    minus_s = _rma(minus_dm, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100.0 * plus_s / atr_s
        mdi = 100.0 * minus_s / atr_s
        dx = 100.0 * np.abs(pdi - mdi) / (pdi + mdi)
    dx = np.nan_to_num(dx, nan=0.0, posinf=0.0, neginf=0.0)
    adx_s = _rma(dx, period)

    # pad front (diff arrays are length n-1) so everything aligns to close index
    pad = lambda a: np.concatenate(([np.nan], a))
    return (np.nan_to_num(pad(adx_s)), np.nan_to_num(pad(pdi)), np.nan_to_num(pad(mdi)))


def adx(high, low, close, period):
    a, p, m = adx_series(high, low, close, period)
    return float(a[-1]), float(p[-1]), float(m[-1])
