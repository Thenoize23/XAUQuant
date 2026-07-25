//+------------------------------------------------------------------+
//|                                                    XAUQuant.mq5   |
//|         Grid / martingale basket EA for XAUUSD (M1)              |
//|         Reverse-engineered feature set (regime + confidence +    |
//|         basket management + on-chart dashboard) with safety      |
//|         guardrails. Educational use only. NOT financial advice.  |
//|                                                                  |
//|         Repo: github.com/thenoize23/XAUQuant                     |
//+------------------------------------------------------------------+
#property copyright "thenoize23"
#property link      "https://github.com/thenoize23/XAUQuant"
#property version   "0.1"
#property strict

#include <Trade/Trade.mqh>

//==================================================================
//  Enums
//==================================================================
enum ENUM_REGIME     { REGIME_RANGE=0, REGIME_TREND_UP=1, REGIME_TREND_DOWN=2 };
enum ENUM_STEP_MODE  { STEP_FIXED=0, STEP_ATR=1 };
enum ENUM_TARGET_MODE{ TARGET_MONEY=0, TARGET_POINTS=1 };
enum ENUM_LOT_MODE   { LOT_FIXED=0, LOT_MULTIPLIER=1 };

//==================================================================
//  Inputs
//==================================================================
input group "=== General ==="
input long            InpMagic          = 990045;      // Magic number
input string          InpSymbolOverride = "";          // Symbol ("" = current chart)
input int             InpSlippagePoints = 30;          // Max slippage (points)
input bool            InpShowPanel      = true;        // Show dashboard panel

input group "=== Direction / Regime ==="
input bool            InpAllowLong      = true;        // Allow long baskets
input bool            InpAllowShort     = true;        // Allow short baskets
input int             InpADXPeriod      = 14;          // ADX period (regime)
input double          InpADXTrendLevel  = 25.0;        // ADX >= this => trending
input int             InpMAPeriod       = 50;          // MA period (trend bias)

input group "=== Confidence signal ==="
input int             InpRSIPeriod      = 14;          // RSI period
input int             InpBBPeriod       = 20;          // Bollinger period (mean reversion)
input double          InpBBDeviations   = 2.0;         // Bollinger deviations
input int             InpConfThreshold  = 60;          // Min confidence (0-100) to open a basket
input int             InpMomPeriod      = 14;          // Momentum period (panel + filter)

input group "=== Basket / grid (martingale) ==="
input ENUM_LOT_MODE   InpLotMode        = LOT_MULTIPLIER; // Lot scaling mode
input double          InpBaseLot        = 0.01;        // First level lot size
input double          InpLotMultiplier  = 1.5;         // Lot multiplier per level (LOT_MULTIPLIER)
input double          InpMaxLotPerOrder = 5.0;         // Hard cap per single order (lots)
input ENUM_STEP_MODE  InpStepMode       = STEP_ATR;    // Grid spacing mode
input int             InpGridStepPoints = 400;         // Grid step (points) if STEP_FIXED
input int             InpATRPeriod      = 14;          // ATR period (STEP_ATR)
input double          InpATRStepMult    = 1.0;         // Grid step = ATR * this (STEP_ATR)
input int             InpMaxLevels      = 15;          // GUARDRAIL: max grid levels per basket

input group "=== Basket exit ==="
input ENUM_TARGET_MODE InpTargetMode    = TARGET_MONEY;// Basket take-profit mode
input double          InpTargetMoney    = 50.0;        // Close basket at +this account currency
input int             InpTargetPoints   = 250;         // Close basket at +this points from avg

input group "=== Guardrails (safety) ==="
input double          InpMaxDrawdownPct = 25.0;        // Emergency: close ALL if equity DD% from peak >= this
input int             InpMaxSpreadPoints= 60;          // Skip new entries if spread > this
input bool            InpHaltAfterStop  = true;        // Stop trading after an emergency close

//==================================================================
//  Globals
//==================================================================
CTrade         trade;
string         g_symbol;
int            g_digits;
double         g_point;

