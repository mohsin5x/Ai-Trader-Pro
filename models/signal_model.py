"""
models/signal_model.py
========================
Standard output object for every signal produced by the AI Signal
Engine (services/signal_engine.py). One Signal = one fully-formed,
multi-timeframe, multi-confirmation trade idea for one symbol.

Kept separate from models/strategy_result.py, which is the single-
timeframe / single-strategy result used by the existing strategy
dropdown + chart overlays. This object is intentionally richer,
matching the full output spec: symbol, direction, entry/SL/TP1-3, R:R,
confidence, strength, trend, timeframe, data source, timestamps, trade
type classification, and the full list of confirmation reasons.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import time


@dataclass
class Signal:
    symbol: str
    direction: str  # "BUY" or "SELL"

    entry_price: float
    current_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float
    risk_reward: float

    confidence: int  # 0-100
    strength: str  # "Weak" / "Moderate" / "Strong" / "Very Strong"

    trend: str  # "Bullish" / "Bearish"
    setup_timeframe: str  # e.g. "15M"
    trade_type: str  # "Scalping" / "Intraday" / "Swing"

    data_source: str
    session: str  # e.g. "London + New York overlap"

    reasons: List[str] = field(default_factory=list)

    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    news_risk_note: str = "News risk filter not configured -- no live news-impact data source is wired in yet."

    def touch(self):
        """Marks the signal as re-confirmed on a later scan pass without
        losing its original creation time."""
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "stop_loss": self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "take_profit_3": self.take_profit_3,
            "risk_reward": self.risk_reward,
            "confidence": self.confidence,
            "strength": self.strength,
            "trend": self.trend,
            "setup_timeframe": self.setup_timeframe,
            "trade_type": self.trade_type,
            "data_source": self.data_source,
            "session": self.session,
            "reasons": list(self.reasons),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "news_risk_note": self.news_risk_note,
        }
