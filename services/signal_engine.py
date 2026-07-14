"""
services/signal_engine.py
===========================
AI Signal Engine -- multi-timeframe, multi-confirmation trade signal
generation, sitting alongside (not replacing) the existing single-
timeframe strategy dropdown in services/ai_engine.py.

Standard pipeline per symbol:
  1. Trend        (4H + 1H)   -- EMA20/EMA50/SMA200 + ADX direction, must agree
  2. Setup        (15M)       -- Smart Money Concepts pattern aligned with the trend
  3. Entry        (5M + 1M)   -- momentum / structure confirmation in the same direction
  4. Confluence scoring across every technical + SMC confirmation
  5. ATR-based Entry / Stop Loss / TP1 / TP2 / TP3 / Risk-Reward
  6. Trade-type classification (Scalping / Intraday / Swing)

Scan-mode pipeline (added for Manual Scanner timeframe selector):
  Each mode shifts ALL timeframes down proportionally so the pipeline
  stays structurally identical but targets a different trading horizon.

No signal is produced unless enough real confirmations agree
(config.settings.SIGNAL_MIN_CONFLUENCE) and confidence clears
config.settings.SIGNAL_MIN_CONFIDENCE. Every number in the output is
computed from real OHLC candle data returned by
services/crypto_service.CryptoService.fetch_market_data() -- nothing in
this file invents a price, indicator value, or confirmation.
"""

from datetime import datetime, timezone
from typing import Optional

from config import settings
from models.signal_model import Signal
from services import smc_analysis
from services.notification_center import nc
from utils.logger import logger


# ── Crypto price floor guard (protects against wrong MT5 demo prices) ───────
# If a symbol's candle-close price is below these floors, it almost certainly
# came from a misconfigured broker symbol (e.g. BTC showing $28 on an MT5 demo).
# In that case signal generation is skipped for that symbol.
_SIGNAL_PRICE_FLOORS: dict = {
    "BTC":  5_000.0,
    "ETH":    100.0,
    "BNB":      5.0,
    "SOL":      0.5,
    "XRP":      0.01,
}


def _signal_price_ok(symbol: str, price: float) -> bool:
    """Return False if price looks like demo/test data for known coins."""
    if price <= 0:
        return False
    base = symbol.upper().split("/")[0].replace("USDT", "").replace("USD", "")
    floor = _SIGNAL_PRICE_FLOORS.get(base)
    if floor and price < floor:
        logger.warning(
            f"[SignalEngine] Skipping signal for {symbol}: candle close {price:.4f} "
            f"is below price floor {floor:.2f}. This usually means your MT5 broker "
            f"uses a different symbol name for this asset (e.g. 'BTCUSD' vs 'BTCUSDm'). "
            f"Go to Settings → Data Feed → switch to Default (Free) for correct crypto prices."
        )
        return False
    return True


# ── Scan modes: each defines the three pipeline layers ─────────────────────
# Format: { mode_label: (trend_tfs, setup_tf, entry_tfs, sl_atr_mult, tp_mults) }
# Shorter timeframes use tighter SL (smaller ATR multiple) and faster TP targets.
SCAN_MODES = {
    # ── Swing / Position ────────────────────────────────────────────────────
    "Swing (1D/4H)": (
        ["1d", "4h"],   # trend timeframes
        "1h",           # setup timeframe
        ["30m", "15m"], # entry timeframes
        2.0,            # SL ATR multiple (wider — swing trades need room)
        (1.5, 3.0, 5.0),# TP multiples (TP1, TP2, TP3)
    ),
    # ── Standard / Intraday (default) ───────────────────────────────────────
    "Intraday (4H/1H)": (
        ["4h", "1h"],
        "15m",
        ["5m", "1m"],
        1.5,
        (1.0, 2.0, 3.0),
    ),
    # ── Scalping 30M ────────────────────────────────────────────────────────
    "Scalp (1H/30M)": (
        ["1h", "30m"],
        "5m",
        ["1m", "1m"],   # both entry frames on 1m for tight scalp timing
        1.2,
        (0.8, 1.5, 2.5),
    ),
    # ── Scalping 15M ────────────────────────────────────────────────────────
    "Scalp (30M/15M)": (
        ["30m", "15m"],
        "5m",
        ["1m", "1m"],
        1.0,
        (0.7, 1.2, 2.0),
    ),
    # ── Scalping 5M ─────────────────────────────────────────────────────────
    "Scalp (15M/5M)": (
        ["15m", "5m"],
        "1m",
        ["1m", "1m"],
        0.8,
        (0.6, 1.0, 1.5),
    ),
    # ── Micro-scalp 1M ──────────────────────────────────────────────────────
    "Micro-Scalp (5M/1M)": (
        ["5m", "1m"],
        "1m",
        ["1m", "1m"],
        0.6,
        (0.5, 0.8, 1.2),
    ),
}

