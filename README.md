# XAUQuant

Grid / martingale **basket EA for MetaTrader 5** on **XAUUSD (M1)**, with a regime +
confidence signal engine and an on-chart dashboard — a clean-room re-implementation of
the *feature set* shown in a public "XAU QUANT" livestream demo.

> ⚠️ **Read this first.** This EA uses a **martingale grid**: it averages into a losing
> position by adding levels. In the reference video the account tolerated a **−$436,060
> floating drawdown** before recovering. Martingale grids can and do **blow up accounts**
> when price does not revert. This code is for **education and backtesting only**. It is
> **not** financial advice. Trade it on a **demo account** first. Use at your own risk.

## What it does

| Component | Behaviour |
|---|---|
| **Regime detector** | Classifies the market as `RANGE`, `TREND UP`, or `TREND DOWN` (ADX + DI). |
| **Confidence score** | `BUY CONF` / `SELL CONF` (0–100) from Bollinger mean-reversion + RSI, biased by regime. |
| **Entry** | Opens the first basket level when confidence ≥ threshold and the regime allows the direction. |
| **Grid (martingale)** | Adds levels as price moves against the basket, spaced by fixed points or ATR, lot scaled by a multiplier. |
| **Basket exit** | Closes the **whole** basket once aggregate P/L hits the money/points target, then increments *Closed baskets*. |
| **Guardrails** | Max levels cap, per-order lot cap, max-spread filter, and an **emergency equity-drawdown stop** that flattens everything. |
| **Dashboard** | On-chart panel mimicking the reference: regime, confidence, long/short basket stats, momentum, balance/equity, closed baskets. |
| **Entry alert banner** | On each order, flashes a strip at the **bottom of the panel**: green **`BUY EXECUTED`** / red **`SELL EXECUTED`**, auto-hiding after a few seconds; optional `Alert()` popup and push notification. |

## Two runtimes

| Runtime | Path | Use when |
|---|---|---|
| **MT5 Expert Advisor** | `Experts/XAUQuant.mq5` | Your broker allows EAs attached to the chart. |
| **MCP server (Python)** | [`mcp/`](mcp/) | Your broker blocks chart EAs but the MT5 terminal can still trade. Drives the same strategy from Python via the `MetaTrader5` package and exposes it to Claude as MCP tools — no EA on the chart. |

Both share the same strategy logic (regime + confidence + basket grid + guardrails).

## Why this is a *re-implementation*, not a copy

The reference video is a **sales livestream of a closed-source EA** — no code or exact rules
are shown. The strategy here was reconstructed from what the on-screen panel revealed during
live trades (grid direction, level counts, average price, basket P/L, regime and confidence
values). The signal math and all thresholds are original and fully parameterised.

## Install

1. Copy `Experts/XAUQuant.mq5` into your terminal's `MQL5/Experts/` folder
   (in MetaTrader 5: **File → Open Data Folder → MQL5 → Experts**).
2. Open it in **MetaEditor** and press **F7** to compile → `XAUQuant.ex5`.
3. Attach it to an **XAUUSD, M1** chart. Enable **Algo Trading**.

## Backtest before anything else

Use the **Strategy Tester** (Ctrl+R) on XAUUSD M1 with real-tick data:

- Start with **conservative inputs**: `InpMaxLevels = 6`, `InpLotMultiplier = 1.3`,
  `InpMaxDrawdownPct = 15`, `InpBaseLot = 0.01`.
- Watch the **equity drawdown**, not just the profit curve — that is where martingale risk hides.

## Key inputs

See the grouped inputs in `Experts/XAUQuant.mq5`. Most important:

- `InpMaxLevels` — hard cap on grid depth (the main risk dial).
- `InpLotMultiplier` / `InpLotMode` — how aggressively lots scale per level.
- `InpStepMode` + `InpGridStepPoints` / `InpATRStepMult` — grid spacing.
- `InpTargetMode` + `InpTargetMoney` / `InpTargetPoints` — basket take-profit.
- `InpMaxDrawdownPct` — emergency flatten-everything guardrail.

## Strategy detail

See [`docs/STRATEGY.md`](docs/STRATEGY.md) for the reverse-engineering notes and signal math.

## Disclaimer

Trading leveraged products carries a high risk of loss. Nothing here is investment advice.
The authors accept no liability for any losses. Licensed under the MIT License.
