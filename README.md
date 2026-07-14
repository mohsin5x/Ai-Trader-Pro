# AI Trader Pro v2.0 — Production Edition

**Professional AI Trading Terminal** — Dark-themed, multi-strategy, multi-asset paper trading and analysis platform built with Python and CustomTkinter.

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure your API key (choose one method)

**Method A — .env file (recommended):**
```bash
cp .env.example .env
# Edit .env and set your Twelve Data key:
# TWELVE_DATA_API_KEY=your_key_here
```

**Method B — Settings panel:**  
Launch the app → click ⚙️ Settings → select TwelveData → paste key → Save

**Method C — OS Keyring (most secure):**  
The app automatically stores keys in your OS credential store when the `keyring` package is installed. Install it with `pip install keyring`.

> **Free data sources**: Select "Default (Free)" in Settings for basic crypto quotes via ccxt/TradingView — no API key required.

### 3. Run
```bash
python main.py
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+1` | Dashboard |
| `Ctrl+2` | AI Signals |
| `Ctrl+3` | Signal History |
| `Ctrl+4` | Market Scanner |
| `Ctrl+5` | Manual Scanner |
| `Ctrl+6` | Watchlist |
| `Ctrl+7` | News |
| `Ctrl+8` | Settings |
| `Ctrl+R` / `F5` | Refresh analysis |
| `F11` | Toggle chart fullscreen |
| `Ctrl+Q` | Exit (with confirmation) |
| `↑ ↓ ← →` | Scroll panels |
| `PgUp / PgDn` | Fast scroll |
| `Home / End` | Scroll to top / bottom |

---

## Trading Strategies (19 Total)

### ICT / Smart Money Concepts
| Strategy | Description |
|----------|-------------|
| ICT Smart Money | Liquidity sweeps + Fair Value Gap displacement |
| Smart Money Concepts | EMA-based trend + accumulation/distribution zones |
| Order Blocks | Institutional candle zone retest entries |
| Fair Value Gaps | 3-candle imbalance fill setups |
| Break of Structure | Structural confirmation for trend continuation |
| Change of Character | Counter-trend structural break detection |
| Liquidity Concepts | Equal highs/lows stop-hunt reversal setups |

### Technical Analysis
| Strategy | Description |
|----------|-------------|
| EMA Crossover | Golden/death cross + established alignment |
| MACD | Histogram sign-change momentum signals |
| RSI | Oversold/overbought mean-reversion |
| VWAP | Discount/premium zone entries vs fair value |
| Price Action | Pin bars + engulfing patterns (no indicators) |
| Scalping | RSI extreme micro-reversion on short timeframes |
| Swing Trading | EMA20/50 separation trend entries |
| Trend Following | SMA200 macro trend (1:3 RR targets) |
| Breakout | Bollinger Band volatility expansion |

### Multi-Factor
| Strategy | Description |
|----------|-------------|
| Multi-Timeframe | 5-indicator confluence scoring |
| ATR | Volatility expansion breakout detection |

---

## Security

- **API keys are never stored in plain text** when `keyring` is installed  
- OS Keyring → `.env` file → `config.json` priority chain  
- `config.json` is in `.gitignore` — never commit it  
- `.env` is in `.gitignore` — never commit it  
- All SQL queries use parameterised statements (no injection risk)  
- Identifiers in dynamic DDL statements are validated against an allowlist  

---

## Architecture

```
AI Trader Pro/
├── main.py                      # Entry point, DPI awareness, keyboard nav
├── config/
│   └── settings.py              # All constants, env-var overrides
├── services/
│   ├── ai_engine.py             # 19 strategy implementations
│   ├── signal_engine.py         # Multi-timeframe AI signal pipeline
│   ├── market_analyzer.py       # Technical indicators (OHLCV → DataFrame)
│   ├── smc_analysis.py          # Smart Money Concepts structural analysis
│   ├── market_scanner.py        # Background auto-scanner (all assets)
│   ├── crypto_service.py        # Market data orchestration
│   ├── market_data_provider.py  # Provider base + rate limiter + TTL cache
│   ├── paper_trading_engine.py  # Automatic paper trading (TP/SL tracking)
│   ├── paper_trading_db.py      # SQLite persistence for paper trades
│   ├── signal_storage.py        # SQLite persistence for AI signals
│   ├── history_service.py       # CSV trade journal (thread-safe)
│   ├── leverage_manager.py      # Position sizing + leverage (persisted)
│   ├── notification_center.py   # Thread-safe notification hub
│   └── provider_settings.py     # Config + API key management
├── ui/
│   ├── main_window.py           # Application window (2,238 lines)
│   └── ...                      # 25+ panel/page components
├── utils/
│   ├── secret_manager.py        # OS Keyring → .env → config.json
│   ├── logger.py                # Rotating file + console logger
│   ├── error_handler.py         # Retry decorator, safe_call helper
│   └── path_manager.py          # EXE-safe path resolution
└── tests/                       # 136 tests across 9 test files
```

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage report
pytest tests/ --cov=. --cov-report=html -v
open htmlcov/index.html

# Specific module
pytest tests/test_ai.py -v
pytest tests/test_notification_center.py -v
```

**Test coverage:** 136 tests across 9 test files covering:
- All 19 trading strategies (output validation, edge cases)
- Thread safety (concurrent writes, listener management)
- SQL injection prevention
- Memory bounds (notification center, TTL cache)
- Position sizing accuracy
- Rate limiter concurrency

---

## Environment Variables

See `.env.example` for all configurable options. Key variables:

```bash
TWELVE_DATA_API_KEY=          # Twelve Data API key
DATA_PROVIDER=twelvedata      # twelvedata | finnhub | alphavantage
SIGNAL_MIN_CONFLUENCE=4       # Min confirmations for signal
SIGNAL_MIN_CONFIDENCE=70      # Min confidence % to show signal
SIGNAL_SCAN_INTERVAL_SECONDS=90  # How often to scan each symbol
SCANNER_NOTIFY_COOLDOWN_SECONDS=300  # Min sec between repeat alerts
TWELVE_DATA_RATE_LIMIT=8      # API credits per 60s (raise for paid plans)
```

---

## Data Providers

| Provider | Free Tier | Best For |
|----------|-----------|----------|
| Default (Free) | Unlimited | Crypto only |
| Twelve Data | 8 credits/min | Forex + Crypto + Indices |
| Finnhub | 30 req/min | Stocks + Crypto |
| Alpha Vantage | 5 req/min | Stocks + Forex |
| MetaTrader 5 | n/a (broker) | Windows + MT5 broker |

---

## License

AI Trader Pro — Professional AI Trading Terminal  
© Mohsin Abbas. All rights reserved.
=======
# Ai-Trader-Pro
Analysis Ai 
>>>>>>> 98b78a91006c25010cb4047650940a15f747b2db
