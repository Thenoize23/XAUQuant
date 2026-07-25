"""Run every backtest scenario and print one consolidated markdown table."""
import dataclasses
import backtest as bt
from config import Config

DATA = {
    "1m 7d":  "data/gold_1m.csv",
    "2m 60d": "data/gold_2m.csv",
    "5m 60d": "data/gold_5m.csv",
}
loaded = {k: bt.load_csv(v) for k, v in DATA.items()}
syn = bt.generate(20000)

def cfg(**over):
    c = Config()
    for k, v in over.items():
        setattr(c, k, v)
    return c

# (label, dataset key or "syn", config overrides)
SCEN = [
    ("Oro 1m 7d",              "1m 7d",  {}),
    ("Oro 2m 60d",             "2m 60d", {}),
    ("Oro 5m 60d",             "5m 60d", {}),
    ("Oro 5m  mult2.0",        "5m 60d", {"lot_multiplier": 2.0}),
    ("Oro 2m  mult2.0 sinGuard","2m 60d",{"lot_multiplier": 2.0, "max_drawdown_pct": 99}),
    ("Oro 1m  mult2.0 lvl20",  "1m 7d",  {"lot_multiplier": 2.0, "max_levels": 20}),
    ("Sintetico+shocks 20k",   "syn",    {}),
]

rows = []
for label, key, over in SCEN:
    t, o, h, l, c = syn if key == "syn" else loaded[key]
    r = bt.run(cfg(**over), t, o, h, l, c, verbose=False)
    rows.append((label, r))

hdr = ["Escenario", "Net $", "Return %", "MaxDD %", "Cestas", "Win %", "MaxNiv", "MaxLotes", "Revento"]
print("| " + " | ".join(hdr) + " |")
print("|" + "|".join(["---"] * len(hdr)) + "|")
for label, r in rows:
    print("| {} | {:+,.0f} | {:+.1f} | {:.1f} | {} | {:.0f} | {} | {:.2f} | {} |".format(
        label, r["net_profit"], r["return_pct"], r["max_drawdown_pct"],
        r["baskets_closed"], r["win_rate_pct"], r["max_grid_levels"],
        r["max_basket_lots"], "SI" if r["blew_up"] else "no"))
