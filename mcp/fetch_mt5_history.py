"""Export real XAUUSD history from YOUR MetaTrader 5 terminal to a CSV,
so backtest.py can run on years of TíoMarkets data (including bad regimes
that the 60-day Yahoo sample can't show).

Run on your Windows machine with MT5 open and logged in:

    python fetch_mt5_history.py --symbol XAUUSD --timeframe M1 --years 3 --out data/xauusd_m1.csv
    python backtest.py data/xauusd_m1.csv
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta

try:
    import MetaTrader5 as mt5
except ImportError:
    raise SystemExit("MetaTrader5 package not installed. pip install MetaTrader5 (Windows only).")

_TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
       "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
       "D1": mt5.TIMEFRAME_D1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframe", default="M1", choices=list(_TF))
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--out", default="data/xauusd_m1.csv")
    args = ap.parse_args()

    if not mt5.initialize():
        raise SystemExit(f"mt5.initialize() failed: {mt5.last_error()}")
    if not mt5.symbol_select(args.symbol, True):
        raise SystemExit(f"cannot select {args.symbol}: {mt5.last_error()}")

    utc_to = datetime.now()
    utc_from = utc_to - timedelta(days=int(args.years * 365))
    rates = mt5.copy_rates_range(args.symbol, _TF[args.timeframe], utc_from, utc_to)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        raise SystemExit("no bars returned — scroll the symbol's chart back in MT5 to load history, then retry.")

    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close"])
        for r in rates:
            w.writerow([int(r["time"]), r["open"], r["high"], r["low"], r["close"]])
    print(f"wrote {len(rates)} bars to {args.out}  ({args.symbol} {args.timeframe}, ~{args.years}y)")
    print(f"now run:  python backtest.py {args.out}")


if __name__ == "__main__":
    main()