int            h_adx, h_rsi, h_bb, h_ma, h_atr, h_mom;

datetime       g_lastBarTime = 0;
double         g_peakEquity  = 0.0;
bool           g_halted      = false;

// panel-cached values
ENUM_REGIME    g_regime      = REGIME_RANGE;
int            g_buyConf     = 0;
int            g_sellConf    = 0;
double         g_momValue    = 0.0;

// persistent closed-baskets counter key
string GVName() { return "XAUQuant_closed_" + g_symbol + "_" + (string)InpMagic; }

//==================================================================
//  Init / Deinit
//==================================================================
int OnInit()
{
   g_symbol = (InpSymbolOverride=="" ? _Symbol : InpSymbolOverride);
   g_digits = (int)SymbolInfoInteger(g_symbol, SYMBOL_DIGITS);
   g_point  = SymbolInfoDouble(g_symbol, SYMBOL_POINT);

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(g_symbol);

   h_adx = iADX(g_symbol, PERIOD_CURRENT, InpADXPeriod);
   h_rsi = iRSI(g_symbol, PERIOD_CURRENT, InpRSIPeriod, PRICE_CLOSE);
   h_bb  = iBands(g_symbol, PERIOD_CURRENT, InpBBPeriod, 0, InpBBDeviations, PRICE_CLOSE);
   h_ma  = iMA(g_symbol, PERIOD_CURRENT, InpMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   h_atr = iATR(g_symbol, PERIOD_CURRENT, InpATRPeriod);
   h_mom = iMomentum(g_symbol, PERIOD_CURRENT, InpMomPeriod, PRICE_CLOSE);

   if(h_adx==INVALID_HANDLE || h_rsi==INVALID_HANDLE || h_bb==INVALID_HANDLE ||
      h_ma==INVALID_HANDLE  || h_atr==INVALID_HANDLE || h_mom==INVALID_HANDLE)
   {
      Print("XAUQuant: failed to create indicator handles");
      return(INIT_FAILED);
   }

   g_peakEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(!GlobalVariableCheck(GVName()))
      GlobalVariableSet(GVName(), 0);

   Print("XAUQuant initialised on ", g_symbol, "  magic=", InpMagic);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, "xq_");
   IndicatorRelease(h_adx); IndicatorRelease(h_rsi); IndicatorRelease(h_bb);
   IndicatorRelease(h_ma);  IndicatorRelease(h_atr); IndicatorRelease(h_mom);
}

//==================================================================
//  Main
//==================================================================
void OnTick()
{
   // Manage open baskets every tick (exits are time critical)
   ManageBasket(POSITION_TYPE_BUY);
   ManageBasket(POSITION_TYPE_SELL);

   // Guardrail: equity drawdown emergency stop
   CheckDrawdownGuard();

   // Signals & new entries only once per bar
   if(IsNewBar())
   {
      UpdateSignals();
      if(!g_halted)
      {
         TryEntry(POSITION_TYPE_BUY);
         TryEntry(POSITION_TYPE_SELL);
         TryGridAdd(POSITION_TYPE_BUY);
         TryGridAdd(POSITION_TYPE_SELL);
      }
   }

   if(InpShowPanel)
      DrawPanel();
}

//==================================================================
//  New bar detection
//==================================================================
bool IsNewBar()
{
   datetime t = iTime(g_symbol, PERIOD_CURRENT, 0);
   if(t != g_lastBarTime)
   {
      g_lastBarTime = t;
      return true;
   }
   return false;
}

//==================================================================
//  Indicator read helpers
//==================================================================
double Buf(int handle, int buffer, int shift)
{
   double v[];
   if(CopyBuffer(handle, buffer, shift, 1, v) != 1) return 0.0;
   return v[0];
}

