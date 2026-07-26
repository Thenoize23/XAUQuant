@echo off
title XAUQuant Runner (DEMO)
cd /d C:\Users\conoi\XAUQuant\mcp
set XQ_AUTO_TRADE=true
set XQ_INTERVAL=30
echo Starting XAUQuant runner (DEMO). Make sure MT5 is open, logged into
echo the Axi demo account, and the Algo Trading button is GREEN.
echo Close this window to stop trading.
echo.
"C:\Users\conoi\AppData\Local\Programs\Python\Python312\python.exe" runner.py
echo.
echo Runner stopped. Press a key to close.
pause >nul
