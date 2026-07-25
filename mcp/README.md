# XAUQuant MCP server

Runs the XAUQuant grid/martingale strategy as an **MCP server** that talks to a
running **MetaTrader 5** terminal through the `MetaTrader5` Python package — so it
reads live signals and (optionally) executes **without any chart-attached EA**.

Use this when your broker blocks EAs on the chart but still allows the terminal to
trade (algorithmic/manual trading permitted).

> ⚠️ Same risk warning as the EA: this is a **martingale grid** and can blow up an
> account. Execution is **OFF by default** (`auto_trade=false`); nothing is sent live
> until you explicitly enable it. Confirm your broker's Terms allow programmatic
> trading — even without an EA, this is still algorithmic trading. Demo first.

## How it works

```
Claude (MCP client)  ──tools──►  server.py  ──►  strategy.py  (regime + confidence + basket plan)
                                     │
                                     └──►  mt5_client.py  ──►  MetaTrader5 terminal (prices + orders)
```

The strategy is a faithful Python port of `Experts/XAUQuant.mq5` (same regime,
confidence, grid and guardrail logic).

## Tools exposed

| Tool | What it does |
|---|---|
| `status` | Connect + account/config summary (call first). |
| `market_snapshot` | Live bid/ask/spread + ADX, RSI, Bollinger, ATR, momentum. |
| `compute_current_signal` | Regime + BUY/SELL confidence (0–100). |
| `basket_state` | Current LONG/SHORT baskets: levels, avg, volume, P/L. |
| `plan_next_action` | What the strategy would do now (OPEN/ADD/CLOSE/HOLD) — no execution. |
| `execute_plan` | Execute the plan (`confirm=True` needed for new orders). |
| `place_order` | Manual single BUY/SELL market order. |
| `close_basket` / `emergency_close_all` | Close one/both baskets. |
| `set_auto_trade` | Toggle live execution for the session. |

Closes (including the drawdown guardrail) run even without `confirm`; **opening**
new orders needs both `auto_trade=true` and `confirm=true`.

## Setup

1. Install a **MetaTrader 5** desktop terminal, log into your TíoMarkets account,
   and enable **Tools → Options → Expert Advisors → Allow algorithmic trading**.
2. Install deps (Windows, same Python that can import `MetaTrader5`):
   ```powershell
   cd C:\Users\conoi\XAUQuant\mcp
   pip install -r requirements.txt
   ```
3. Smoke-test the pure logic (no terminal needed):
   ```powershell
   python test_strategy.py
   ```

## Register with Claude Desktop / Claude Code

Add to your MCP client config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "xauquant": {
      "command": "python",
      "args": ["C:\\Users\\conoi\\XAUQuant\\mcp\\server.py"],
      "env": {
        "XQ_SYMBOL": "XAUUSD",
        "XQ_MAX_LEVELS": "6",
        "XQ_AUTO_TRADE": "false"
      }
    }
  }
}
```

Any `Config` field can be overridden with an `XQ_`-prefixed env var
(`XQ_LOT_MULTIPLIER`, `XQ_TARGET_MONEY`, `XQ_MAX_DRAWDOWN_PCT`, ...).

## Typical flow in Claude

1. `status` → confirm connection + `trade_allowed`.
2. `plan_next_action` → see the recommendation (safe, read-only).
3. When happy: `set_auto_trade(true)` then `execute_plan(confirm=true)`.
4. Panic: `emergency_close_all`.

Start with `auto_trade=false` and drive it manually until you trust the signals.
