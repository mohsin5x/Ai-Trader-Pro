"""
=========================================================
 AI Trader Pro - Strategy Chart Overlay Engine
=========================================================
Turns a strategy name + market dataframe into a list of
generic, chart-agnostic drawing primitives ("overlays") that
ui/chart_widget.py knows how to render. This keeps strategy
detection logic out of the rendering layer entirely.

Overlay primitive schema (plain dicts, all keys optional
except 'kind'):

    {
        "kind":  "zone" | "hline" | "line" | "marker",
        "i0":    int,                  # candle index (full dataframe)
        "i1":    int | "end",          # zone/hline/line end index
        "p0":    float,                # price (zone lower bound / hline / marker / line start)
        "p1":    float | None,         # zone upper bound / line end price
        "color": "#rrggbb",
        "label": str | None,
        "style": "fill" | "outline" | "dashed" | "solid",
        "shape": "up" | "down" | "circle",   # markers only
        "width": float,
    }

Indices are positions into the dataframe AS PASSED IN
(after reset_index(drop=True)), so the chart widget can map
them into its own visible window.
"""

import pandas as pd

# Local color palette mirroring ui/theme.py -- kept independent so this
# service has no dependency on the UI layer.
GREEN = "#10D9A0"
RED = "#FF5C7A"
BLUE = "#4C8DFF"
CYAN = "#22D3EE"
ORANGE = "#F5A623"
PURPLE = "#B37FEB"
GREY = "#5C6B82"
WHITE = "#F4F6FA"


def build_overlays(df: pd.DataFrame, strategy: str, ai_result: dict = None) -> list:
    """Main entry point. Returns a list of overlay primitives for the given
    strategy, plus a universal Risk/Reward box when entry/SL/TP are known."""
    if df is None or df.empty or len(df) < 20:
        return []

    df = df.reset_index(drop=True)
    ai_result = ai_result or {}
    key = (strategy or "").strip().lower()

    handlers = {
        "ict smart money": _ict_overlays,
        "smart money concepts": _ict_overlays,
        "support & resistance": _sr_overlays,
        "liquidity concepts": _liquidity_overlays,
        "order blocks": _orderblock_overlays,
        "fair value gaps": _fvg_overlays,
        "break of structure": _bos_overlays,
        "change of character": _choch_overlays,
        "scalping": _scalping_overlays,
        "swing trading": _trend_overlays,
        "trend following": _trend_overlays,
        "breakout": _breakout_overlays,
    }

    handler = handlers.get(key, _breakout_overlays)
    overlays = handler(df, ai_result)
    overlays += _risk_reward_box(df, ai_result)
    return overlays


# =========================================================
# SHARED STRUCTURE DETECTION
# =========================================================
def _find_swings(df: pd.DataFrame, window: int = 3):
    """Returns (swing_high_indices, swing_low_indices): local extrema over
    a +/- window bar neighborhood."""
    n = len(df)
    highs, lows = [], []
    for i in range(window, n - window):
        seg_h = df['high'].iloc[i - window:i + window + 1]
        seg_l = df['low'].iloc[i - window:i + window + 1]
        if df['high'].iloc[i] == seg_h.max():
            highs.append(i)
        if df['low'].iloc[i] == seg_l.min():
            lows.append(i)
    return highs, lows


def _avg_range(df: pd.DataFrame, i: int, lookback: int = 10) -> float:
    seg = (df['high'] - df['low']).iloc[max(0, i - lookback):i]
    val = seg.mean()
    return float(val) if val and val > 0 else float(df['close'].iloc[i]) * 0.0005


def _find_order_blocks(df: pd.DataFrame, lookback: int = 45):
    """Last opposite-colour candle immediately preceding a strong impulsive
    move -- the classic ICT order-block definition."""
    n = len(df)
    start = max(1, n - lookback)
    obs = []
    for i in range(start, n - 1):
        body = df['close'].iloc[i] - df['open'].iloc[i]
        nxt_body = df['close'].iloc[i + 1] - df['open'].iloc[i + 1]
        impulsive = abs(nxt_body) > _avg_range(df, i) * 1.3
        if body < 0 and nxt_body > 0 and impulsive:
            obs.append(("bullish", i))
        elif body > 0 and nxt_body < 0 and impulsive:
            obs.append(("bearish", i))
    return obs[-4:]


