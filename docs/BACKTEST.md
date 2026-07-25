# Backtest results & honest interpretation

The MQL5 EA and the Python MCP **share the same strategy logic**, so this one
Python backtest (`mcp/backtest.py`) represents both. Running the MT5 Strategy
Tester on the EA is still worthwhile — matching numbers confirms the port.

## Method

- Bar-based simulation over XAUUSD/gold OHLC.
- Reuses the live signal engine (`strategy.compute_signal`) and the same config
  thresholds. Martingale basket simulated **intrabar**: grid adds on the bar's
  adverse extreme, basket take-profit on the favourable extreme.
- Models spread (20 pts), leverage 1:100, a broker **stop-out at 50% of used
  margin** (blow-up), and — matching the EA's `InpHaltAfterStop` — **halts
  trading after the drawdown guardrail fires** (`HALT_AFTER_STOP` in backtest.py).
- Symbol/point/contract taken from the real broker: `XAUUSDun`, digits 2,
  point 0.01, contract 100.

## Headline: real TíoMarkets `XAUUSDun` data

Pulled straight from the live terminal with `fetch_mt5_history.py`. The terminal
caps history at 100k bars/timeframe, so higher timeframes reach further back.

**Guardrail ON (default 25% emergency stop):**

| TF | Period | Return | Max DD | Baskets | Win% | Outcome |
|---|---|---|---|---|---|---|
| M1  | Apr–Jul 2026 (3.3 mo) | +233% | 30% | 330 | 99.7% | guard fired → **halted** 2026-05-11 |
| M5  | Mar 2025–Jul 2026 (1.4 y) | +94% | 35% | 231 | 99.6% | guard fired → **halted** 2025-05-05 |
| M15 | May 2022–Jul 2026 (4.2 y) | +2642% | 12% | 2044 | 100% | never halted |

**Guardrail OFF (does it really blow up?):**

| TF | Return | Max DD | Outcome |
|---|---|---|---|
| M1 | +1820% | 52% | survived (barely) |
| M5 | +39% | 53% | **BLEW UP — margin call** |

## Two findings that matter

**1. On real data it does blow up.** The M5 set (1.4 real years) took a **margin
call** with no guardrail. With the guardrail it doesn't blow up, but it **trips the
emergency stop** (halted May-2025 and May-2026) — i.e. it books a ~25–35% loss and
switches itself off (needs a manual restart). That is the shock scenario the short
Yahoo sample never contained.

**2. The M15 "+2642%, 100% win" is a resolution artifact — distrust it.** The same
kind of period shows **12% drawdown on M15 but 52% on M5**. Martingale drawdown
happens *inside* the bar; 15-minute bars hide it. The finer the timeframe, the more
realistic (and uglier) the picture — so **M1 is the trustworthy row, not M15.**

## Verdict

On the broker's own gold data the strategy makes money in good stretches
(+94% to +233% before stopping), but within **1.4 real years it hit a margin call
unprotected, and tripped its emergency stop twice when protected.** Real drawdowns
run **30–52%**. It is a "win a lot until one shock takes half or all of the account"
machine — now confirmed on real gold, not just synthetic.

## Earlier Yahoo sample (superseded, kept for reference)

Gold futures `GC=F` 1m/2m/5m, 7–60 days: +411% to +452%, 100% win, no blow-up.
That window was simply too short and too kind to contain a shock — which is exactly
why the real multi-year `XAUUSDun` pull above matters.

## Anti-shock experiments (honest: no free lunch)

The martingale's only failure mode is a sustained adverse shock. We tested a
per-basket protection layer (`shock_guard`: % stop-loss, ATR-distance stop,
freeze-adds on a >N×ATR "shock candle", post-stop cooldown) on real `XAUUSDun`.

| Config | M5 (1.4y, *has* a shock) | M1 (3.3mo, *calm*) |
|---|---|---|
| No protection | +39%, DD 53%, **BLEW UP** | +1820%, DD 52%, survived |
| Anti-shock (5% stop, 8 levels, cooldown) | **+441%, DD 32%, survived** | **−98%, DD 99%** |

The same protection that saves the shock period **wrecks the calm period**: a
loss-based stop converts would-be-winners into realised losers, which bleeds a
martingale dry when there is no shock. Volatility-candle *freeze-only* didn't
reliably prevent the blow-up either. **A blunt stop can't tell "normal grid
drawdown that reverts" from "a real shock that doesn't."**

Conclusion: chasing stop parameters is a dead end. A principled anti-shock must
target the *cause* of shocks, which for gold are mostly **scheduled**:
- an **economic-calendar / time filter** (pause entries + freeze the grid ±30 min
  around NFP / CPI / FOMC) — regime-neutral, fires only on real risk;
- **weekend-gap protection** (cut/reduce baskets before Friday close).

The `shock_guard` config knobs remain available for experimentation.

## Confirm the port with the MT5 Strategy Tester

1. MetaTrader 5 → **View → Strategy Tester** (Ctrl+R).
2. Expert `XAUQuant`, Symbol `XAUUSDun`, Period `M1`, Model **Every tick based on real ticks**.
3. Match inputs to the backtest (`InpMaxLevels=15`, `InpLotMultiplier=1.5`,
   `InpTargetMoney=50`, `InpMaxDrawdownPct=25`).
4. Close net-profit / max-drawdown / trade-count = MQL5 EA and Python MCP are equivalent.
