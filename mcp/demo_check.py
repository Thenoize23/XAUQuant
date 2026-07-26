"""Read-only live check: connect to MT5 and print what the MCP would do.

Places NO orders (auto_trade stays off). Proves the engine reads your live
terminal correctly. Run:  XQ_SYMBOL=XAUUSDun python demo_check.py
"""
from datetime import datetime, timezone

import protection
from config import Config
from mt5_client import MT5Client, MT5Error
from strategy import compute_signal, plan_actions

cfg = Config.from_env()
client = MT5Client(cfg)

try:
    info = client.connect()
except MT5Error as e:
    raise SystemExit(f"connect failed: {e}")

print("=== CONNECTION ===")
for k in ("login", "server", "balance", "equity", "currency", "trade_allowed"):
    print(f"  {k:14} {info.get(k)}")

snap = client.snapshot()
print("\n=== MARKET SNAPSHOT ({}) ===".format(cfg.symbol))
for k in ("bid", "ask", "spread_points", "adx", "rsi", "atr", "momentum"):
    print(f"  {k:14} {snap[k]}")

sig = compute_signal(
    cfg, adx_val=snap["adx"], plus_di=snap["plus_di"], minus_di=snap["minus_di"],
    rsi_val=snap["rsi"], bb_mid=snap["bb_mid"], bb_up=snap["bb_upper"],
    bb_low=snap["bb_lower"], price=snap["last_close"], mom=snap["momentum"],
)
print("\n=== SIGNAL ===")
print(f"  regime    {sig.regime}")
print(f"  BUY conf  {sig.buy_conf}   SELL conf  {sig.sell_conf}   (threshold {cfg.conf_threshold})")

long_b, short_b = client.basket("BUY"), client.basket("SELL")
print("\n=== BASKETS ===")
print(f"  LONG  levels={long_b.levels} vol={long_b.volume:.2f} avg={long_b.avg_price:.3f} pl={long_b.pl:.2f}")
print(f"  SHORT levels={short_b.levels} vol={short_b.volume:.2f} avg={short_b.avg_price:.3f} pl={short_b.pl:.2f}")

now = datetime.now(timezone.utc)
block = protection.protection_reason(now, cfg)
print("\n=== ANTI-SHOCK ===")
print(f"  utc_now={now:%Y-%m-%d %H:%M}  weekend_flatten={cfg.weekend_flatten}  block={block}")

print("\n=== PLAN (what it WOULD do — nothing is sent) ===")
if block:
    print(f"  PROTECTED ({block}) -> flatten & pause")
else:
    acct = client.account()
    actions = plan_actions(
        cfg, sig, bid=snap["bid"], ask=snap["ask"], spread_points=snap["spread_points"],
        atr_value=snap["atr"], point=snap["point"], long_basket=long_b, short_basket=short_b,
        equity=acct["equity"], peak_equity=acct["equity"],
    )
    for a in actions:
        print("  ", a.to_dict())

print(f"\n  auto_trade = {cfg.auto_trade}  (False = read-only, no orders sent)")
client.shutdown()