def _find_fvgs(df: pd.DataFrame, lookback: int = 45):
    """3-candle imbalance: candle[i-1] and candle[i+1] don't overlap, leaving
    a Fair Value Gap at candle[i]."""
    n = len(df)
    start = max(1, n - lookback)
    gaps = []
    for i in range(start, n - 1):
        c1, c3 = df.iloc[i - 1], df.iloc[i + 1]
        if c1['high'] < c3['low']:
            gaps.append(("bullish", i, c1['high'], c3['low']))
        elif c1['low'] > c3['high']:
            gaps.append(("bearish", i, c3['high'], c1['low']))
    return gaps[-5:]


def _find_liquidity_sweeps(df: pd.DataFrame, lookback: int = 45):
    """A candle wicks beyond the recent swing extreme then closes back
    inside it -- a stop-hunt / liquidity sweep."""
    n = len(df)
    sweeps = []
    for i in range(max(20, n - lookback), n):
        recent_low = df['low'].iloc[max(0, i - 20):i].min()
        recent_high = df['high'].iloc[max(0, i - 20):i].max()
        row = df.iloc[i]
        if row['low'] < recent_low and row['close'] > recent_low:
            sweeps.append(("bullish", i, row['low']))
        elif row['high'] > recent_high and row['close'] < recent_high:
            sweeps.append(("bearish", i, row['high']))
    return sweeps[-4:]


def _find_bos_choch(df: pd.DataFrame):
    """Compares the two most recent confirmed swing highs/lows against the
    prevailing EMA20/EMA50 trend bias to classify structural breaks as
    Break of Structure (with-trend) or Change of Character (counter-trend)."""
    highs_idx, lows_idx = _find_swings(df, window=3)
    events = []
    if len(highs_idx) < 2 or len(lows_idx) < 2:
        return events

    ema20 = df['EMA20'].iloc[-1] if 'EMA20' in df.columns else df['close'].iloc[-1]
    ema50 = df['EMA50'].iloc[-1] if 'EMA50' in df.columns else df['close'].iloc[-1]
    bullish_bias = ema20 >= ema50

    last_swing_high_i = highs_idx[-1]
    last_swing_low_i = lows_idx[-1]
    current_close = df['close'].iloc[-1]
    n = len(df)

    if current_close > df['high'].iloc[last_swing_high_i] and last_swing_high_i < n - 1:
        label = "BOS" if bullish_bias else "CHoCH"
        color = GREEN if bullish_bias else CYAN
        events.append((label, last_swing_high_i, df['high'].iloc[last_swing_high_i], color))

    if current_close < df['low'].iloc[last_swing_low_i] and last_swing_low_i < n - 1:
        label = "BOS" if not bullish_bias else "CHoCH"
        color = RED if not bullish_bias else ORANGE
        events.append((label, last_swing_low_i, df['low'].iloc[last_swing_low_i], color))

    return events


# =========================================================
# ICT SMART MONEY / SMART MONEY CONCEPTS
# =========================================================
def _ict_overlays(df: pd.DataFrame, ai_result: dict) -> list:
    n = len(df)
    overlays = []

    # Order Blocks + Institutional Buy/Sell Areas
    for kind, i in _find_order_blocks(df):
        color = GREEN if kind == "bullish" else RED
        overlays.append({
            "kind": "zone", "i0": i, "i1": "end",
            "p0": df['low'].iloc[i], "p1": df['high'].iloc[i],
            "color": color, "style": "fill",
            "label": "Bullish OB" if kind == "bullish" else "Bearish OB",
        })

    # Fair Value Gaps
    for kind, i, lo, hi in _find_fvgs(df):
        color = GREEN if kind == "bullish" else RED
        overlays.append({
            "kind": "zone", "i0": i, "i1": "end", "p0": lo, "p1": hi,
            "color": color, "style": "outline", "label": "FVG",
        })

    # Liquidity Sweeps
    for kind, i, price in _find_liquidity_sweeps(df):
        overlays.append({
            "kind": "marker", "i0": i, "p0": price,
            "shape": "up" if kind == "bullish" else "down",
            "color": CYAN, "label": "Sweep",
        })

    # Liquidity Zones (equal highs/lows clusters)
    for i0, i1, price, side in _cluster_liquidity(df):
        overlays.append({
            "kind": "hline", "i0": i0, "i1": "end", "p0": price,
            "color": PURPLE, "style": "dashed",
            "label": "Liquidity" + (" (Buy-side)" if side == "high" else " (Sell-side)"),
        })

    # BOS / CHoCH
    for label, i, price, color in _find_bos_choch(df):
        overlays.append({
            "kind": "hline", "i0": i, "i1": "end", "p0": price,
            "color": color, "style": "dashed", "label": label,
        })

    # Market Structure zig-zag across swing points
    overlays += _market_structure_line(df)

    # Premium / Discount zones (equilibrium split of the recent range)
    overlays += _premium_discount_zones(df)

    return overlays


