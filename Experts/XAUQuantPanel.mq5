//+------------------------------------------------------------------+
//|                                              XAUQuantPanel.mq5    |
//|   DISPLAY-ONLY panel (like the XAU QUANT video). Draws the        |
//|   dashboard + BUY/SELL EXECUTED banner on the chart, reading the  |
//|   baskets opened by the Python runner (same magic). It NEVER      |
//|   trades — safe to run alongside the runner.                      |
//|                                                                    |
//|   Load on the SAME symbol + timeframe the runner uses (M5).       |
//+------------------------------------------------------------------+
#property copyright "thenoize23"
#property link      "https://github.com/thenoize23/XAUQuant"
#property version   "1.0"
#property strict

enum ENUM_REGIME { REGIME_RANGE=0, REGIME_TREND_UP=1, REGIME_TREND_DOWN=2 };

input group "=== Match the runner ==="
input long   InpMagic          = 990045;      // Magic of the runner's orders
input string InpSymbolOverride = "";          // Symbol ("" = chart symbol)
input string InpSignalMode     = "reversion"; // "reversion" (gold) | "trend" (BTC)

input group "=== Signal display params (match config.py) ==="
input int    InpADXPeriod      = 14;
input double InpADXTrendLevel  = 25.0;
input int    InpRSIPeriod      = 14;
input int    InpBBPeriod       = 20;
input double InpBBDeviations   = 2.0;
input int    InpMomPeriod      = 14;

input group "=== Panel / banner ==="
input bool   InpShowPanel      = true;
input bool   InpShowBanner     = true;
input int    InpBannerSeconds  = 6;
input string InpBuyMessage     = "BUY EXECUTED";
input string InpSellMessage    = "SELL EXECUTED";

string   g_symbol;
int      g_digits;
int      h_adx, h_rsi, h_bb, h_mom;

ENUM_REGIME g_regime = REGIME_RANGE;
int      g_buyConf=0, g_sellConf=0;
double   g_momValue=0;

int      g_prevLong=-1, g_prevShort=-1;   // previous level counts (event detection)
datetime g_bannerUntil=0;
string   g_bannerText="";
color    g_bannerClr=clrLime;
int      g_panelBottomY=220;

string GVName() { return "XAUQuantPanel_closed_"+g_symbol+"_"+(string)InpMagic; }

//==================================================================
int OnInit()
{
   g_symbol = (InpSymbolOverride=="" ? _Symbol : InpSymbolOverride);
   g_digits = (int)SymbolInfoInteger(g_symbol, SYMBOL_DIGITS);
   h_adx = iADX(g_symbol, PERIOD_CURRENT, InpADXPeriod);
   h_rsi = iRSI(g_symbol, PERIOD_CURRENT, InpRSIPeriod, PRICE_CLOSE);
   h_bb  = iBands(g_symbol, PERIOD_CURRENT, InpBBPeriod, 0, InpBBDeviations, PRICE_CLOSE);
   h_mom = iMomentum(g_symbol, PERIOD_CURRENT, InpMomPeriod, PRICE_CLOSE);
   if(h_adx==INVALID_HANDLE||h_rsi==INVALID_HANDLE||h_bb==INVALID_HANDLE||h_mom==INVALID_HANDLE)
      return(INIT_FAILED);
   if(!GlobalVariableCheck(GVName())) GlobalVariableSet(GVName(), 0);
   EventSetTimer(1);   // refresh even without ticks
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, "xqp_");
   IndicatorRelease(h_adx); IndicatorRelease(h_rsi);
   IndicatorRelease(h_bb);  IndicatorRelease(h_mom);
}

void OnTimer() { Refresh(); }
void OnTick()  { Refresh(); }

void Refresh()
{
   UpdateSignals();
   DetectEvents();
   if(InpShowPanel) DrawPanel();
   DrawBanner();
}

//==================================================================
double Buf(int handle, int buffer, int shift)
{
   double v[]; if(CopyBuffer(handle, buffer, shift, 1, v)!=1) return 0.0; return v[0];
}
double Clamp(double v,double lo,double hi){ return v<lo?lo:(v>hi?hi:v); }

