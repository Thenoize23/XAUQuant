"""Minimal, dependency-light technical indicators (numpy only).

Each function takes numpy arrays of OHLC data (oldest -> newest) and returns
the latest value(s). Smoothing uses Wilder's RMA to match MetaTrader.
"""
from __future__ import annotations

import numpy as np


def _rma(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothed moving average (a.k.a. RMA), full series."""
    values = np.asarray(values, dtype=float)
    out = np.full_like(values, np.nan)
    if len(values) < period:
        return out
    # seed with simple average of the first `period` values
    seed = values[:period].mean()
    out[period - 1] = seed
    alpha = 1.0 / period
    for i in range(period, len(values)):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])
    return out


def rsi(close: np.ndarray, period: int) -> float:
    close = np.asarray(close, dtype=float)
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = _rma(gain, period)[-1]
    avg_loss = _rma(loss, period)[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    prev_close = np.roll(close, 1)
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    tr[0] = high[0] - low[0]
    return float(_rma(tr, period)[-1])


def bollinger(close: np.ndarray, period: int, dev: float):
    close = np.asarray(close, dtype=float)
    window = close[-period:]
    mid = float(window.mean())
    sd = float(window.std(ddof=0))
    upper = mid + dev * sd
    lower = mid - dev * sd
    return mid, upper, lower


def momentum(close: np.ndarray, period: int) -> float:
    """MetaTrader iMomentum: close[now] / close[now-period] * 100."""
    close = np.asarray(close, dtype=float)
    if len(close) <= period:
        return 100.0
    return float(close[-1] / close[-1 - period] * 100.0)


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int):
    """Returns (adx, plus_di, minus_di) latest values."""
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)

    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = close[:-1]
    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - prev_close),
        np.abs(low[1:] - prev_close),
    ])

    atr_s = _rma(tr, period)
    plus_s = _rma(plus_dm, period)
    minus_s = _rma(minus_dm, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * plus_s / atr_s
        minus_di = 100.0 * minus_s / atr_s
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    dx = np.nan_to_num(dx, nan=0.0, posinf=0.0, neginf=0.0)

    adx_series = _rma(dx, period)
    return (
        float(np.nan_to_num(adx_series[-1])),
        float(np.nan_to_num(plus_di[-1])),
        float(np.nan_to_num(minus_di[-1])),
    )