def _cluster_liquidity(df: pd.DataFrame, lookback: int = 45, tolerance: float = 0.0012):
    """Groups nearby swing highs (and lows) into equal-highs/equal-lows
    liquidity pools."""
    highs_idx, lows_idx = _find_swings(df, window=2)
    n = len(df)
    highs_idx = [i for i in highs_idx if i >= n - lookback]
    lows_idx = [i for i in lows_idx if i >= n - lookback]
    pools = []

    for idx_list, col, side in ((highs_idx, 'high', 'high'), (lows_idx, 'low', 'low')):
        used = set()
        for a in idx_list:
            if a in used:
                continue
            group = [a]
            price_a = df[col].iloc[a]
            for b in idx_list:
                if b == a or b in used:
                    continue
                price_b = df[col].iloc[b]
                if abs(price_a - price_b) / price_a <= tolerance:
                    group.append(b)
                    used.add(b)
            if len(group) >= 2:
                used.add(a)
                avg_price = df[col].iloc[group].mean()
                pools.append((min(group), max(group), avg_price, side))
    pools.sort(key=lambda p: p[0])
    return pools[-3:]


def _market_structure_line(df: pd.DataFrame):
    highs_idx, lows_idx = _find_swings(df, window=3)
    points = sorted([(i, df['high'].iloc[i]) for i in highs_idx[-4:]] +
                     [(i, df['low'].iloc[i]) for i in lows_idx[-4:]], key=lambda p: p[0])
    overlays = []
    for a, b in zip(points, points[1:]):
        overlays.append({
            "kind": "line", "i0": a[0], "i1": b[0], "p0": a[1], "p1": b[1],
            "color": GREY, "width": 1.0,
        })
    return overlays


def _premium_discount_zones(df: pd.DataFrame, lookback: int = 40):
    n = len(df)
    seg = df.iloc[max(0, n - lookback):n]
    hi, lo = seg['high'].max(), seg['low'].min()
    mid = (hi + lo) / 2.0
    start_i = max(0, n - lookback)
    return [
        {"kind": "zone", "i0": start_i, "i1": "end", "p0": mid, "p1": hi,
         "color": RED, "style": "fill", "label": "Premium"},
        {"kind": "zone", "i0": start_i, "i1": "end", "p0": lo, "p1": mid,
         "color": GREEN, "style": "fill", "label": "Discount"},
    ]


# =========================================================
# LIQUIDITY CONCEPTS / ORDER BLOCKS / FVG / BOS / CHOCH (standalone views)
# =========================================================
def _liquidity_overlays(df, ai_result):
    overlays = []
    for kind, i, price in _find_liquidity_sweeps(df):
        overlays.append({"kind": "marker", "i0": i, "p0": price,
                          "shape": "up" if kind == "bullish" else "down",
                          "color": CYAN, "label": "Liquidity Sweep"})
    for i0, i1, price, side in _cluster_liquidity(df):
        overlays.append({"kind": "hline", "i0": i0, "i1": "end", "p0": price,
                          "color": PURPLE, "style": "dashed",
                          "label": "Liquidity Pool (" + side + ")"})
    return overlays


def _orderblock_overlays(df, ai_result):
    overlays = []
    for kind, i in _find_order_blocks(df, lookback=60):
        color = GREEN if kind == "bullish" else RED
        overlays.append({"kind": "zone", "i0": i, "i1": "end",
                          "p0": df['low'].iloc[i], "p1": df['high'].iloc[i],
                          "color": color, "style": "fill",
                          "label": "Bullish Order Block" if kind == "bullish" else "Bearish Order Block"})
    return overlays


def _fvg_overlays(df, ai_result):
    overlays = []
    for kind, i, lo, hi in _find_fvgs(df, lookback=60):
        color = GREEN if kind == "bullish" else RED
        overlays.append({"kind": "zone", "i0": i, "i1": "end", "p0": lo, "p1": hi,
                          "color": color, "style": "outline",
                          "label": "Bullish FVG" if kind == "bullish" else "Bearish FVG"})
    return overlays


