@echo off
title XAUQuant Runner - CENT ($20 challenge)
cd /d C:\Users\conoi\XAUQuant\mcp
set XQ_MT5_PATH=C:\Program Files\MetaTrader 5 - Copy\terminal64.exe
set XQ_GOLD_SYMBOL=XAUUSD.c
set XQ_BTC_SYMBOL=BTCUSD
set XQ_GOLD_LOT=0.01
set XQ_BTC_LOT=0.0001
set XQ_GOLD_LEVELS=6
set XQ_BTC_LEVELS=6
set XQ_AUTO_TRADE=true
set XQ_INTERVAL=30
echo XAUQuant CENT runner ($20 challenge) on the "- Copy" MT5 instance.
echo Make sure that terminal is logged into the cent account (2000 USC)
echo and the Algo Trading button is GREEN.
echo Close this window to stop.
echo.
"C:\Users\conoi\AppData\Local\Programs\Python\Python312\python.exe" runner.py
echo.
echo Runner stopped. Press a key to close.
pause >nul
