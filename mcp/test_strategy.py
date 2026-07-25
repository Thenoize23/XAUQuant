"""Offline smoke test for the pure strategy + indicators (no MetaTrader needed).

Run:  python test_strategy.py
"""
import numpy as np

import indicators as ind
from config import Config
from strategy import Basket, compute_signal, plan_actions, next_level_lot


def synthetic_series(n=400, seed=7):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.5, n).cumsum()
    close = 4000 + steps
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    return high, low, close


def test_indicators():
    high, low, close = synthetic_series()
    r = ind.rsi(close, 14)
    a = ind.atr(high, low, close, 14)
    mid, up, lo = ind.bollinger(close, 20, 2.0)
    adx_val, pdi, mdi = ind.adx(high, low, close, 14)
    mom = ind.momentum(close, 14)
    assert 0 <= r <= 100, r
    assert a > 0, a
    assert lo < mid < up, (lo, mid, up)
    assert adx_val >= 0 and pdi >= 0 and mdi >= 0, (adx_val, pdi, mdi)
    assert mom > 0, mom
    print(f"indicators OK: rsi={r:.1f} atr={a:.3f} adx={adx_val:.1f} mom={mom:.2f}")


def test_signal_and_plan():
    cfg = Config()
    # force a strong oversold buy setup in a range
    sig = compute_signal(
        cfg, adx_val=15, plus_di=20, minus_di=18, rsi_val=22,
        bb_mid=4000, bb_up=4010, bb_low=3990, price=3989, mom=99.0,
    )
    assert sig.regime == "RANGE", sig.regime
    assert sig.buy_conf > sig.sell_conf, (sig.buy_conf, sig.sell_conf)
    print(f"signal OK: regime={sig.regime} buy={sig.buy_conf} sell={sig.sell_conf}")

    # empty baskets -> should recommend OPEN BUY if conf clears threshold
    empty_long = Basket("BUY")
    empty_short = Basket("SELL")
    cfg.conf_threshold = min(cfg.conf_threshold, sig.buy_conf)
    actions = plan_actions(
        cfg, sig, bid=3989, ask=3989.2, spread_points=2, atr_value=1.0, point=0.01,
        long_basket=empty_long, short_basket=empty_short, equity=10000, peak_equity=10000,
    )
    kinds = {(a.action, a.direction) for a in actions}
    assert ("OPEN", "BUY") in kinds, kinds
    print(f"entry plan OK: {[a.to_dict() for a in actions]}")

    # open long basket deep in profit -> should CLOSE
    lb = Basket("BUY", levels=10, volume=0.1, avg_price=3980, pl=999, worst_price=3970)
    actions = plan_actions(
        cfg, sig, bid=3995, ask=3995.2, spread_points=2, atr_value=1.0, point=0.01,
        long_basket=lb, short_basket=empty_short, equity=10999, peak_equity=11000,
    )
    assert any(a.action == "CLOSE" and a.direction == "BUY" for a in actions), actions
    print("exit plan OK: CLOSE triggered at target")

    # emergency drawdown
    actions = plan_actions(
        cfg, sig, bid=3960, ask=3960.2, spread_points=2, atr_value=1.0, point=0.01,
        long_basket=lb, short_basket=empty_short, equity=8000, peak_equity=11000,
    )
    assert any(a.action == "EMERGENCY_CLOSE" for a in actions), actions
    print("guardrail OK: EMERGENCY_CLOSE at drawdown")

    # martingale lot growth
    lots = [next_level_lot(cfg, i) for i in range(4)]
    assert lots[1] > lots[0], lots
    print(f"lot scaling OK: {lots}")


if __name__ == "__main__":
    test_indicators()
    test_signal_and_plan()
    print("\nALL TESTS PASSED")
