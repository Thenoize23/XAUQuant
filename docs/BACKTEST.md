# Backtest results & honest interpretation

The MQL5 EA and the Python MCP **share the same strategy logic**, so this one
Python backtest (`mcp/backtest.py`) represents both. Running the MT5 Strategy
Tester on the EA is still worthwhile — matching numbers confirms the port.

## Method

- Bar-based simulation over XAUUSD/gold OHLC.
- Reuses the live signal engine (`strategy.compute_signal`) and the same config
  thresholds. Martingale basket simulated **intrabar**: grid adds on the bar's
  adverse extreme, basket take-profit on the favourable extreme.
- Models spread (20 pts), leverage 1:100, and a broker **stop-out at 50% of used
  margin** (blow-up). See the constants at the top of `backtest.py`.
- Data: gold futures (`GC=F`) 1m/2m/5m pulled from Yahoo (free, but only ~7–60
  days of intraday). **Short and recent** — this is the key caveat.

## Results (default config, $10,000 start)

| Data | Bars | Net profit | Return | Max DD | Baskets | Win rate | Blew up? |
|---|---|---|---|---|---|---|---|
| Gold 1m (7d)  | 7,873  | +$41,117 | +411% | 4.6%  | 114 | 100% | no |
| Gold 2m (60d) | 17,519 | +$45,238 | +452% | 18.0% | 297 | 100% | no |
| Gold 5m (60d) | 13,783 | +$43,417 | +434% | 23.3% | 341 | 100% | no |
| Synthetic + shocks (20k) | 20,000 | −$1,649 | −16% | 19.9% | 12 | 91.7% | **YES** |

Stress variants on the 5m/2m set: turning the drawdown guardrail off changed
nothing (it never triggered — DD peaked at 23.3%); a 2.0 lot multiplier looked
*better* (+515% / +1524%, DD 3–4%) because doubling closes baskets faster — right
up until the move that doesn't revert.

## What this actually means (read this)

- **+400% with a 100% win rate is not a good sign — it's the martingale mirage.**
  Averaging down wins almost every basket and draws a smooth rising equity curve…
  until one sustained adverse move keeps stacking levels and wipes the account.
- The real windows here were **kind**: gold chopped/trended-up enough that every
  dip reverted. **None contained the killer scenario** (a long one-directional run
  or a weekend gap). The 5m set already crept to **23.3% drawdown — one bad move
  from the 25% guardrail flattening everything.**
- The synthetic run *with shocks* is the honest preview: **91.7% win rate, then a
  margin call.** That is how this strategy fails.

## Verdict

On this data the strategy is **not proven profitable — it is proven to survive a
short, favourable sample.** To trust it you need a real verdict over years of M1
that include bad regimes (2020 crash, strong trends, gaps). Yahoo can't provide
that; your MT5 terminal can:

```
python fetch_mt5_history.py --symbol XAUUSD --timeframe M1 --years 3 --out data/xauusd_m1.csv
python backtest.py data/xauusd_m1.csv
```

Then compare against the MT5 Strategy Tester (below). Treat any result with a
100% win rate and a big return as a **risk profile to distrust**, not a green light.

## Running the EA in the MT5 Strategy Tester (to confirm the port)

1. MetaTrader 5 → **View → Strategy Tester** (Ctrl+R).
2. Expert: `XAUQuant`, Symbol: `XAUUSD`, Period: `M1`, Model: **Every tick based on real ticks**.
3. Set inputs to match the backtest (e.g. `InpMaxLevels=15`, `InpLotMultiplier=1.5`,
   `InpTargetMoney=50`, `InpMaxDrawdownPct=25`).
4. Compare net profit / max drawdown / trade count with `backtest.py` on the same
   period. Close numbers = the MQL5 EA and the Python MCP are equivalent.