def _bos_overlays(df, ai_result):
    overlays = _market_structure_line(df)
    for label, i, price, color in _find_bos_choch(df):
        if label == "BOS":
            overlays.append({"kind": "hline", "i0": i, "i1": "end", "p0": price,
                              "color": color, "style": "dashed", "label": "Break of Structure"})
    return overlays


def _choch_overlays(df, ai_result):
    overlays = _market_structure_line(df)
    for label, i, price, color in _find_bos_choch(df):
        if label == "CHoCH":
            overlays.append({"kind": "hline", "i0": i, "i1": "end", "p0": price,
                              "color": color, "style": "dashed", "label": "Change of Character"})
    return overlays


# =========================================================
# SUPPORT & RESISTANCE
# =========================================================
def _sr_overlays(df: pd.DataFrame, ai_result: dict, lookback: int = 60, tolerance: float = 0.0015) -> list:
    n = len(df)
    highs_idx, lows_idx = _find_swings(df, window=3)
    highs_idx = [i for i in highs_idx if i >= n - lookback]
    lows_idx = [i for i in lows_idx if i >= n - lookback]

    levels = []  # (price, first_index, touches, kind)
    for idx_list, col, kind in ((highs_idx, 'high', 'resistance'), (lows_idx, 'low', 'support')):
        used = set()
        for a in idx_list:
            if a in used:
                continue
            group = [a]
            price_a = df[col].iloc[a]
            for b in idx_list:
                if b == a or b in used:
                    continue
                if abs(price_a - df[col].iloc[b]) / price_a <= tolerance:
                    group.append(b)
                    used.add(b)
            used.add(a)
            avg_price = df[col].iloc[group].mean()
            levels.append([avg_price, min(group), len(group), kind])

    current_price = df['close'].iloc[-1]
    overlays = []
    for price, first_i, touches, kind in levels[-8:]:
        strong = touches >= 3
        broken = (kind == 'resistance' and current_price > price * (1 + tolerance)) or \
                 (kind == 'support' and current_price < price * (1 - tolerance))

        if broken:
            label = "Broken Level"
            color = GREY
            style = "dashed"
        elif strong:
            label = "Strong Resistance" if kind == 'resistance' else "Strong Support"
            color = RED if kind == 'resistance' else GREEN
            style = "solid"
        else:
            label = "Resistance" if kind == 'resistance' else "Support"
            color = ORANGE if kind == 'resistance' else CYAN
            style = "solid"

        overlays.append({
            "kind": "hline", "i0": first_i, "i1": "end", "p0": price,
            "color": color, "style": style, "label": label,
            "width": 2.0 if strong else 1.2,
        })

        # Retest marker: price has revisited a broken level after breaking it
        if broken:
            after = df.iloc[first_i + 1:]
            close_enough = after[(after['low'] <= price * (1 + tolerance)) &
                                  (after['high'] >= price * (1 - tolerance))]
            if not close_enough.empty:
                retest_i = close_enough.index[-1]
                overlays.append({"kind": "marker", "i0": int(retest_i), "p0": price,
                                  "shape": "circle", "color": WHITE, "label": "Retest"})

    return overlays


# =========================================================
# TREND FOLLOWING / SWING TRADING
# =========================================================
def _trend_overlays(df: pd.DataFrame, ai_result: dict, lookback: int = 60) -> list:
    n = len(df)
    highs_idx, lows_idx = _find_swings(df, window=3)
    highs_idx = [i for i in highs_idx if i >= n - lookback]
    lows_idx = [i for i in lows_idx if i >= n - lookback]

    overlays = []
    ema20 = df['EMA20'].iloc[-1] if 'EMA20' in df.columns else df['close'].iloc[-1]
    ema50 = df['EMA50'].iloc[-1] if 'EMA50' in df.columns else df['close'].iloc[-1]
    uptrend = ema20 >= ema50

    # HH/HL or LH/LL markers + labels
    pts = lows_idx if uptrend else highs_idx
    price_col = 'low' if uptrend else 'high'
    labels_cycle = ["HL", "HH"] if uptrend else ["LH", "LL"]
    for n_i, i in enumerate(pts[-4:]):
        overlays.append({
            "kind": "marker", "i0": i, "p0": df[price_col].iloc[i],
            "shape": "up" if uptrend else "down",
            "color": GREEN if uptrend else RED,
            "label": labels_cycle[n_i % 2],
        })

    # Trend line across the last two swing points in trend direction
    if len(pts) >= 2:
        a, b = pts[-2], pts[-1]
        overlays.append({
            "kind": "line", "i0": a, "i1": n - 1,
            "p0": df[price_col].iloc[a],
            "p1": df[price_col].iloc[a] + (df[price_col].iloc[b] - df[price_col].iloc[a]) *
                  ((n - 1 - a) / max(1, (b - a))),
            "color": GREEN if uptrend else RED, "width": 1.6,
        })

    # Pullback area around the fast EMA
    if 'EMA20' in df.columns:
        band = df['close'].iloc[-1] * 0.0025
        overlays.append({
            "kind": "zone", "i0": max(0, n - 15), "i1": "end",
            "p0": ema20 - band, "p1": ema20 + band,
            "color": BLUE, "style": "fill", "label": "Pullback Area",
        })

    return overlays