//==================================================================
//  Signals: regime, confidence, momentum
//==================================================================
void UpdateSignals()
{
   double adx    = Buf(h_adx, 0, 1);   // MAIN line
   double diPlus = Buf(h_adx, 1, 1);   // +DI
   double diMinus= Buf(h_adx, 2, 1);   // -DI
   double ma     = Buf(h_ma, 0, 1);
   double price  = iClose(g_symbol, PERIOD_CURRENT, 1);

   // --- Regime ---
   if(adx < InpADXTrendLevel)
      g_regime = REGIME_RANGE;
   else
      g_regime = (diPlus >= diMinus) ? REGIME_TREND_UP : REGIME_TREND_DOWN;

   // --- Momentum (100 = flat) ---
   g_momValue = Buf(h_mom, 0, 1);

   // --- Confidence (0-100) ---
   double rsi   = Buf(h_rsi, 0, 1);
   double upper = Buf(h_bb, 1, 1);   // upper band
   double lower = Buf(h_bb, 2, 1);   // lower band
   double mid   = Buf(h_bb, 0, 1);   // basis

   // Mean-reversion core: buy strength grows as price sinks toward/below lower band
   // and RSI is oversold; sell strength mirrors it near the upper band.
   double bbBuy  = (mid>lower) ? (mid - price) / (mid - lower) : 0.0; // >0 below mid
   double bbSell = (upper>mid) ? (price - mid) / (upper - mid) : 0.0; // >0 above mid
   bbBuy  = Clamp(bbBuy,  0.0, 1.5);
   bbSell = Clamp(bbSell, 0.0, 1.5);

   double rsiBuy  = Clamp((50.0 - rsi) / 30.0, 0.0, 1.0); // oversold -> 1
   double rsiSell = Clamp((rsi - 50.0) / 30.0, 0.0, 1.0); // overbought -> 1

   double buyRaw  = 0.6*Clamp(bbBuy,0,1)  + 0.4*rsiBuy;
   double sellRaw = 0.6*Clamp(bbSell,0,1) + 0.4*rsiSell;

   // Regime bias: allow trend continuation, damp counter-trend
   if(g_regime==REGIME_TREND_UP)   { buyRaw  *= 1.15; sellRaw *= 0.60; }
   if(g_regime==REGIME_TREND_DOWN) { sellRaw *= 1.15; buyRaw  *= 0.60; }

   g_buyConf  = (int)MathRound(Clamp(buyRaw, 0.0, 1.0) * 100.0);
   g_sellConf = (int)MathRound(Clamp(sellRaw,0.0, 1.0) * 100.0);
}

double Clamp(double v, double lo, double hi)
{
   if(v<lo) return lo;
   if(v>hi) return hi;
   return v;
}

//==================================================================
//  Basket statistics (scan open positions of a direction)
//==================================================================
void BasketStats(ENUM_POSITION_TYPE type, int &levels, double &vol,
                 double &avgPrice, double &pl, double &lastPrice)
{
   levels=0; vol=0; avgPrice=0; pl=0; lastPrice=0;
   double weighted=0;
   double extreme = (type==POSITION_TYPE_BUY) ? DBL_MAX : 0.0;

   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)  continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != type) continue;

      double v = PositionGetDouble(POSITION_VOLUME);
      double p = PositionGetDouble(POSITION_PRICE_OPEN);
      levels++;
      vol      += v;
      weighted += v*p;
      pl       += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);

      // last level = the worst price so far (deepest into drawdown)
      if(type==POSITION_TYPE_BUY)  { if(p<extreme) extreme=p; }
      else                         { if(p>extreme) extreme=p; }
   }
   if(vol>0) avgPrice = weighted/vol;
   lastPrice = (levels>0) ? extreme : 0.0;
}

//==================================================================
//  Entry: open the first level of a basket
//==================================================================
void TryEntry(ENUM_POSITION_TYPE type)
{
   if(type==POSITION_TYPE_BUY  && !InpAllowLong)  return;
   if(type==POSITION_TYPE_SELL && !InpAllowShort) return;

   int levels; double vol, avg, pl, last;
   BasketStats(type, levels, vol, avg, pl, last);
   if(levels>0) return; // basket already open

   if(SpreadPoints() > InpMaxSpreadPoints) return;

   int conf = (type==POSITION_TYPE_BUY) ? g_buyConf : g_sellConf;
   if(conf < InpConfThreshold) return;

   // Regime gate
   if(type==POSITION_TYPE_BUY  && g_regime==REGIME_TREND_DOWN) return;
   if(type==POSITION_TYPE_SELL && g_regime==REGIME_TREND_UP)   return;

   double lot = NormalizeLot(InpBaseLot);
   OpenLevel(type, lot, "xq-L0");
}

