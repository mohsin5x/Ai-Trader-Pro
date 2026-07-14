"""
services/smc_analysis.py
=========================
Reusable Smart Money Concepts (SMC/ICT) structural analysis.

This module is intentionally separate from services/ai_engine.py.
ai_engine.py's `_process_*` methods each look at ONE timeframe and
immediately decide BUY/SELL/STAY OUT for a single named strategy (used
by the existing strategy dropdown + chart overlays -- untouched by this
module).

The AI Signal Engine (services/signal_engine.py) needs something
different: the raw *structural facts* (is there a bullish order block
near price? did a liquidity sweep just happen? is price in a discount
zone?) for several timeframes at once, so it can combine them into one
multi-timeframe confluence read instead of one strategy's single
opinion. That's what this module returns -- plain structural facts, no
BUY/SELL decision of its own.

Every function operates on a DataFrame that already has OHLCV columns
(and, where noted, the indicator columns added by
services/market_analyzer.MarketAnalyzer.calculate_indicators). No
network calls, no randomness -- pure calculation on whatever real
candle data is passed in.
"""

import pandas as pd
import numpy as np


def _swing_points(df: pd.DataFrame, lookback: int = 3):
    """Fractal-style swing highs/lows: a candle whose high/low is the
    extreme of its `lookback`-candle neighborhood on both sides."""
    highs, lows = [], []
    n = len(df)
    for i in range(lookback, n - lookback):
        window_hi = df['high'].iloc[i - lookback: i + lookback + 1]
        window_lo = df['low'].iloc[i - lookback: i + lookback + 1]
        if df['high'].iloc[i] == window_hi.max():
            highs.append(i)
        if df['low'].iloc[i] == window_lo.min():
            lows.append(i)
    return highs, lows