# =========================================================
# BREAKOUT
# =========================================================
def _breakout_overlays(df: pd.DataFrame, ai_result: dict, lookback: int = 25) -> list:
    n = len(df)
    seg_start = max(0, n - lookback)
    seg = df.iloc[seg_start:n - 1] if n > 1 else df.iloc[seg_start:n]
    if seg.empty:
        return []

    box_hi, box_lo = seg['high'].max(), seg['low'].min()
    current = df.iloc[-1]
    overlays = [{
        "kind": "zone", "i0": seg_start, "i1": len(df) - 2 if n > 1 else len(df) - 1,
        "p0": box_lo, "p1": box_hi, "color": GREY, "style": "outline",
        "label": "Breakout Zone",
    }]

    broke_up = current['close'] > box_hi
    broke_down = current['close'] < box_lo

    if broke_up or broke_down:
        level = box_hi if broke_up else box_lo
        confirmed = abs(current['close'] - level) > _avg_range(df, n - 1) * 0.5
        label = "Breakout Confirmation" if confirmed else "Invalid Breakout"
        color = GREEN if (confirmed and broke_up) else (RED if confirmed else ORANGE)
        overlays.append({"kind": "hline", "i0": n - 2, "i1": "end", "p0": level,
                          "color": color, "style": "dashed", "label": label})
        overlays.append({"kind": "zone", "i0": n - 4, "i1": "end",
                          "p0": min(level, current['close']), "p1": max(level, current['close']),
                          "color": CYAN, "style": "fill", "label": "Retest Zone"})

    return overlays


# =========================================================
# SCALPING
# =========================================================
def _scalping_overlays(df: pd.DataFrame, ai_result: dict, lookback: int = 15) -> list:
    n = len(df)
    seg = df.iloc[max(0, n - lookback):n]
    micro_hi, micro_lo = seg['high'].max(), seg['low'].min()

    overlays = [
        {"kind": "hline", "i0": n - lookback, "i1": "end", "p0": micro_hi,
         "color": RED, "style": "dashed", "label": "Micro Resistance"},
        {"kind": "hline", "i0": n - lookback, "i1": "end", "p0": micro_lo,
         "color": GREEN, "style": "dashed", "label": "Micro Support"},
    ]

    entry = ai_result.get("entry", 0.0)
    tp = ai_result.get("tp", 0.0)
    band = df['close'].iloc[-1] * 0.0008
    if entry:
        overlays.append({"kind": "zone", "i0": max(0, n - 3), "i1": "end",
                          "p0": entry - band, "p1": entry + band,
                          "color": BLUE, "style": "fill", "label": "Entry Zone"})
    if tp:
        overlays.append({"kind": "zone", "i0": max(0, n - 3), "i1": "end",
                          "p0": tp - band, "p1": tp + band,
                          "color": CYAN, "style": "fill", "label": "Exit Zone"})

    return overlays


# =========================================================
# UNIVERSAL RISK / REWARD BOX
# =========================================================
def _risk_reward_box(df: pd.DataFrame, ai_result: dict) -> list:
    entry = ai_result.get("entry", 0.0)
    sl = ai_result.get("sl", 0.0)
    tp = ai_result.get("tp", 0.0)
    if not entry or not sl or not tp:
        return []

    n = len(df)
    i0 = max(0, n - 6)
    rr = ai_result.get("rr", 0.0)
    return [
        {"kind": "zone", "i0": i0, "i1": "end", "p0": min(entry, sl), "p1": max(entry, sl),
         "color": RED, "style": "fill", "label": "Risk"},
        {"kind": "zone", "i0": i0, "i1": "end", "p0": min(entry, tp), "p1": max(entry, tp),
         "color": GREEN, "style": "fill", "label": f"Reward  R:R 1:{rr:.1f}" if rr else "Reward"},
    ]
