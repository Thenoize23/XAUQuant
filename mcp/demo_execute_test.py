"""One-shot EXECUTION test on the DEMO account: place a minimum-lot order,
show it, then close it. Proves the MCP can actually trade.

Safe: demo only, minimum lot, opens then closes the same basket.
Requires: MT5 logged into the DEMO account AND the 'Algo Trading' button ON.

Run:  XQ_SYMBOL=DOGEUSD XQ_AUTO_TRADE=true python demo_execute_test.py
"""
import time

from config import Config
from mt5_client import MT5Client, MT5Error

cfg = Config.from_env()
client = MT5Client(cfg)

info = client.connect()
print("=== ACCOUNT ===")
print(f"  {info.get('login')} {info.get('server')} | balance {info.get('balance')} "
      f"| trade_allowed {info.get('trade_allowed')}")

if "DEMO" not in str(info.get("server", "")).upper():
    raise SystemExit("SAFETY STOP: not a DEMO account — refusing to place orders.")
if not info.get("trade_allowed"):
    raise SystemExit("Algo Trading is OFF. Click the 'Algo Trading' button in MT5 "
                     "(top toolbar, must turn green), then re-run.")

# Broker-side automated-trading permission (the real gate on TíoMarkets)
import MetaTrader5 as _mt5
if not _mt5.account_info().trade_expert:
    raise SystemExit(
        "BROKER BLOCK: account.trade_expert = False — this server disables ALL\n"
        "automated order execution (EAs and the Python API alike). The MCP can\n"
        "still read signals and produce the plan; execution must be done MANUALLY,\n"
        "or ask the broker to enable algo trading / use a broker that allows it.")
if not cfg.auto_trade:
    raise SystemExit("auto_trade is off. Run with XQ_AUTO_TRADE=true.")

print(f"\n=== PLACING min-lot BUY on {cfg.symbol} ===")
res = client.open_order("BUY", cfg.base_lot, "xq-exectest")
print("  order result:", res)

time.sleep(1.0)   # let MT5 reflect the new position before reading
b = client.basket("BUY")
print(f"  basket now: levels={b.levels} vol={b.volume} avg={b.avg_price:.5f} pl={b.pl:.2f}")
print("  >>> look at MT5 'Trade' tab — the position should be there. Closing in 4s...")
time.sleep(4)

print("\n=== CLOSING the basket ===")
print("  close result:", client.close_basket("BUY"))
print("  basket after:", client.basket("BUY").levels, "levels (0 = closed)")
print("\nDONE — execution round-trip works.")
client.shutdown()
