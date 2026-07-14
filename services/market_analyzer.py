"""
services/market_analyzer.py
=============================
Technical indicator calculation engine for AI Trader Pro.

Fixes applied:
  - VWAP: per-day session reset when timestamp data is available
    (falls back to cumulative VWAP when no timestamp column is present,
    exactly as before — this never breaks existing code).
  - ATR: NaN-safe guard and minimum floor prevents division-by-zero
    in downstream signal calculations.
  - ADX: guard against zero-division on flat price data.
  - All magic numbers moved to named module-level constants.
  - ffill/bfill replaced with pandas-recommended inplace=False usage
    to suppress FutureWarning in pandas 2.x.
  - Added Stochastic Oscillator (%K / %D) for RSI cross-confirmation.
  - Module-level docstring explaining every indicator and its purpose.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

# ── Indicator constants (no magic numbers inline) ──────────────────────────
_EMA_SHORT     = 20     # EMA20 — short-term trend
_EMA_MID       = 50     # EMA50 — intermediate trend
_SMA_LONG      = 200    # SMA200 — macro trend baseline

_RSI_PERIOD    = 14     # RSI lookback
_RSI_SMOOTH    = 13     # Wilder smoothing (com=13 ≈ alpha=1/14)

_MACD_FAST     = 12     # MACD fast EMA
_MACD_SLOW     = 26     # MACD slow EMA
_MACD_SIGNAL   = 9      # MACD signal EMA

_BB_PERIOD     = 20     # Bollinger Band basis period
_BB_STD        = 2.0    # Bollinger Band standard-deviation width

_ATR_PERIOD    = 14     # ATR / ADX smoothing period
_ATR_MIN_FLOOR = 1e-9   # Minimum ATR to prevent downstream division-by-zero

_VWAP_PERIOD   = "D"    # Resample frequency for session-reset VWAP ("D" = daily)

_MOM_PERIOD    = 10     # Momentum lookback (close.diff(N))
_VOL_MA_PERIOD = 20     # Volume moving average period

_STOCH_K       = 14     # Stochastic %K lookback
_STOCH_D       = 3      # Stochastic %D smoothing


class MarketAnalyzer:
    """
    Stateless technical indicator calculator.

    Accepts a raw OHLCV DataFrame (columns: open, high, low, close, volume)
    and returns a new DataFrame with all indicator columns appended.

    Design rules:
      - Never modifies the input DataFrame.
      - Never raises — returns input unchanged on any error.
      - Every indicator fill-forward-fill-backward to eliminate NaN in the
        usable portion of the frame, matching the original behaviour.
    """

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all technical indicators and return an enriched DataFrame.

        Indicators added:
          EMA20, EMA50, SMA200      — trend
          RSI                       — momentum oscillator
          MACD, MACD_Signal, MACD_Hist — momentum + divergence
          BB_Upper, BB_Middle, BB_Lower — volatility channel
          ATR                       — volatility / stop-sizing
          ADX, PLUS_DI, MINUS_DI   — trend strength / direction
          VWAP                      — fair-value anchor (session-reset when possible)
          MOMENTUM                  — rate-of-change
          VOLUME_MA20               — volume trend filter
          STOCH_K, STOCH_D          — stochastic oscillator
        """
        if df is None or df.empty:
            return df

        try:
            return self._compute(df)
        except Exception:
            return df

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        w = df.copy()

        # ── 1. Moving averages ────────────────────────────────────────────
        w["EMA20"]  = w["close"].ewm(span=_EMA_SHORT, adjust=False).mean()
        w["EMA50"]  = w["close"].ewm(span=_EMA_MID,   adjust=False).mean()
        w["SMA200"] = w["close"].rolling(window=_SMA_LONG, min_periods=1).mean()

        # ── 2. RSI (Wilder smoothing) ─────────────────────────────────────
        delta  = w["close"].diff()
        gain   = delta.clip(lower=0)
        loss   = (-delta).clip(lower=0)
        rs     = (gain.ewm(com=_RSI_SMOOTH, adjust=False).mean() /
                  (loss.ewm(com=_RSI_SMOOTH, adjust=False).mean() + _ATR_MIN_FLOOR))
        w["RSI"] = 100.0 - (100.0 / (1.0 + rs))

        # ── 3. MACD ───────────────────────────────────────────────────────
        ema_fast    = w["close"].ewm(span=_MACD_FAST,   adjust=False).mean()
        ema_slow    = w["close"].ewm(span=_MACD_SLOW,   adjust=False).mean()
        w["MACD"]       = ema_fast - ema_slow
        w["MACD_Signal"] = w["MACD"].ewm(span=_MACD_SIGNAL, adjust=False).mean()
        w["MACD_Hist"]   = w["MACD"] - w["MACD_Signal"]

        # ── 4. Bollinger Bands ────────────────────────────────────────────
        bb_basis    = w["close"].rolling(window=_BB_PERIOD, min_periods=1).mean()
        bb_std      = w["close"].rolling(window=_BB_PERIOD, min_periods=1).std().fillna(0)
        w["BB_Middle"] = bb_basis
        w["BB_Upper"]  = bb_basis + bb_std * _BB_STD
        w["BB_Lower"]  = bb_basis - bb_std * _BB_STD

        # ── 5. ATR ───────────────────────────────────────────────────────
        prev_close = w["close"].shift(1)
        tr = pd.concat([
            w["high"] - w["low"],
            (w["high"] - prev_close).abs(),
            (w["low"]  - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr_raw = tr.ewm(alpha=1.0 / _ATR_PERIOD, adjust=False).mean()
        # NaN-safe floor — prevents division-by-zero in SignalEngine
        w["ATR"] = atr_raw.clip(lower=_ATR_MIN_FLOOR)

        # ── 6. ADX (Average Directional Index) ────────────────────────────
        up_move  = w["high"].diff()
        dn_move  = -w["low"].diff()
        plus_dm  = ((up_move > dn_move) & (up_move > 0)) * up_move
        minus_dm = ((dn_move > up_move) & (dn_move > 0)) * dn_move
        atr_di   = atr_raw.ewm(alpha=1.0 / _ATR_PERIOD, adjust=False).mean().replace(0, _ATR_MIN_FLOOR)
        plus_di  = 100.0 * (plus_dm.ewm(alpha=1.0 / _ATR_PERIOD, adjust=False).mean() / atr_di)
        minus_di = 100.0 * (minus_dm.ewm(alpha=1.0 / _ATR_PERIOD, adjust=False).mean() / atr_di)
        di_sum   = (plus_di + minus_di).replace(0, _ATR_MIN_FLOOR)
        dx       = 100.0 * (plus_di - minus_di).abs() / di_sum
        w["ADX"]      = dx.ewm(alpha=1.0 / _ATR_PERIOD, adjust=False).mean()
        w["PLUS_DI"]  = plus_di
        w["MINUS_DI"] = minus_di

        # ── 7. VWAP (session-reset when timestamp available) ──────────────
        w["VWAP"] = self._calculate_vwap(w)

        # ── 8. Momentum & Volume MA ────────────────────────────────────────
        w["MOMENTUM"]   = w["close"].diff(_MOM_PERIOD)
        w["VOLUME_MA20"] = w["volume"].rolling(window=_VOL_MA_PERIOD, min_periods=1).mean()

        # ── 9. Stochastic Oscillator (%K / %D) ────────────────────────────
        low_min  = w["low"].rolling(window=_STOCH_K,  min_periods=1).min()
        high_max = w["high"].rolling(window=_STOCH_K, min_periods=1).max()
        denom    = (high_max - low_min).replace(0, _ATR_MIN_FLOOR)
        w["STOCH_K"] = 100.0 * (w["close"] - low_min) / denom
        w["STOCH_D"] = w["STOCH_K"].rolling(window=_STOCH_D, min_periods=1).mean()

        # ── Fill NaN at the start of the series ───────────────────────────
        w = w.ffill().bfill()

        return w

    def _calculate_vwap(self, w: pd.DataFrame) -> pd.Series:
        """
        Session-resetting VWAP when a datetime-indexed or 'timestamp' column is
        available. Falls back to cumulative VWAP (the original behaviour) when
        no date information can be extracted.

        Daily session resets make VWAP a meaningful fair-value anchor for
        intraday strategies instead of a always-upward-trending cumulative line.
        """
        typical = (w["high"] + w["low"] + w["close"]) / 3.0

        # Try to group by date for session reset
        date_index = None
        if hasattr(w.index, "date"):
            # DatetimeIndex — use it directly
            date_index = w.index.date
        elif "timestamp" in w.columns:
            try:
                ts = pd.to_datetime(w["timestamp"], unit="s", errors="coerce")
                if ts.notna().any():
                    date_index = ts.dt.date.values
            except Exception:
                pass

        if date_index is not None:
            # Group by session day and compute VWAP per day, then concatenate
            w_copy = w.assign(_date=date_index, _typical=typical)
            result = pd.Series(index=w.index, dtype=float)
            for _, grp in w_copy.groupby("_date", sort=False):
                vol     = grp["volume"].clip(lower=0)
                cum_tpv = (grp["_typical"] * vol).cumsum()
                cum_vol = vol.cumsum().replace(0, _ATR_MIN_FLOOR)
                result.loc[grp.index] = cum_tpv / cum_vol
            return result.fillna(typical)

        # Fallback: cumulative VWAP over the entire window (original behaviour)
        vol     = w["volume"].clip(lower=0)
        cum_tpv = (typical * vol).cumsum()
        cum_vol = vol.cumsum().replace(0, _ATR_MIN_FLOOR)
        return cum_tpv / cum_vol