# Default mode key used when calling analyze() with no mode argument
DEFAULT_SCAN_MODE = "Intraday (4H/1H)"

# Reduced confluence requirement for fast scalp modes
_SCALP_MIN_CONFLUENCE = 3   # standard is 4 — scalp has fewer higher-TF confirmations


class SignalEngine:
    def __init__(self, crypto_service, market_analyzer):
        self.crypto_service = crypto_service
        self.market_analyzer = market_analyzer

    # ------------------------------------------------------------------
    # Public entrypoints
    # ------------------------------------------------------------------
    def analyze(self, symbol: str) -> Optional[Signal]:
        """Standard pipeline — uses default Intraday (4H/1H) timeframes."""
        return self.analyze_with_mode(symbol, DEFAULT_SCAN_MODE)

    def analyze_with_mode(self, symbol: str, mode: str) -> Optional[Signal]:
        """
        Full multi-timeframe pipeline with a selectable scan mode.
        mode -- one of the keys in SCAN_MODES (e.g. 'Scalp (1H/30M)').
        Falls back to DEFAULT_SCAN_MODE if the key is unknown.
        """
        cfg = SCAN_MODES.get(mode, SCAN_MODES[DEFAULT_SCAN_MODE])
        trend_tfs, setup_tf, entry_tfs, sl_atr_mult, tp_mults = cfg

        is_scalp = "Scalp" in mode or "Micro" in mode
        min_confluence = _SCALP_MIN_CONFLUENCE if is_scalp else settings.SIGNAL_MIN_CONFLUENCE

        try:
            frames = self._fetch_timeframes(symbol, trend_tfs, setup_tf, entry_tfs)
        except Exception as e:
            logger.warning(f"[SignalEngine/{mode}] data fetch failed for {symbol}: {e}")
            return None

        if any(f is None or f.empty or len(f) < 20 for f in frames.values()):
            return None

        indicators = {tf: self.market_analyzer.calculate_indicators(df) for tf, df in frames.items()}
        smc_data   = {tf: smc_analysis.analyze_smc(df) for tf, df in indicators.items()}

        trend = self._read_trend_tfs(indicators, smc_data, trend_tfs)
        if trend["bias"] == "neutral":
            return None

        setup        = self._read_setup(indicators[setup_tf], smc_data[setup_tf], trend["bias"])
        entry_confirm = self._read_entry_tfs(indicators, smc_data, trend["bias"], entry_tfs)

        confirmations   = trend["reasons"] + setup["reasons"] + entry_confirm["reasons"]
        confluence_count = trend["score"]  + setup["score"]  + entry_confirm["score"]

        if confluence_count < min_confluence:
            return None

        max_possible = len(trend_tfs) + 5 + (4 * len(set(entry_tfs)))
        confidence   = int(round(min(1.0, (confluence_count / max(max_possible, 1)) * 1.35) * 100))
        confidence   = max(0, min(100, confidence))

        if confidence < settings.SIGNAL_MIN_CONFIDENCE:
            return None

        direction    = "BUY" if trend["bias"] == "bullish" else "SELL"
        entry_tf_df  = indicators[entry_tfs[0]]
        current_price = float(entry_tf_df["close"].iloc[-1])
        if not _signal_price_ok(symbol, current_price):
            return None  # Bad price from provider (e.g. MT5 demo BTC=$28) — skip signal

        # FIX (2026-07-13): When MT5 is the chart provider, the candle close
        # price may still be from the broker's demo feed (even after the floor
        # check above).  Cross-check against the Binance PriceFeed which always
        # fetches real market prices via the public REST API.  If the PriceFeed
        # has a sane price we use it as the entry so Entry/SL/TP are correct.
        try:
            from services import price_feed as _pf
            if _pf._feed is not None:
                pf_price = _pf._feed.get_price_for_pnl(symbol)
                if pf_price and _signal_price_ok(symbol, pf_price):
                    # Only override if difference > 0.1% (avoids overriding
                    # valid near-identical prices from different candle closes)
                    if abs(pf_price - current_price) / max(current_price, 1e-9) > 0.001:
                        logger.debug(
                            f"[SignalEngine] {symbol}: replacing candle close "
                            f"{current_price:.6f} with Binance feed price "
                            f"{pf_price:.6f} for signal entry."
                        )
                        current_price = pf_price
        except Exception:
            pass
        setup_atr    = float(indicators[setup_tf]["ATR"].iloc[-1])
        if not setup_atr or setup_atr != setup_atr:
            return None

        levels     = self._build_levels_custom(direction, current_price, setup_atr, sl_atr_mult, tp_mults)
        trade_type = self._classify_from_mode(mode)
        strength   = self._strength_label(confidence)
        provider   = self.crypto_service.get_connection_status().get("broker") or "Unavailable"

        signal = Signal(
            symbol=symbol,
            direction=direction,
            entry_price=current_price,
            current_price=current_price,
            stop_loss=levels["sl"],
            take_profit_1=levels["tp1"],
            take_profit_2=levels["tp2"],
            take_profit_3=levels["tp3"],
            risk_reward=levels["rr"],
            confidence=confidence,
            strength=strength,
            trend="Bullish" if trend["bias"] == "bullish" else "Bearish",
            setup_timeframe=setup_tf.upper(),
            trade_type=trade_type,
            data_source=provider,
            session=self._current_session(),
            reasons=confirmations,
        )

        try:
            nc.push(
                "signal",
                title=f"AI Signal [{trade_type}]: {symbol}",
                message=f"{direction} · {confidence}% · {setup_tf.upper()} setup",
                level="info",
            )
        except Exception:
            pass

        return signal

    # ------------------------------------------------------------------
    # (legacy wrapper — keeps the original pipeline intact for the
    #  auto market scanner which calls analyze() with no mode arg)
    # ------------------------------------------------------------------
    def _run_legacy_pipeline(self, symbol: str) -> Optional[Signal]:
        """Original fixed-timeframe pipeline — called by analyze()."""
        try:
            frames = self._fetch_all_timeframes(symbol)
        except Exception as e:
            logger.warning(f"[SignalEngine] data fetch failed for {symbol}: {e}")
            return None

        if any(f is None or f.empty or len(f) < 30 for f in frames.values()):
            return None  # not enough real candle data yet on one or more timeframes

        indicators = {tf: self.market_analyzer.calculate_indicators(df) for tf, df in frames.items()}
        smc = {tf: smc_analysis.analyze_smc(df) for tf, df in indicators.items()}

        trend = self._read_trend(indicators, smc)
        if trend["bias"] == "neutral":
            return None  # higher timeframes disagree or show no clear trend -- stay out

        setup = self._read_setup(indicators[settings.SIGNAL_SETUP_TIMEFRAME], smc[settings.SIGNAL_SETUP_TIMEFRAME], trend["bias"])
        entry_confirm = self._read_entry_confirmation(indicators, smc, trend["bias"])

        confirmations = trend["reasons"] + setup["reasons"] + entry_confirm["reasons"]
        confluence_count = trend["score"] + setup["score"] + entry_confirm["score"]

        if confluence_count < settings.SIGNAL_MIN_CONFLUENCE:
            return None  # avoid forcing a signal in poor/ambiguous conditions

        confidence = self._score_confidence(confluence_count, trend, setup, entry_confirm)
        if confidence < settings.SIGNAL_MIN_CONFIDENCE:
            return None

        direction = "BUY" if trend["bias"] == "bullish" else "SELL"
        entry_tf_df = indicators[settings.SIGNAL_ENTRY_TIMEFRAMES[0]]
        current_price = float(entry_tf_df['close'].iloc[-1])
        if not _signal_price_ok(symbol, current_price):
            return None  # Bad price from provider (e.g. MT5 demo BTC=$28) — skip signal
        setup_atr = float(indicators[settings.SIGNAL_SETUP_TIMEFRAME]['ATR'].iloc[-1])
        if not setup_atr or setup_atr != setup_atr:  # NaN / zero guard
            return None

        levels = self._build_levels(direction, current_price, setup_atr)
        trade_type = self._classify_trade_type(indicators)
        strength = self._strength_label(confidence)
        provider_name = self.crypto_service.get_connection_status().get("broker") or "Unavailable"

        signal = Signal(
            symbol=symbol,
            direction=direction,
            entry_price=current_price,
            current_price=current_price,
            stop_loss=levels["sl"],
            take_profit_1=levels["tp1"],
            take_profit_2=levels["tp2"],
            take_profit_3=levels["tp3"],
            risk_reward=levels["rr"],
            confidence=confidence,
            strength=strength,
            trend="Bullish" if trend["bias"] == "bullish" else "Bearish",
            setup_timeframe=settings.SIGNAL_SETUP_TIMEFRAME.upper(),
            trade_type=trade_type,
            data_source=provider_name,
            session=self._current_session(),
            reasons=confirmations,
        )

        # Safe Notification Trigger (Insulated to prevent core logic failure)
        try:
            nc.push(
                "signal",
                title=f"AI Signal: {symbol}",
                message=f"{direction} setup detected — {confidence}% confluence.",
                level="info",
            )
        except Exception as notify_err:
            logger.warning(f"[SignalEngine] Alert delivery skipped safely: {notify_err}")

        return signal

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def _fetch_all_timeframes(self, symbol: str) -> dict:
        needed = list(dict.fromkeys(
            settings.SIGNAL_TREND_TIMEFRAMES + [settings.SIGNAL_SETUP_TIMEFRAME] + settings.SIGNAL_ENTRY_TIMEFRAMES
        ))
        return {tf: self.crypto_service.fetch_market_data(symbol, tf) for tf in needed}

    def _fetch_timeframes(self, symbol: str, trend_tfs: list, setup_tf: str, entry_tfs: list) -> dict:
        """Generic fetch for any timeframe combination."""
        needed = list(dict.fromkeys(trend_tfs + [setup_tf] + entry_tfs))
        return {tf: self.crypto_service.fetch_market_data(symbol, tf) for tf in needed}

    # ------------------------------------------------------------------
    # Mode-aware wrappers for trend and entry reads
    # ------------------------------------------------------------------
    def _read_trend_tfs(self, indicators: dict, smc: dict, trend_tfs: list) -> dict:
        """Read trend from an arbitrary list of trend timeframes."""
        biases, reasons, score = [], [], 0
        for tf in trend_tfs:
            if tf not in indicators:
                continue
            row  = indicators[tf].iloc[-1]
            bias = "neutral"
            if row["EMA20"] > row["EMA50"] and row["close"] > row["SMA200"]:
                bias = "bullish"
            elif row["EMA20"] < row["EMA50"] and row["close"] < row["SMA200"]:
                bias = "bearish"
            biases.append(bias)
            if bias != "neutral" and row.get("ADX", 0) >= 15:
                reasons.append(
                    f"{tf.upper()} trend: EMA20/EMA50/SMA200 aligned {bias} "
                    f"with ADX {row['ADX']:.1f} confirming trend strength."
                )
                score += 1
        if len(set(biases)) == 1 and biases[0] != "neutral":
            return {"bias": biases[0], "reasons": reasons, "score": score}
        return {"bias": "neutral", "reasons": [], "score": 0}

    def _read_entry_tfs(self, indicators: dict, smc: dict, trend_bias: str, entry_tfs: list) -> dict:
        """Read entry confirmations from an arbitrary list of entry timeframes."""
        reasons, score = [], 0
        wants = "bullish" if trend_bias == "bullish" else "bearish"
        for tf in list(dict.fromkeys(entry_tfs)):   # deduplicate
            if tf not in indicators:
                continue
            row   = indicators[tf].iloc[-1]
            facts = smc.get(tf, {})
            if (row["MOMENTUM"] > 0) if wants == "bullish" else (row["MOMENTUM"] < 0):
                reasons.append(f"{tf.upper()} entry: momentum confirms {wants} pressure.")
                score += 1
            if facts.get("bos") == wants or facts.get("choch") == wants:
                reasons.append(f"{tf.upper()} entry: structure broke {wants}, timing the entry.")
                score += 1
            vol_ma = row.get("VOLUME_MA20", 0)
            if vol_ma and row["volume"] > vol_ma:
                reasons.append(f"{tf.upper()} entry: volume above its 20-period MA.")
                score += 1
            rsi = row.get("RSI", 50)
            if wants == "bullish" and 40 <= rsi <= 72:
                reasons.append(f"{tf.upper()} entry: RSI {rsi:.1f} — bullish momentum, not overbought.")
                score += 1
            elif wants == "bearish" and 28 <= rsi <= 60:
                reasons.append(f"{tf.upper()} entry: RSI {rsi:.1f} — bearish momentum, not oversold.")
                score += 1
        return {"reasons": reasons, "score": score}

    def _build_levels_custom(self, direction: str, price: float, atr: float,
                              sl_atr_mult: float, tp_mults: tuple) -> dict:
        """Build SL/TP levels with mode-specific ATR multiples."""
        sl_dist = atr * sl_atr_mult
        m1, m2, m3 = tp_mults
        if direction == "BUY":
            sl  = price - sl_dist
            tp1 = price + sl_dist * m1
            tp2 = price + sl_dist * m2
            tp3 = price + sl_dist * m3
        else:
            sl  = price + sl_dist
            tp1 = price - sl_dist * m1
            tp2 = price - sl_dist * m2
            tp3 = price - sl_dist * m3
        return {"sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "rr": round(m2, 2)}

    def _classify_from_mode(self, mode: str) -> str:
        """Map a scan mode name to a trade-type label."""
        if "Micro" in mode:
            return "Micro-Scalp"
        if "Scalp" in mode:
            return "Scalping"
        if "Swing" in mode:
            return "Swing"
        return "Intraday"

    # ------------------------------------------------------------------
    # Step 1: Trend (higher timeframes) — original fixed-TF version
    # ------------------------------------------------------------------
    def _read_trend(self, indicators: dict, smc: dict) -> dict:
        biases, reasons, score = [], [], 0
        for tf in settings.SIGNAL_TREND_TIMEFRAMES:
            row = indicators[tf].iloc[-1]
            bias = "neutral"
            if row['EMA20'] > row['EMA50'] and row['close'] > row['SMA200']:
                bias = "bullish"
            elif row['EMA20'] < row['EMA50'] and row['close'] < row['SMA200']:
                bias = "bearish"
            biases.append(bias)
            if bias != "neutral" and row.get('ADX', 0) >= 18:
                reasons.append(f"{tf.upper()} trend: EMA20/EMA50/SMA200 aligned {bias} with ADX {row['ADX']:.1f} confirming trend strength.")
                score += 1

        if len(set(biases)) == 1 and biases[0] != "neutral":
            return {"bias": biases[0], "reasons": reasons, "score": score}
        return {"bias": "neutral", "reasons": [], "score": 0}

    # ------------------------------------------------------------------
    # Step 2: Setup (mid timeframe -- Smart Money Concepts)
    # ------------------------------------------------------------------
    def _read_setup(self, df, facts: dict, trend_bias: str) -> dict:
        reasons, score = [], 0
        wants = "bullish" if trend_bias == "bullish" else "bearish"

        if facts.get("order_block") == wants:
            reasons.append(f"{settings.SIGNAL_SETUP_TIMEFRAME.upper()} setup: price retested a {wants} order block aligned with the higher-timeframe trend.")
            score += 1
        if facts.get("fvg") == wants:
            reasons.append(f"{settings.SIGNAL_SETUP_TIMEFRAME.upper()} setup: an unfilled {wants} Fair Value Gap sits in the trend direction.")
            score += 1
        if facts.get("liquidity_sweep") == wants:
            reasons.append(f"{settings.SIGNAL_SETUP_TIMEFRAME.upper()} setup: a liquidity sweep just reversed back in the {wants} direction.")
            score += 1
        if facts.get("zone") == ("discount" if wants == "bullish" else "premium"):
            reasons.append(f"{settings.SIGNAL_SETUP_TIMEFRAME.upper()} setup: price sits in the {facts['zone']} zone of its recent range, favouring {wants} entries.")
            score += 1
        if facts.get("bos") == wants:
            reasons.append(f"{settings.SIGNAL_SETUP_TIMEFRAME.upper()} setup: Break of Structure confirms continuation to the {wants} side.")
            score += 1

        return {"reasons": reasons, "score": score}

    # ------------------------------------------------------------------
    # Step 3: Entry confirmation (lower timeframes)
    # ------------------------------------------------------------------
    def _read_entry_confirmation(self, indicators: dict, smc: dict, trend_bias: str) -> dict:
        reasons, score = [], 0
        wants = "bullish" if trend_bias == "bullish" else "bearish"

        for tf in settings.SIGNAL_ENTRY_TIMEFRAMES:
            row = indicators[tf].iloc[-1]
            facts = smc[tf]

            momentum_ok = (row['MOMENTUM'] > 0) if wants == "bullish" else (row['MOMENTUM'] < 0)
            if momentum_ok:
                reasons.append(f"{tf.upper()} entry: momentum confirms {wants} pressure into the current candle.")
                score += 1

            if facts.get("bos") == wants or facts.get("choch") == wants:
                reasons.append(f"{tf.upper()} entry: structure just broke {wants}, timing the entry.")
                score += 1

            volume_ok = row['volume'] > row.get('VOLUME_MA20', 0) if row.get('VOLUME_MA20', 0) else False
            if volume_ok:
                reasons.append(f"{tf.upper()} entry: volume is above its 20-period average, supporting the move.")
                score += 1

            parent_rsi = row.get('RSI', 50)
            if wants == "bullish" and 45 <= parent_rsi <= 70:
                reasons.append(f"{tf.upper()} entry: RSI at {parent_rsi:.1f} shows bullish momentum without being overbought.")
                score += 1
            elif wants == "bearish" and 30 <= parent_rsi <= 55:
                reasons.append(f"{tf.upper()} entry: RSI at {parent_rsi:.1f} shows bearish momentum without being oversold.")
                score += 1

        return {"reasons": reasons, "score": score}

    # ------------------------------------------------------------------
    # Confidence / strength
    # ------------------------------------------------------------------
    def _score_confidence(self, confluence_count: int, trend: dict, setup: dict, entry_confirm: dict) -> int:
        max_possible = 2 + 5 + (4 * len(settings.SIGNAL_ENTRY_TIMEFRAMES))
        raw = confluence_count / max_possible
        confidence = int(round(min(1.0, raw * 1.35) * 100))
        return max(0, min(100, confidence))

    def _strength_label(self, confidence: int) -> str:
        if confidence >= 90:
            return "Very Strong"
        if confidence >= 80:
            return "Strong"
        if confidence >= 70:
            return "Moderate"
        return "Weak"

    # ------------------------------------------------------------------
    # Trade levels
    # ------------------------------------------------------------------
    def _build_levels(self, direction: str, price: float, atr: float) -> dict:
        sl_distance = atr * settings.SIGNAL_SL_ATR_MULTIPLE
        m1, m2, m3 = settings.SIGNAL_TP_MULTIPLES
        if direction == "BUY":
            sl = price - sl_distance
            tp1, tp2, tp3 = price + sl_distance * m1, price + sl_distance * m2, price + sl_distance * m3
        else:
            sl = price + sl_distance
            tp1, tp2, tp3 = price - sl_distance * m1, price - sl_distance * m2, price - sl_distance * m3
        rr = round(m2, 2)  # uses TP2 as the primary target
        return {"sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "rr": rr}

    # ------------------------------------------------------------------
    # Trade type classification
    # ------------------------------------------------------------------
    def _classify_trade_type(self, indicators: dict) -> str:
        entry_tf = settings.SIGNAL_ENTRY_TIMEFRAMES[0]
        trend_tf = settings.SIGNAL_TREND_TIMEFRAMES[0]

        price = float(indicators[entry_tf]['close'].iloc[-1]) or 1e-9
        entry_atr_pct = float(indicators[entry_tf]['ATR'].iloc[-1]) / price
        trend_atr_pct = float(indicators[trend_tf]['ATR'].iloc[-1]) / price

        if trend_atr_pct > 0 and entry_atr_pct / trend_atr_pct < 0.12:
            return "Scalping"
        if trend_atr_pct > 0 and entry_atr_pct / trend_atr_pct > 0.35:
            return "Swing"
        return "Intraday"

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------
    def _current_session(self) -> str:
        hour = datetime.now(timezone.utc).hour
        tokyo = 0 <= hour < 9
        london = 8 <= hour < 17
        new_york = 13 <= hour < 22
        if london and new_york:
            return "London / New York overlap"
        if london:
            return "London session"
        if new_york:
            return "New York session"
        if tokyo:
            return "Tokyo session"
        return "Outside major sessions"