void UpdateSignals()
{
   double adx=Buf(h_adx,0,1), diP=Buf(h_adx,1,1), diM=Buf(h_adx,2,1);
   double price=iClose(g_symbol,PERIOD_CURRENT,1);
   if(adx < InpADXTrendLevel) g_regime=REGIME_RANGE;
   else g_regime = (diP>=diM)? REGIME_TREND_UP : REGIME_TREND_DOWN;

   g_momValue = Buf(h_mom,0,1);
   double rsi=Buf(h_rsi,0,1), up=Buf(h_bb,1,1), lo=Buf(h_bb,2,1), mid=Buf(h_bb,0,1);
   double bbBuy = (mid>lo)? (mid-price)/(mid-lo) : 0.0;
   double bbSell= (up>mid)? (price-mid)/(up-mid) : 0.0;
   bbBuy=Clamp(bbBuy,0,1.5); bbSell=Clamp(bbSell,0,1.5);
   double rBuy=Clamp((50-rsi)/30,0,1), rSell=Clamp((rsi-50)/30,0,1);
   if(InpSignalMode=="trend"){ double t; t=bbBuy;bbBuy=bbSell;bbSell=t; t=rBuy;rBuy=rSell;rSell=t; }
   double buy =0.6*Clamp(bbBuy,0,1)+0.4*rBuy;
   double sell=0.6*Clamp(bbSell,0,1)+0.4*rSell;
   if(g_regime==REGIME_TREND_UP){ buy*=1.15; sell*=0.60; }
   if(g_regime==REGIME_TREND_DOWN){ sell*=1.15; buy*=0.60; }
   g_buyConf =(int)MathRound(Clamp(buy,0,1)*100);
   g_sellConf=(int)MathRound(Clamp(sell,0,1)*100);
}

void BasketStats(ENUM_POSITION_TYPE type,int &levels,double &vol,double &avg,double &pl)
{
   levels=0; vol=0; avg=0; pl=0; double w=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=g_symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=type) continue;
      double v=PositionGetDouble(POSITION_VOLUME), p=PositionGetDouble(POSITION_PRICE_OPEN);
      levels++; vol+=v; w+=v*p;
      pl+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
   }
   if(vol>0) avg=w/vol;
}

//  Detect new orders (banner) and basket closes (counter)
void DetectEvents()
{
   int Lv,Sv; double a,b,c;
   BasketStats(POSITION_TYPE_BUY, Lv,a,b,c);
   BasketStats(POSITION_TYPE_SELL,Sv,a,b,c);
   if(g_prevLong>=0)
   {
      if(Lv>g_prevLong) FireBanner(true);
      if(Sv>g_prevShort) FireBanner(false);
      if(Lv==0 && g_prevLong>0) GlobalVariableSet(GVName(),GlobalVariableGet(GVName())+1);
      if(Sv==0 && g_prevShort>0) GlobalVariableSet(GVName(),GlobalVariableGet(GVName())+1);
   }
   g_prevLong=Lv; g_prevShort=Sv;
}

void FireBanner(bool isBuy)
{
   if(!InpShowBanner) return;
   g_bannerText = isBuy? InpBuyMessage : InpSellMessage;
   g_bannerClr  = isBuy? clrLime : clrTomato;
   g_bannerUntil= (InpBannerSeconds>0)? TimeCurrent()+InpBannerSeconds : D'2099.01.01';
}

//==================================================================
void Lbl(string name,int x,int y,string text,color clr,int size=9,string font="Consolas")
{
   string o="xqp_"+name;
   if(ObjectFind(0,o)<0){
      ObjectCreate(0,o,OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,o,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,o,OBJPROP_ANCHOR,ANCHOR_LEFT_UPPER);
      ObjectSetInteger(0,o,OBJPROP_SELECTABLE,false);
      ObjectSetInteger(0,o,OBJPROP_HIDDEN,true);
   }
   ObjectSetInteger(0,o,OBJPROP_XDISTANCE,x); ObjectSetInteger(0,o,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,o,OBJPROP_COLOR,clr); ObjectSetInteger(0,o,OBJPROP_FONTSIZE,size);
   ObjectSetString(0,o,OBJPROP_FONT,font); ObjectSetString(0,o,OBJPROP_TEXT,text);
}

