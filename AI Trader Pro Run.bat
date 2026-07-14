@echo off
REM Always launches AI Trader Pro with the exact Python install that has
REM MetaTrader5 / tvDatafeed / ccxt installed, regardless of what "python"
REM resolves to on this machine's PATH.
"C:\Users\MOHSIN\AppData\Local\Programs\Python\Python312\python.exe" "%~dp0main.py"
pause