//==================================================================
//  Grid add: add a level when price moves against the basket
//==================================================================
void TryGridAdd(ENUM_POSITION_TYPE type)
{
   if(type==POSITION_TYPE_BUY  && !InpAllowLong)  return;
   if(type==POSITION_TYPE_SELL && !InpAllowShort) return;

   int levels; double vol, avg, pl, last;
   BasketStats(type, levels, vol, avg, pl, last);
   if(levels==0) return;               // no basket to extend
   if(levels>=InpMaxLevels) return;    // GUARDRAIL

   double step = GridStep();
   if(step<=0) return;

   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);

   bool addLong  = (type==POSITION_TYPE_BUY  && ask <= last - step);
   bool addShort = (type==POSITION_TYPE_SELL && bid >= last + step);
   if(!(addLong || addShort)) return;

   double lot = NextLevelLot(InpBaseLot, levels);
   OpenLevel(type, lot, "xq-L"+(string)levels);
}

//==================================================================
//  Basket management: close whole basket when target reached
//==================================================================
void ManageBasket(ENUM_POSITION_TYPE type)
{
   int levels; double vol, avg, pl, last;
   BasketStats(type, levels, vol, avg, pl, last);
   if(levels==0) return;

   bool hit=false;
   if(InpTargetMode==TARGET_MONEY)
   {
      if(pl >= InpTargetMoney) hit=true;
   }
   else // TARGET_POINTS from average
   {
      double price = (type==POSITION_TYPE_BUY)
                     ? SymbolInfoDouble(g_symbol, SYMBOL_BID)
                     : SymbolInfoDouble(g_symbol, SYMBOL_ASK);
      double pts = (type==POSITION_TYPE_BUY)
                   ? (price - avg)/g_point
                   : (avg - price)/g_point;
      if(pts >= InpTargetPoints) hit=true;
   }

   if(hit)
   {
      CloseBasket(type);
      GlobalVariableSet(GVName(), GlobalVariableGet(GVName()) + 1);
   }
}

//==================================================================
//  Guardrail: emergency drawdown stop
//==================================================================
void CheckDrawdownGuard()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(eq > g_peakEquity) g_peakEquity = eq;
   if(g_peakEquity<=0) return;

   double ddPct = (g_peakEquity - eq) / g_peakEquity * 100.0;
   if(ddPct >= InpMaxDrawdownPct && !g_halted)
   {
      CloseBasket(POSITION_TYPE_BUY);
      CloseBasket(POSITION_TYPE_SELL);
      Print("XAUQuant: EMERGENCY drawdown guard hit (", DoubleToString(ddPct,1),
            "%). All positions closed.");
      if(InpHaltAfterStop) g_halted = true;
   }
}

//==================================================================
//  Order helpers
//==================================================================
void OpenLevel(ENUM_POSITION_TYPE type, double lot, string tag)
{
   lot = NormalizeLot(lot);
   if(lot<=0) return;
   bool ok = (type==POSITION_TYPE_BUY)
             ? trade.Buy(lot, g_symbol, 0, 0, 0, tag)
             : trade.Sell(lot, g_symbol, 0, 0, 0, tag);
   if(!ok)
      Print("XAUQuant: order failed ", tag, " ret=", trade.ResultRetcode(),
            " ", trade.ResultRetcodeDescription());
}

void CloseBasket(ENUM_POSITION_TYPE type)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)  continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != type) continue;
      trade.PositionClose(ticket);
   }
}

double NextLevelLot(double baseLot, int level)
{
   double lot = baseLot;
   if(InpLotMode==LOT_MULTIPLIER)
      lot = baseLot * MathPow(InpLotMultiplier, level);
   return NormalizeLot(lot);
}