def analyze_smc(df: pd.DataFrame) -> dict:
    """Runs every Smart Money Concept check against the tail of `df` and
    returns a dict of structural facts. Safe to call on any timeframe's
    candle data. Returns a dict with `valid: False` if there isn't
    enough real candle data yet (never fabricates a reading)."""

    facts = {
        "valid": False, "trend_bias": "neutral",
        "bos": None, "choch": None, "liquidity_sweep": None,
        "order_block": None, "breaker_block": None, "mitigation_block": None,
        "fvg": None, "zone": "equilibrium", "supply_demand": None,
        "support": None, "resistance": None, "equal_highs": False, "equal_lows": False,
        "notes": [],
    }
    if df is None or df.empty or len(df) < 30:
        return facts

    d = df.tail(120).reset_index(drop=True)
    facts["valid"] = True
    closes, highs, lows = d['close'], d['high'], d['low']
    last_close = closes.iloc[-1]
    swing_hi_idx, swing_lo_idx = _swing_points(d, lookback=3)

    # ---- Trend bias (EMA20 vs EMA50, if present) ----
    if "EMA20" in d.columns and "EMA50" in d.columns:
        ema20, ema50 = d['EMA20'].iloc[-1], d['EMA50'].iloc[-1]
        if ema20 > ema50:
            facts["trend_bias"] = "bullish"
        elif ema20 < ema50:
            facts["trend_bias"] = "bearish"

    # ---- Break of Structure / Change of Character ----
    if swing_hi_idx and swing_lo_idx:
        last_swing_high = highs.iloc[swing_hi_idx[-1]]
        last_swing_low = lows.iloc[swing_lo_idx[-1]]
        if last_close > last_swing_high:
            is_with_trend = facts["trend_bias"] != "bearish"
            facts["bos" if is_with_trend else "choch"] = "bullish"
            facts["notes"].append("Price closed above the prior swing high (structure break to the upside).")
        elif last_close < last_swing_low:
            is_with_trend = facts["trend_bias"] != "bullish"
            facts["bos" if is_with_trend else "choch"] = "bearish"
            facts["notes"].append("Price closed below the prior swing low (structure break to the downside).")

    # ---- Liquidity sweep (wick beyond a recent extreme, then close back inside) ----
    lookback_n = min(20, len(d) - 2)
    if lookback_n > 2:
        recent_high = highs.iloc[-(lookback_n + 1):-1].max()
        recent_low = lows.iloc[-(lookback_n + 1):-1].min()
        last = d.iloc[-1]
        if last['high'] > recent_high and last['close'] < recent_high:
            facts["liquidity_sweep"] = "bearish"  # swept buy-side liquidity, closed back down
            facts["notes"].append("Buy-side liquidity swept above the recent high, then price closed back below it.")
        elif last['low'] < recent_low and last['close'] > recent_low:
            facts["liquidity_sweep"] = "bullish"  # swept sell-side liquidity, closed back up
            facts["notes"].append("Sell-side liquidity swept below the recent low, then price closed back above it.")

    # ---- Equal highs / equal lows (resting liquidity pools) ----
    if len(swing_hi_idx) >= 2:
        h1, h2 = highs.iloc[swing_hi_idx[-1]], highs.iloc[swing_hi_idx[-2]]
        if abs(h1 - h2) / max(h1, 1e-9) < 0.0015:
            facts["equal_highs"] = True
    if len(swing_lo_idx) >= 2:
        l1, l2 = lows.iloc[swing_lo_idx[-1]], lows.iloc[swing_lo_idx[-2]]
        if abs(l1 - l2) / max(l1, 1e-9) < 0.0015:
            facts["equal_lows"] = True

    # ---- Order blocks / breaker blocks / mitigation blocks ----
    # Last opposite-colour candle before a strong (>1.5x average body)
    # directional move; if price has since traded back into that
    # candle's range, it's a live order block. If structure has since
    # broken *through* it, the same zone is reclassified as a breaker
    # block (failed order block) / mitigation block (origin of the move
    # being partially filled).
    body = (d['close'] - d['open']).abs()
    avg_body = body.rolling(10).mean()
    for i in range(len(d) - 2, max(len(d) - 25, 5), -1):
        move_body = d['close'].iloc[i + 1] - d['open'].iloc[i + 1]
        if avg_body.iloc[i] and abs(move_body) > 1.5 * avg_body.iloc[i]:
            is_bull_move = move_body > 0
            candle_is_opposite = (d['close'].iloc[i] < d['open'].iloc[i]) if is_bull_move else (d['close'].iloc[i] > d['open'].iloc[i])
            if not candle_is_opposite:
                continue
            zone_low, zone_high = d['low'].iloc[i], d['high'].iloc[i]
            direction = "bullish" if is_bull_move else "bearish"
            retested = zone_low <= last_close <= zone_high
            broken_through = (last_close < zone_low) if is_bull_move else (last_close > zone_high)
            if broken_through:
                facts["breaker_block"] = direction
                facts["mitigation_block"] = direction
                facts["notes"].append(f"A former {direction} order block has been broken through and is acting as a breaker/mitigation zone.")
            elif retested:
                facts["order_block"] = direction
                facts["notes"].append(f"Price has returned into a {direction} order block from a prior displacement move.")
            break

    # ---- Fair Value Gap (3-candle imbalance), most recent unfilled one ----
    for i in range(len(d) - 3, max(len(d) - 30, 0), -1):
        c1_high, c1_low = d['high'].iloc[i], d['low'].iloc[i]
        c3_high, c3_low = d['high'].iloc[i + 2], d['low'].iloc[i + 2]
        if c3_low > c1_high:
            gap_low, gap_high = c1_high, c3_low
            if not (last_close > gap_high or last_close < gap_low):
                facts["fvg"] = "bullish"
                facts["notes"].append("Price is trading inside an unfilled bullish Fair Value Gap.")
                break
        elif c1_low > c3_high:
            gap_low, gap_high = c3_high, c1_low
            if not (last_close > gap_high or last_close < gap_low):
                facts["fvg"] = "bearish"
                facts["notes"].append("Price is trading inside an unfilled bearish Fair Value Gap.")
                break

    # ---- Premium / Discount zone (relative to recent range) ----
    range_high, range_low = highs.tail(50).max(), lows.tail(50).min()
    span = range_high - range_low
    if span > 0:
        pos = (last_close - range_low) / span
        if pos >= 0.66:
            facts["zone"] = "premium"
        elif pos <= 0.33:
            facts["zone"] = "discount"
        else:
            facts["zone"] = "equilibrium"

    # ---- Supply & Demand (simple zone from strongest recent impulse) ----
    if len(d) > 15:
        impulse_idx = body.tail(30).idxmax()
        if pd.notna(impulse_idx):
            is_up = d['close'].iloc[impulse_idx] > d['open'].iloc[impulse_idx]
            facts["supply_demand"] = "demand" if is_up else "supply"

    # ---- Support & Resistance (nearest recent swing levels) ----
    if swing_hi_idx:
        facts["resistance"] = float(highs.iloc[swing_hi_idx[-1]])
    if swing_lo_idx:
        facts["support"] = float(lows.iloc[swing_lo_idx[-1]])

    return facts
