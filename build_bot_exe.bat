@echo off
REM ==========================================================================
REM  Builds Kestrel.exe (v3.13.0) from main.py + IB.py + Tradezero.py + kestrel_discord.py + lh_long_premarket.py
REM  + jay_read_short.py + max_squeeze_short.py. Put this file in the same folder as the .py files and double-click it.
REM ==========================================================================
setlocal
cd /d "%~dp0"

for %%F in (main.py core\settings.py core\bot\bot_core.py core\data\IB.py core\data\helpers.py core\data\vault_feed.py core\data\tickfeed.py core\data\chart_notes.py core\broker\Tradezero.py core\notify\kestrel_discord.py core\window\jsapi.py core\backtest_engine\kestrel_backtest.py ui\app.html ui\app.css ui\js\01_boot.js) do (
  if not exist %%F (
    echo %%F was not found in %cd% - keep main.py with its core and ui folders
    goto :err
  )
)
if not exist backtest\premarket_long\lh_long_premarket.py (
  echo backtest\premarket_long\lh_long_premarket.py was not found - the strategy files live in the backtest folder
  goto :err
)
if not exist backtest\jay_read_short\jay_read_short.py (
  echo backtest\jay_read_short\jay_read_short.py was not found - the strategy files live in the backtest folder - it is the Jay-read short
  goto :err
)
if not exist backtest\jay_read_2\jay_read_2_short.py (
  echo backtest\jay_read_2\jay_read_2_short.py was not found - it is the 3.13.0 Jay-read 2 short
  goto :err
)
if not exist backtest\max_squeeze_short\max_squeeze_short.py (
  echo backtest\max_squeeze_short\max_squeeze_short.py was not found - the strategy files live in the backtest folder - it is the 3.9.0 max squeeze short
  goto :err
)

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

echo [1/4] Creating a clean build environment (.venv) ...
%PY% -m venv .venv || goto :err
call .venv\Scripts\activate.bat || goto :err

echo [2/4] Installing packages ...
python -m pip install --upgrade pip >nul
python -m pip install pywebview ib_async pandas numpy tzdata matplotlib pyinstaller || goto :err

echo [3/4] Downloading the chart library so the .exe works offline ...
set "LWC=lightweight-charts-4.2.3.js"
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js' -OutFile '%LWC%' } catch { exit 1 }"
set "ADDLWC="
if exist "%LWC%" set "ADDLWC=--add-data %LWC%;."

echo [4/4] Building the .exe (takes 1-3 minutes) ...
pyinstaller --noconfirm --clean --onefile --windowed --name Kestrel ^
  --collect-data tzdata --collect-data pytz --hidden-import matplotlib.backends.backend_agg ^
  --hidden-import lh_long_premarket --hidden-import jay_read_short --hidden-import jay_read_2_short --hidden-import max_squeeze_short ^
  --hidden-import IB --hidden-import Tradezero --hidden-import kestrel_discord --hidden-import kestrel_backtest --hidden-import vault_feed --hidden-import tickfeed --hidden-import turso --hidden-import turso_vault --hidden-import newsfeed --hidden-import websockets --hidden-import tradedb --hidden-import missed --hidden-import strat_settings --hidden-import floats --hidden-import scan_spark --hidden-import tape --hidden-import chart_notes ^
  --hidden-import lh_combined_backtester --hidden-import lh_vault_bars --paths . ^
  --paths core --paths core\data --paths core\broker --paths core\notify --paths core\backtest_engine --hidden-import webview --hidden-import winsound --hidden-import pytz --hidden-import zoneinfo --hidden-import csv ^
  --add-data "core;core" --add-data "ui;ui" ^
  --paths backtest\_shared --paths backtest\jay_read_short --paths backtest\jay_read_2 --paths backtest\max_squeeze_short --paths backtest\premarket_long ^
  %ADDLWC% main.py || goto :err

if exist .env.example copy /Y .env.example dist\.env.example >nul
if exist .env if not exist dist\.env copy /Y .env dist\.env >nul

echo.
echo ==========================================================================
echo  Done:  %cd%\dist\Kestrel.exe
echo  Start IB Gateway first (before 05:00 for the premarket long), then
echo  double-click the .exe. Credentials: the .env file next to the .exe - the
echo  first start creates it from the keys you saved before (or copy
echo  .env.example to .env and fill it in with Notepad).
echo  Optional: extra_tickers.txt next to the .exe = tickers for the long scanner.
echo ==========================================================================
pause
exit /b 0

:err
echo.
echo Build failed - see the messages above.
pause
exit /b 1