double NormalizeLot(double lot)
{
   double minLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_STEP);

   if(lot > InpMaxLotPerOrder) lot = InpMaxLotPerOrder;
   if(step>0) lot = MathFloor(lot/step)*step;
   if(lot < minLot) lot = minLot;
   if(lot > maxLot) lot = maxLot;
   return lot;
}

double GridStep()
{
   if(InpStepMode==STEP_FIXED)
      return InpGridStepPoints * g_point;
   double atr = Buf(h_atr, 0, 1);
   return atr * InpATRStepMult;
}

double SpreadPoints()
{
   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   return (ask-bid)/g_point;
}

//==================================================================
//  Dashboard panel (mimics the "XAU QUANT" screen)
//==================================================================
void Lbl(string name, int x, int y, string text, color clr, int size=9, string font="Consolas")
{
   string obj = "xq_"+name;
   if(ObjectFind(0, obj) < 0)
   {
      ObjectCreate(0, obj, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, obj, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, obj, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
      ObjectSetInteger(0, obj, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, obj, OBJPROP_HIDDEN, true);
   }
   ObjectSetInteger(0, obj, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, obj, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, obj, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, obj, OBJPROP_FONTSIZE, size);
   ObjectSetString (0, obj, OBJPROP_FONT, font);
   ObjectSetString (0, obj, OBJPROP_TEXT, text);
}

void DrawPanel()
{
   int x=12, y=20, dy=16;

   Lbl("title", x, y, "XAU QUANT | "+g_symbol, clrGold, 11); y+=dy+4;

   string reg = (g_regime==REGIME_RANGE) ? "RANGE" :
                (g_regime==REGIME_TREND_UP ? "TREND UP" : "TREND DOWN");
   color  regClr = (g_regime==REGIME_RANGE)? clrSilver :
                   (g_regime==REGIME_TREND_UP? clrLime : clrTomato);
   Lbl("regime", x, y, "REGIME: "+reg, regClr, 10); y+=dy;

   Lbl("conf", x, y, StringFormat("BUY CONF %d    SELL CONF %d", g_buyConf, g_sellConf),
       clrWhite, 10); y+=dy+2;

   int Lv; double Lvol,Lavg,Lpl,Llast; BasketStats(POSITION_TYPE_BUY, Lv,Lvol,Lavg,Lpl,Llast);
   Lbl("long", x, y, "LONG BASKET", clrLime, 10); y+=dy;
   if(Lv>0)
      Lbl("longd", x, y, StringFormat("Lv %d  Avg %.3f  Vol %.2f  P/L %.2f", Lv,Lavg,Lvol,Lpl),
          (Lpl>=0?clrLime:clrTomato), 9);
   else
      Lbl("longd", x, y, "no basket open", clrGray, 9);
   y+=dy+2;

   int Sv; double Svol,Savg,Spl,Slast; BasketStats(POSITION_TYPE_SELL, Sv,Svol,Savg,Spl,Slast);
   Lbl("short", x, y, "SHORT BASKET", clrTomato, 10); y+=dy;
   if(Sv>0)
      Lbl("shortd", x, y, StringFormat("Lv %d  Avg %.3f  Vol %.2f  P/L %.2f", Sv,Savg,Svol,Spl),
          (Spl>=0?clrLime:clrTomato), 9);
   else
      Lbl("shortd", x, y, "no basket open", clrGray, 9);
   y+=dy+2;

   Lbl("mom", x, y, StringFormat("MOMENTUM %.2f", g_momValue), clrAqua, 9); y+=dy+2;

   Lbl("acct", x, y, StringFormat("Balance %.2f   Equity %.2f",
       AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY)), clrWhite, 9); y+=dy;
   Lbl("closed", x, y, StringFormat("Closed baskets: %d%s",
       (int)GlobalVariableGet(GVName()), (g_halted?"   [HALTED]":"")),
       (g_halted?clrOrange:clrWhite), 9);
}
//+------------------------------------------------------------------+