void DrawPanel()
{
   int x=12,y=20,dy=16;
   Lbl("title",x,y,"XAU QUANT | "+g_symbol,clrGold,11); y+=dy+4;
   string reg=(g_regime==REGIME_RANGE)?"RANGE":(g_regime==REGIME_TREND_UP?"TREND UP":"TREND DOWN");
   color rc=(g_regime==REGIME_RANGE)?clrSilver:(g_regime==REGIME_TREND_UP?clrLime:clrTomato);
   Lbl("regime",x,y,"REGIME: "+reg,rc,10); y+=dy;
   Lbl("conf",x,y,StringFormat("BUY CONF %d    SELL CONF %d",g_buyConf,g_sellConf),clrWhite,10); y+=dy+2;

   int Lv;double Lvol,Lavg,Lpl; BasketStats(POSITION_TYPE_BUY,Lv,Lvol,Lavg,Lpl);
   Lbl("long",x,y,"LONG BASKET",clrLime,10); y+=dy;
   if(Lv>0) Lbl("longd",x,y,StringFormat("Lv %d  Avg %.*f  Vol %.2f  P/L %.2f",Lv,g_digits,Lavg,Lvol,Lpl),(Lpl>=0?clrLime:clrTomato),9);
   else     Lbl("longd",x,y,"no basket open",clrGray,9);
   y+=dy+2;

   int Sv;double Svol,Savg,Spl; BasketStats(POSITION_TYPE_SELL,Sv,Svol,Savg,Spl);
   Lbl("short",x,y,"SHORT BASKET",clrTomato,10); y+=dy;
   if(Sv>0) Lbl("shortd",x,y,StringFormat("Lv %d  Avg %.*f  Vol %.2f  P/L %.2f",Sv,g_digits,Savg,Svol,Spl),(Spl>=0?clrLime:clrTomato),9);
   else     Lbl("shortd",x,y,"no basket open",clrGray,9);
   y+=dy+2;

   Lbl("mom",x,y,StringFormat("MOMENTUM %.2f",g_momValue),clrAqua,9); y+=dy+2;
   Lbl("acct",x,y,StringFormat("Balance %.2f   Equity %.2f",
       AccountInfoDouble(ACCOUNT_BALANCE),AccountInfoDouble(ACCOUNT_EQUITY)),clrWhite,9); y+=dy;
   Lbl("closed",x,y,StringFormat("Closed baskets: %d",(int)GlobalVariableGet(GVName())),clrWhite,9);
   y+=dy+4; g_panelBottomY=y;
}

void DrawBanner()
{
   string bg="xqp_banner_bg";
   if(!InpShowBanner || g_bannerUntil==0 || TimeCurrent()>g_bannerUntil){
      ObjectDelete(0,bg); ObjectDelete(0,"xqp_banner_tx");
      if(TimeCurrent()>g_bannerUntil) g_bannerUntil=0;
      return;
   }
   int x=12,y=g_panelBottomY,w=250,h=22;
   if(ObjectFind(0,bg)<0){
      ObjectCreate(0,bg,OBJ_RECTANGLE_LABEL,0,0,0);
      ObjectSetInteger(0,bg,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,bg,OBJPROP_BORDER_TYPE,BORDER_FLAT);
      ObjectSetInteger(0,bg,OBJPROP_BACK,false);
      ObjectSetInteger(0,bg,OBJPROP_SELECTABLE,false);
      ObjectSetInteger(0,bg,OBJPROP_HIDDEN,true);
   }
   ObjectSetInteger(0,bg,OBJPROP_XDISTANCE,x); ObjectSetInteger(0,bg,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,bg,OBJPROP_XSIZE,w); ObjectSetInteger(0,bg,OBJPROP_YSIZE,h);
   ObjectSetInteger(0,bg,OBJPROP_BGCOLOR,g_bannerClr); ObjectSetInteger(0,bg,OBJPROP_COLOR,g_bannerClr);
   Lbl("banner_tx",x+10,y+4,g_bannerText,clrBlack,10,"Arial Bold");
}
//+------------------------------------------------------------------+
