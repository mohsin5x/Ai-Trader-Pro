"""
services/signal_explainer.py
==============================
Detailed signal analysis and explanation engine.

For every symbol, this produces:
  - BUY / SELL / WAIT signal with full reasoning
  - For WAIT: exactly which conditions FAILED and why
  - All SMC/ICT concepts: Order Blocks, FVG, Liquidity, BOS, CHoCH
  - Technical: EMA, MACD, RSI, Bollinger, ADX, Stochastic, Volume
  - Support/Resistance levels
  - Entry, SL, TP1-TP3, Risk/Reward, Confidence score

Used by:
  - ManualScannerPage  (Explain button)
  - CryptoSignalPage   (new dedicated page)
  - SignalEnginePanel  (AI explanation overlay)
"""
from __future__ import annotations

from typing import Optional
import time

from config import settings
from models.signal_model import Signal
from services import smc_analysis
from services.signal_engine import SCAN_MODES, DEFAULT_SCAN_MODE
from utils.logger import logger


def _pct(a: float, b: float) -> float:
    if not b:
        return 0.0
    return (a - b) / b * 100.0


class SignalExplainer:
    """
    Produces a detailed, human-readable explanation of the current market
    conditions for any symbol+timeframe combination.

    Returns a dict with keys:
      signal         – "BUY" / "SELL" / "WAIT"
      confidence     – 0-100
      entry          – price (0 for WAIT)
      stop_loss      – price (0 for WAIT)
      take_profit_1  – price (0 for WAIT)
      take_profit_2  – price
      take_profit_3  – price
      risk_reward    – float
      trend          – "Bullish" / "Bearish" / "Neutral"
      session        – string
      confirmations  – list[str]  (what passed)
      failures       – list[str]  (what failed / why WAIT)
      summary        – str        (one-paragraph plain English)
      smc_analysis   – dict       (raw SMC facts for all TFs)
      timeframes     – dict       (TF → last indicator row dict)
      support        – float
      resistance     – float
    """

    def __init__(self, crypto_service, market_analyzer):
        self.crypto_service  = crypto_service
        self.market_analyzer = market_analyzer

    def explain(self, symbol: str, mode: str = DEFAULT_SCAN_MODE) -> dict:
        """Full pipeline analysis with detailed pass/fail reasoning."""
        cfg = SCAN_MODES.get(mode, SCAN_MODES[DEFAULT_SCAN_MODE])
        trend_tfs, setup_tf, entry_tfs, sl_atr_mult, tp_mults = cfg

        confirmations: list[str] = []
        failures:      list[str] = []

        # ── 1. Fetch data ──────────────────────────────────────────────
        needed = list(dict.fromkeys(trend_tfs + [setup_tf] + entry_tfs))
        frames = {}
        for tf in needed:
            try:
                df = self.crypto_service.fetch_market_data(symbol, tf)
                frames[tf] = df
            except Exception as e:
                failures.append(f"Data fetch failed for {tf.upper()}: {e}")

        if not frames:
            return self._wait_result(symbol, failures, "No market data available.")

        # Check data adequacy
        for tf, df in frames.items():
            if df is None or df.empty:
                failures.append(f"{tf.upper()}: No candle data returned from provider.")
            elif len(df) < 20:
                failures.append(f"{tf.upper()}: Only {len(df)} candles available — need 20+ for reliable indicators.")

        frames = {tf: df for tf, df in frames.items() if df is not None and not df.empty and len(df) >= 20}
        if not frames:
            return self._wait_result(symbol, failures, "Insufficient candle data across all timeframes.")

        # ── 2. Calculate indicators ───────────────────────────────────
        indicators = {}
        smc_data   = {}
        for tf, df in frames.items():
            try:
                ind = self.market_analyzer.calculate_indicators(df)
                indicators[tf] = ind
                smc_data[tf]   = smc_analysis.analyze_smc(ind)
            except Exception as e:
                failures.append(f"{tf.upper()} indicator calculation failed: {e}")

        if not indicators:
            return self._wait_result(symbol, failures, "Indicator calculation failed.")

        current_price = 0.0
        for tf in entry_tfs:
            if tf in indicators:
                current_price = float(indicators[tf]["close"].iloc[-1])
                break
        if not current_price:
            for tf in indicators:
                current_price = float(indicators[tf]["close"].iloc[-1])
                break

        # ── 3. Support & Resistance ───────────────────────────────────
        support, resistance = self._calc_sr(indicators, setup_tf, trend_tfs)

        # ── 4. Trend analysis (higher timeframes) ─────────────────────
        trend_result = self._analyze_trend(
            indicators, smc_data, trend_tfs, confirmations, failures
        )
        trend_bias = trend_result["bias"]

        # ── 5. Setup analysis (mid timeframe) ─────────────────────────
        setup_result = {"score": 0, "reasons": []}
        if trend_bias != "neutral" and setup_tf in indicators:
            setup_result = self._analyze_setup(
                indicators[setup_tf], smc_data.get(setup_tf, {}),
                trend_bias, setup_tf, confirmations, failures
            )

        # ── 6. Entry timing (lower timeframes) ───────────────────────
        entry_result = {"score": 0, "reasons": []}
        if trend_bias != "neutral":
            entry_result = self._analyze_entry(
                indicators, smc_data, trend_bias, entry_tfs, confirmations, failures
            )

        # ── 7. Confluence scoring ─────────────────────────────────────
        total_score = trend_result["score"] + setup_result["score"] + entry_result["score"]
        is_scalp = "Scalp" in mode or "Micro" in mode
        min_confluence = 3 if is_scalp else settings.SIGNAL_MIN_CONFLUENCE

        if trend_bias == "neutral":
            failures.append(
                "TREND: Higher timeframes show conflicting or neutral bias — "
                "trend agreement required for a signal."
            )

        if total_score < min_confluence:
            failures.append(
                f"CONFLUENCE: Only {total_score}/{min_confluence} confirmations met. "
                f"Need at least {min_confluence} independent technical + SMC agreements."
            )

        # ── 8. Confidence ─────────────────────────────────────────────
        max_possible = len(trend_tfs) + 5 + (4 * len(set(entry_tfs)))
        confidence = int(round(min(1.0, (total_score / max(max_possible, 1)) * 1.35) * 100))
        confidence = max(0, min(100, confidence))

        if confidence < settings.SIGNAL_MIN_CONFIDENCE:
            failures.append(
                f"CONFIDENCE: {confidence}% is below the minimum threshold of "
                f"{settings.SIGNAL_MIN_CONFIDENCE}%. More confirming conditions needed."
            )

        # ── 9. Build result ────────────────────────────────────────────
        if (trend_bias != "neutral" and total_score >= min_confluence
                and confidence >= settings.SIGNAL_MIN_CONFIDENCE):

            direction = "BUY" if trend_bias == "bullish" else "SELL"
            # ATR for levels
            setup_atr = 1e-5
            if setup_tf in indicators:
                setup_atr = float(indicators[setup_tf]["ATR"].iloc[-1])
            if not setup_atr or setup_atr != setup_atr:
                setup_atr = 1e-5

            sl_dist = setup_atr * sl_atr_mult
            m1, m2, m3 = tp_mults
            if direction == "BUY":
                sl  = current_price - sl_dist
                tp1 = current_price + sl_dist * m1
                tp2 = current_price + sl_dist * m2
                tp3 = current_price + sl_dist * m3
            else:
                sl  = current_price + sl_dist
                tp1 = current_price - sl_dist * m1
                tp2 = current_price - sl_dist * m2
                tp3 = current_price - sl_dist * m3

            rr = round(m2, 2)
            trend_label = "Bullish" if trend_bias == "bullish" else "Bearish"
            summary = self._build_summary(
                symbol, direction, confidence, trend_label,
                current_price, sl, tp1, tp2, rr, confirmations, mode
            )

            return {
                "signal":        direction,
                "confidence":    confidence,
                "entry":         current_price,
                "stop_loss":     sl,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "risk_reward":   rr,
                "trend":         trend_label,
                "session":       self._session(),
                "confirmations": confirmations,
                "failures":      failures,
                "summary":       summary,
                "smc_analysis":  {tf: dict(v) for tf, v in smc_data.items()},
                "timeframes":    {tf: indicators[tf].iloc[-1].to_dict() for tf in indicators},
                "support":       support,
                "resistance":    resistance,
                "mode":          mode,
                "symbol":        symbol,
                "timestamp":     time.time(),
            }
        else:
            summary = self._build_wait_summary(symbol, trend_bias, failures, confirmations)
            return self._wait_result(symbol, failures, summary,
                                     confirmations=confirmations,
                                     confidence=confidence,
                                     trend=trend_bias,
                                     smc_data=smc_data,
                                     indicators=indicators,
                                     support=support,
                                     resistance=resistance,
                                     mode=mode)

    # ── Trend analysis ─────────────────────────────────────────────────
    def _analyze_trend(self, indicators, smc_data, trend_tfs, confirmations, failures):
        biases, score = [], 0
        reasons = []
        for tf in trend_tfs:
            if tf not in indicators:
                failures.append(f"TREND ({tf.upper()}): No data available.")
                continue
            row = indicators[tf].iloc[-1]
            ema20  = row.get("EMA20",  0)
            ema50  = row.get("EMA50",  0)
            sma200 = row.get("SMA200", 0)
            close  = row.get("close",  0)
            adx    = row.get("ADX",    0)
            rsi    = row.get("RSI",    50)
            macd   = row.get("MACD",   0)
            macd_s = row.get("MACD_Signal", 0)

            bias = "neutral"
            if ema20 > ema50 and close > sma200:
                bias = "bullish"
                reason = (
                    f"{tf.upper()} TREND BULLISH: EMA20 ({ema20:.4f}) > EMA50 ({ema50:.4f}) "
                    f"and price ({close:.4f}) above SMA200 ({sma200:.4f})."
                )
                if adx >= 20:
                    reason += f" ADX {adx:.1f} confirms strong trend."
                    score += 1
                    reasons.append(reason)
                    confirmations.append(reason)
                elif adx >= 15:
                    reason += f" ADX {adx:.1f} shows moderate trend strength."
                    score += 1
                    reasons.append(reason)
                    confirmations.append(reason)
                else:
                    failures.append(
                        f"TREND ({tf.upper()}): Bullish alignment detected but ADX {adx:.1f} "
                        f"is weak (<15) — trend may be choppy."
                    )
            elif ema20 < ema50 and close < sma200:
                bias = "bearish"
                reason = (
                    f"{tf.upper()} TREND BEARISH: EMA20 ({ema20:.4f}) < EMA50 ({ema50:.4f}) "
                    f"and price ({close:.4f}) below SMA200 ({sma200:.4f})."
                )
                if adx >= 20:
                    reason += f" ADX {adx:.1f} confirms strong downtrend."
                    score += 1
                    reasons.append(reason)
                    confirmations.append(reason)
                elif adx >= 15:
                    reason += f" ADX {adx:.1f} shows moderate trend."
                    score += 1
                    reasons.append(reason)
                    confirmations.append(reason)
                else:
                    failures.append(
                        f"TREND ({tf.upper()}): Bearish alignment detected but ADX {adx:.1f} "
                        f"is weak (<15)."
                    )
            else:
                bias = "neutral"
                ema_rel = "above" if ema20 > ema50 else "below"
                price_rel = "above" if close > sma200 else "below"
                failures.append(
                    f"TREND ({tf.upper()}): EMAs and price NOT fully aligned. "
                    f"EMA20 is {ema_rel} EMA50, but price is {price_rel} SMA200. "
                    f"Mixed signals — no clear directional bias."
                )

            # MACD confirmation
            if bias != "neutral":
                if (bias == "bullish" and macd > macd_s) or (bias == "bearish" and macd < macd_s):
                    msg = f"{tf.upper()} MACD {'above' if macd > macd_s else 'below'} signal line — confirms {bias} momentum."
                    confirmations.append(msg)
                    reasons.append(msg)
                else:
                    failures.append(
                        f"TREND ({tf.upper()}): MACD diverges from trend direction "
                        f"(MACD={macd:.6f}, Signal={macd_s:.6f})."
                    )

            biases.append(bias)

        # All trend TFs must agree
        if len(set(biases)) == 1 and biases[0] != "neutral":
            return {"bias": biases[0], "score": score, "reasons": reasons}
        elif biases:
            unique = set(biases)
            if "bullish" in unique and "bearish" in unique:
                failures.append(
                    f"TREND CONFLICT: Higher timeframes disagree — "
                    f"one shows bullish, another bearish. Cannot confirm direction."
                )
            return {"bias": "neutral", "score": 0, "reasons": []}
        return {"bias": "neutral", "score": 0, "reasons": []}

    # ── Setup analysis ─────────────────────────────────────────────────
    def _analyze_setup(self, df, facts, trend_bias, setup_tf, confirmations, failures):
        score, reasons = 0, []
        wants = "bullish" if trend_bias == "bullish" else "bearish"
        tf = setup_tf.upper()
        row = df.iloc[-1]
        bb_upper = row.get("BB_Upper", 0)
        bb_lower = row.get("BB_Lower", 0)
        bb_mid   = row.get("BB_Middle", 0)
        close    = row.get("close", 0)
        rsi      = row.get("RSI", 50)
        stoch_k  = row.get("STOCH_K", 50)

        # Order Block
        if facts.get("order_block") == wants:
            msg = f"{tf} SETUP: Price retested a {wants} Order Block — institutional entry zone."
            confirmations.append(msg); reasons.append(msg); score += 1
        else:
            failures.append(f"SETUP ({tf}): No {wants} Order Block retest detected.")

        # Fair Value Gap
        if facts.get("fvg") == wants:
            msg = f"{tf} SETUP: Unfilled {wants} Fair Value Gap in trade direction — imbalance to fill."
            confirmations.append(msg); reasons.append(msg); score += 1
        else:
            failures.append(f"SETUP ({tf}): No {wants} Fair Value Gap present.")

        # Liquidity sweep
        if facts.get("liquidity_sweep") == wants:
            msg = f"{tf} SETUP: Liquidity sweep reversed to {wants} — stop hunt complete."
            confirmations.append(msg); reasons.append(msg); score += 1
        else:
            failures.append(f"SETUP ({tf}): No liquidity sweep in {wants} direction.")

        # Price zone
        zone = facts.get("zone", "")
        if (wants == "bullish" and zone == "discount") or (wants == "bearish" and zone == "premium"):
            msg = f"{tf} SETUP: Price in {zone} zone — optimal for {wants} entries."
            confirmations.append(msg); reasons.append(msg); score += 1
        else:
            failures.append(
                f"SETUP ({tf}): Price in '{zone}' zone — "
                f"{'discount' if wants == 'bullish' else 'premium'} preferred for {wants}."
            )

        # BOS
        if facts.get("bos") == wants:
            msg = f"{tf} SETUP: Break of Structure confirms {wants} continuation."
            confirmations.append(msg); reasons.append(msg); score += 1
        else:
            failures.append(f"SETUP ({tf}): No Break of Structure in {wants} direction.")

        # Bollinger Band context
        if wants == "bullish" and close < bb_mid:
            failures.append(f"SETUP ({tf}): Price below Bollinger midline — bearish pressure within range.")
        elif wants == "bearish" and close > bb_mid:
            failures.append(f"SETUP ({tf}): Price above Bollinger midline — bullish pressure within range.")

        # RSI context
        if wants == "bullish" and rsi < 30:
            msg = f"{tf} RSI oversold ({rsi:.1f}) — potential bullish reversal zone."
            confirmations.append(msg)
        elif wants == "bearish" and rsi > 70:
            msg = f"{tf} RSI overbought ({rsi:.1f}) — potential bearish reversal zone."
            confirmations.append(msg)

        return {"score": score, "reasons": reasons}

    # ── Entry analysis ─────────────────────────────────────────────────
    def _analyze_entry(self, indicators, smc_data, trend_bias, entry_tfs, confirmations, failures):
        score, reasons = 0, []
        wants = "bullish" if trend_bias == "bullish" else "bearish"

        for tf in list(dict.fromkeys(entry_tfs)):
            if tf not in indicators:
                failures.append(f"ENTRY ({tf.upper()}): No indicator data.")
                continue
            row   = indicators[tf].iloc[-1]
            facts = smc_data.get(tf, {})
            tf_u  = tf.upper()

            # Momentum
            mom = row.get("MOMENTUM", 0)
            if (wants == "bullish" and mom > 0) or (wants == "bearish" and mom < 0):
                msg = f"{tf_u} ENTRY: Momentum ({mom:.6f}) confirms {wants} pressure."
                confirmations.append(msg); reasons.append(msg); score += 1
            else:
                failures.append(
                    f"ENTRY ({tf_u}): Momentum ({mom:.6f}) opposes {wants} direction — "
                    f"entry timing not confirmed."
                )

            # BOS/CHoCH
            if facts.get("bos") == wants or facts.get("choch") == wants:
                label = "BOS" if facts.get("bos") == wants else "CHoCH"
                msg = f"{tf_u} ENTRY: {label} confirms {wants} structure — timing entry."
                confirmations.append(msg); reasons.append(msg); score += 1
            else:
                failures.append(
                    f"ENTRY ({tf_u}): No Break of Structure or Change of Character "
                    f"in {wants} direction on entry timeframe."
                )

            # Volume
            vol    = row.get("volume", 0)
            vol_ma = row.get("VOLUME_MA20", 0)
            if vol_ma and vol > vol_ma:
                msg = f"{tf_u} ENTRY: Volume ({vol:.0f}) above 20-MA ({vol_ma:.0f}) — conviction move."
                confirmations.append(msg); reasons.append(msg); score += 1
            else:
                failures.append(
                    f"ENTRY ({tf_u}): Volume ({vol:.0f}) below 20-period average ({vol_ma:.0f}) — "
                    f"weak participation."
                )

            # RSI
            rsi = row.get("RSI", 50)
            if wants == "bullish" and 40 <= rsi <= 72:
                msg = f"{tf_u} ENTRY: RSI {rsi:.1f} — bullish momentum, not overbought."
                confirmations.append(msg); reasons.append(msg); score += 1
            elif wants == "bearish" and 28 <= rsi <= 60:
                msg = f"{tf_u} ENTRY: RSI {rsi:.1f} — bearish momentum, not oversold."
                confirmations.append(msg); reasons.append(msg); score += 1
            else:
                if wants == "bullish" and rsi > 72:
                    failures.append(f"ENTRY ({tf_u}): RSI {rsi:.1f} overbought — poor BUY timing.")
                elif wants == "bullish" and rsi < 40:
                    failures.append(f"ENTRY ({tf_u}): RSI {rsi:.1f} too weak for bullish entry confirmation.")
                elif wants == "bearish" and rsi < 28:
                    failures.append(f"ENTRY ({tf_u}): RSI {rsi:.1f} oversold — poor SELL timing.")
                else:
                    failures.append(f"ENTRY ({tf_u}): RSI {rsi:.1f} not in range for {wants} entry.")

        return {"score": score, "reasons": reasons}

    # ── Support & Resistance ────────────────────────────────────────────
    def _calc_sr(self, indicators, setup_tf, trend_tfs):
        tf = setup_tf if setup_tf in indicators else (trend_tfs[0] if trend_tfs else None)
        if not tf or tf not in indicators:
            return 0.0, 0.0
        df = indicators[tf]
        window = min(len(df), 50)
        recent = df.tail(window)
        support    = float(recent["low"].min())
        resistance = float(recent["high"].max())
        return support, resistance

    # ── Summary builders ───────────────────────────────────────────────
    def _build_summary(self, symbol, direction, confidence, trend,
                       entry, sl, tp1, tp2, rr, confirmations, mode):
        n = len(confirmations)
        conf_word = "high" if confidence >= 80 else "moderate" if confidence >= 65 else "lower"
        sl_pct  = abs(entry - sl)  / entry * 100 if entry else 0
        tp1_pct = abs(tp1  - entry) / entry * 100 if entry else 0
        return (
            f"AI Signal: {direction} on {symbol} ({mode}). "
            f"Confidence {confidence}% ({conf_word}) with {n} technical + SMC confirmations. "
            f"{trend} trend confirmed on higher timeframes. "
            f"Entry at {entry:.5f}, Stop Loss {sl:.5f} ({sl_pct:.2f}% risk), "
            f"TP1 {tp1:.5f} ({tp1_pct:.2f}% gain), TP2 {tp2:.5f}. "
            f"Risk:Reward 1:{rr:.1f}. {self._session()}."
        )

    def _build_wait_summary(self, symbol, trend_bias, failures, confirmations):
        n_fail = len(failures)
        n_pass = len(confirmations)
        trend_str = trend_bias if trend_bias != "neutral" else "no clear trend"
        return (
            f"WAIT on {symbol}. {n_pass} condition(s) passed, "
            f"{n_fail} condition(s) failed. "
            f"Trend: {trend_str}. "
            f"Key blockers: {'; '.join(failures[:2]) if failures else 'Insufficient data'}. "
            f"No trade until all confluence conditions are met."
        )

    def _wait_result(self, symbol, failures, summary, confirmations=None,
                     confidence=0, trend="neutral", smc_data=None,
                     indicators=None, support=0.0, resistance=0.0, mode=DEFAULT_SCAN_MODE):
        return {
            "signal":        "WAIT",
            "confidence":    confidence,
            "entry":         0.0,
            "stop_loss":     0.0,
            "take_profit_1": 0.0,
            "take_profit_2": 0.0,
            "take_profit_3": 0.0,
            "risk_reward":   0.0,
            "trend":         trend.title() if trend != "neutral" else "Neutral",
            "session":       self._session(),
            "confirmations": confirmations or [],
            "failures":      failures,
            "summary":       summary,
            "smc_analysis":  {tf: dict(v) for tf, v in (smc_data or {}).items()},
            "timeframes":    {tf: indicators[tf].iloc[-1].to_dict() for tf in (indicators or {})},
            "support":       support,
            "resistance":    resistance,
            "mode":          mode,
            "symbol":        symbol,
            "timestamp":     time.time(),
        }

    def _session(self) -> str:
        from datetime import datetime, timezone
        hour = datetime.now(timezone.utc).hour
        if 8 <= hour < 17:
            return "London session"
        if 13 <= hour < 22:
            return "New York session"
        if 0 <= hour < 9:
            return "Tokyo session"
        return "Outside major sessions"
