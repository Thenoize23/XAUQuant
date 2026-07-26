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

#define MOMN 15
double   g_mval[MOMN];        // per-bar momentum VALUES (fixed once sampled -> bars only scroll)
double   g_lastBid=0;
double   g_scale=0;           // slow-adapting scale so bars fill nicely without jumping

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
   PushTick();
   UpdateSignals();
   DetectEvents();
   if(InpShowPanel) DrawPanel();
   DrawBanner();
}

//  Each tick: push ONE fixed momentum value (price change) and scroll the rest.
//  Past bars keep their value -> they only shift left, they don't resize.
void PushTick()
{
   double bid=SymbolInfoDouble(g_symbol,SYMBOL_BID);
   if(bid<=0) return;
   if(g_lastBid==0){ g_lastBid=bid; return; }
   double delta=bid-g_lastBid;
   g_lastBid=bid;
   for(int i=0;i<MOMN-1;i++) g_mval[i]=g_mval[i+1];
   g_mval[MOMN-1]=delta;
   if(MathAbs(delta)>g_scale) g_scale=MathAbs(delta);   // scale = biggest move -> no over-zoom
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

void Box(string name,int x,int y,int w,int h,color bg,color border)
{
   string o="xqp_"+name;
   if(ObjectFind(0,o)<0){
      ObjectCreate(0,o,OBJ_RECTANGLE_LABEL,0,0,0);
      ObjectSetInteger(0,o,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,o,OBJPROP_BACK,false);
      ObjectSetInteger(0,o,OBJPROP_SELECTABLE,false);
      ObjectSetInteger(0,o,OBJPROP_HIDDEN,true);
      ObjectSetInteger(0,o,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   }
   ObjectSetInteger(0,o,OBJPROP_XDISTANCE,x); ObjectSetInteger(0,o,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,o,OBJPROP_XSIZE,MathMax(w,1)); ObjectSetInteger(0,o,OBJPROP_YSIZE,MathMax(h,1));
   ObjectSetInteger(0,o,OBJPROP_BGCOLOR,bg); ObjectSetInteger(0,o,OBJPROP_COLOR,border);
}

void DrawMomentum(int x,int y,int w,int h)
{
   Box("momcard",x,y,w,h,(color)C'30,32,38',(color)C'55,58,66');   // gray card
   // scale = max of the VISIBLE bars -> always zoomed to fill (no old spike flattening it)
   double scale=SymbolInfoDouble(g_symbol,SYMBOL_POINT);
   for(int i=0;i<MOMN;i++) scale=MathMax(scale,MathAbs(g_mval[i]));
   int mid=y+h/2, cap=h/2;
   for(int i=0;i<MOMN;i++){
      double v=g_mval[i];                             // fixed value for this bar
      int bh=(int)(MathAbs(v)/scale*(h/2)*1.7);       // zoomed to fill; tallest clips
      if(bh>cap) bh=cap; if(bh<1) bh=1;               // clip at the card edge
      color c=v>=0?clrLime:clrOrange;
      int bx =x+(i*w)/MOMN;                            // even distribution -> consistent width
      int bxn=x+((i+1)*w)/MOMN;
      int by =v>=0? mid-bh : mid;
      Box("mom"+(string)i, bx, by, MathMax(bxn-bx-2,1), bh, c, c);
   }
}

void DrawPanel()
{
   color PANEL=(color)C'14,16,22', SUB=(color)C'26,30,38', BAR=(color)C'45,50,60';
   int X=8,Y=16,W=352,H=452;
   Box("bg",X,Y,W,H,PANEL,(color)C'70,80,95');

   Lbl("title",X+12,Y+10,"XAU QUANT | "+g_symbol,clrGold,12,"Arial Bold");

   // REGIME highlighted bar
   string reg=(g_regime==REGIME_RANGE)?"RANGE":(g_regime==REGIME_TREND_UP?"TREND UP":"TREND DOWN");
   color rc=(g_regime==REGIME_RANGE)?(color)C'35,55,150':(g_regime==REGIME_TREND_UP?(color)C'20,90,40':(color)C'110,35,35');
   Box("regbar",X+10,Y+40,W-20,24,rc,rc);
   Lbl("regime",X+16,Y+45,"REGIME: "+reg,clrWhite,11,"Arial Bold");

   double bid=SymbolInfoDouble(g_symbol,SYMBOL_BID), ask=SymbolInfoDouble(g_symbol,SYMBOL_ASK);
   Lbl("quote",X+16,Y+74,StringFormat("Bid %.*f   Ask %.*f   Spread %.0f",g_digits,bid,g_digits,ask,
       (ask-bid)/SymbolInfoDouble(g_symbol,SYMBOL_POINT)),(color)C'160,160,175',9);

   // Confidence with progress bars
   Lbl("cbuy",X+16,Y+100,StringFormat("BUY CONF  %d",g_buyConf),clrWhite,10);
   Box("cbuybg",X+16,Y+122,150,12,BAR,BAR);
   Box("cbuybar",X+16,Y+122,(int)(150.0*g_buyConf/100.0),12,clrLime,clrLime);
   Lbl("csell",X+190,Y+100,StringFormat("SELL CONF  %d",g_sellConf),clrWhite,10);
   Box("csellbg",X+190,Y+122,150,12,BAR,BAR);
   Box("csellbar",X+190,Y+122,(int)(150.0*g_sellConf/100.0),12,clrTomato,clrTomato);

   // LONG basket box
   int Lv;double Lvol,Lavg,Lpl; BasketStats(POSITION_TYPE_BUY,Lv,Lvol,Lavg,Lpl);
   Box("lbox",X+10,Y+146,W-20,58,SUB,(color)C'30,110,55');
   Lbl("long",X+16,Y+152,"LONG BASKET",clrLime,11,"Arial Bold");
   if(Lv>0) Lbl("longd",X+16,Y+178,StringFormat("Lv %d    Avg %.*f    Vol %.2f    P/L %.2f",Lv,g_digits,Lavg,Lvol,Lpl),(Lpl>=0?clrLime:clrTomato),9);
   else     Lbl("longd",X+16,Y+178,"no basket open",(color)C'120,120,130',9);

   // SHORT basket box
   int Sv;double Svol,Savg,Spl; BasketStats(POSITION_TYPE_SELL,Sv,Svol,Savg,Spl);
   Box("sbox",X+10,Y+212,W-20,58,SUB,(color)C'130,40,40');
   Lbl("short",X+16,Y+218,"SHORT BASKET",clrTomato,11,"Arial Bold");
   if(Sv>0) Lbl("shortd",X+16,Y+244,StringFormat("Lv %d    Avg %.*f    Vol %.2f    P/L %.2f",Sv,g_digits,Savg,Svol,Spl),(Spl>=0?clrLime:clrTomato),9);
   else     Lbl("shortd",X+16,Y+244,"no basket open",(color)C'120,120,130',9);

   // MOMENTUM histogram (taller + live)
   Lbl("momlbl",X+16,Y+282,"MOMENTUM",(color)C'150,150,165',9);
   DrawMomentum(X+16,Y+302,W-32,96);

   Lbl("acct",X+16,Y+408,StringFormat("Balance %.2f    Equity %.2f",
       AccountInfoDouble(ACCOUNT_BALANCE),AccountInfoDouble(ACCOUNT_EQUITY)),clrWhite,9);
   Lbl("closed",X+16,Y+430,StringFormat("Closed baskets: %d",(int)GlobalVariableGet(GVName())),(color)C'170,170,185',9);

   g_panelBottomY=Y+H+4;
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
