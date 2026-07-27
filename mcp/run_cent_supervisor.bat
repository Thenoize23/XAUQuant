@echo off
REM Supervisor: keeps the CENT runner alive; restarts it if it ever exits.
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
set PYTHONUNBUFFERED=1
set PY="C:\Users\conoi\AppData\Local\Programs\Python\Python312\python.exe"
set LOG=C:\Users\conoi\XAUQuant\mcp\runner_cent.log

:loop
echo [%date% %time%] starting cent runner >> "%LOG%"
%PY% runner.py >> "%LOG%" 2>&1
echo [%date% %time%] runner exited (code %errorlevel%), restarting in 15s >> "%LOG%"
ping -n 16 127.0.0.1 >nul
goto loop
