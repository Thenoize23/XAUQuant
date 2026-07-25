# Strategy notes — reverse-engineered from the "XAU QUANT" livestream

The reference is a public livestream that trades a **closed-source** XAUUSD EA on a
multi-million-dollar "account management" demo. No source or rules are shown. Everything
below was read directly off the EA's on-chart panel during live trades.

## What the panel showed (observed facts)

- **Symbol / TF:** XAUUSD on a low timeframe (M1-style price action).
- **Regime line:** cycled through `RANGE`, `TREND UP`, `TREND DOWN`.
- **Confidence:** `BUY CONF` and `SELL CONF`, 0–100, roughly mutually exclusive
  (when one side was high the other was ~0).
- **Baskets:** separate `LONG BASKET` and `SHORT BASKET`, each showing
  `Levels`, `Avg` (average entry), `Vol` (total volume), `P/L`.
- **Closed baskets:** a running counter that incremented over the session.
- **Momentum:** a histogram.
- **Account:** `Balance` and `Equity` (equity < balance while a basket floated red).

### Concrete captures

| Time in stream | Regime | BUY / SELL conf | Basket | Levels | Vol | P/L | Balance |
|---|---|---|---|---|---|---|---|
| ~02:10 | TREND UP | 35 / 0 | LONG | 10 | 2000 | **−436,060** | 2,608,720 |
| ~09:18 | RANGE | 52 / 0 | LONG | 10 | 2000 | −128,060 | 2,608,720 |
| ~16:25 | TREND UP | 70 / 0 | flat | — | — | 0 | **3,282,780** (closed +674k, "Closed baskets: 1") |
| ~30:41 | RANGE | 68 / 0 | LONG (new) | 10 | 2000 | −397,200 | 3,282,780 |
| ~7:02:43 | TREND DOWN | 0 / 64 | SHORT | 1024 | 10.24 | +16,129 | 6,660,574 ("Closed baskets: 18") |

**Read of the mechanics:**

1. **It is a martingale grid basket.** A basket opens in one direction, then **adds levels**
   averaging the entry as price moves against it, and closes the **entire basket** once the
   aggregate P/L turns positive by some target. The huge tolerated floating loss
   (−436k on ~2.6M ≈ −17%) that later closed in profit is the martingale signature.
2. **Bi-directional, regime-gated.** Long baskets appeared with high `BUY CONF` in
   `RANGE`/`TREND UP`; the short basket appeared with high `SELL CONF` in `TREND DOWN`.
3. **Level/lot scaling varied** across the session (`10 × 200` early; `1024 × 0.01` later),
   i.e. the grid depth and base lot are configurable.
4. **Confidence is mean-reversion flavoured** — in the first (unrelated-audio) demo, when the
   regime flipped to TREND UP the BUY CONF *dropped*, consistent with a "buy weakness / sell
   strength" score rather than trend-following.

## Our re-implementation

Because no rules are published, the signal math is **original** and designed to reproduce the
*observable behaviour*, not to clone a hidden algorithm.

### Regime (`ENUM_REGIME`)
- `ADX(InpADXPeriod)`; if `ADX < InpADXTrendLevel` → **RANGE**.
- Else `+DI ≥ −DI` → **TREND UP**, otherwise **TREND DOWN**.

### Confidence (0–100)
- Mean-reversion component from **Bollinger Bands**: buy strength grows as price sinks from the
  basis toward/below the lower band; sell strength mirrors it toward the upper band.
- Momentum/exhaustion component from **RSI** (oversold → buy, overbought → sell).
- Combined `0.6·BB + 0.4·RSI`, then **regime-biased** (trend continuation boosted, counter-trend damped).
- Scaled to 0–100.

### Entry
- Open the first level of a basket when `conf ≥ InpConfThreshold`, the regime allows the
  direction (no longs in TREND DOWN, no shorts in TREND UP), spread is acceptable, and no basket
  of that direction is already open.

### Grid add (martingale)
- When price is `≥ GridStep` beyond the worst existing level, add a new level.
- `GridStep` = fixed points **or** `ATR × InpATRStepMult`.
- Level lot = `InpBaseLot × InpLotMultiplier^level` (or fixed), capped by `InpMaxLotPerOrder`.
- Never exceed `InpMaxLevels` (**guardrail**, default 15 — far below the 1024 seen in the video).

### Basket exit
- Close the **whole** basket when aggregate P/L ≥ target (`InpTargetMoney` money mode, or
  `InpTargetPoints` from the average price). Increment the persistent *Closed baskets* counter.

### Guardrails (added for safety — not in the original)
- `InpMaxLevels` grid-depth cap.
- `InpMaxLotPerOrder` per-order lot cap.
- `InpMaxSpreadPoints` entry filter.
- `InpMaxDrawdownPct` **emergency stop**: if equity draws down this % from its peak, flatten all
  baskets and (optionally) halt trading.

## Honest risk note

The reference account "worked" precisely because it could absorb six-figure floating losses and
wait for mean reversion in gold. On a normal-sized retail account, the same mechanic that made
+674k can produce a margin call. Backtest with modest `InpMaxLevels` and a real
`InpMaxDrawdownPct`, and never run it live on money you cannot lose.
