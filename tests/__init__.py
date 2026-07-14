"""
AI Trader Pro — Test Suite

Run all tests:
    pytest tests/ -v

Run with coverage:
    pytest tests/ --cov=. --cov-report=html -v

Test categories:
    test_ai.py                  — Strategy engine (all 19 strategies)
    test_history.py             — Trade journal (CSV, thread safety)
    test_leverage_manager.py    — Position sizing, leverage, P&L
    test_market.py              — Technical indicators
    test_market_data_provider.py — Rate limiter, TTL cache
    test_notification_center.py — Notifications, dedup, memory bounds
    test_paper_trading.py       — Paper trading DB, SQL injection guards
    test_signal_storage.py      — Signal CRUD, lifecycle, thread safety
    test_smc_analysis.py        — Smart Money Concepts analysis
"""
