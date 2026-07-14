"""
AI Trader Pro
Standard Strategy Result Model
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class StrategyResult:
    """
    Standard output for every trading strategy.

    Every strategy (ICT, SMC, EMA, Scalping, etc.)
    should return this object instead of different dictionaries.
    """

    # Main Signal
    signal: str = "NO TRADE"
    confidence: int = 0

    # Explanation
    reasons: List[str] = field(default_factory=list)

    # Trading Levels
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    # Market Information
    market_bias: str = "Neutral"
    timeframe: str = ""
    strategy: str = ""

    # Risk Management
    risk_reward: str = ""

    # Chart Objects
    drawings: List[Dict[str, Any]] = field(default_factory=list)

    # Extra Information
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_reason(self, text: str):
        """Append a reason for the decision."""
        self.reasons.append(text)

    def add_drawing(self, drawing: Dict[str, Any]):
        """Append a drawing instruction."""
        self.drawings.append(drawing)

    @property
    def is_trade(self) -> bool:
        """True if signal is BUY or SELL."""
        return self.signal.upper() in ("BUY", "SELL")

    def to_dict(self):
        """Convert to dictionary."""
        return {
            "signal": self.signal,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "market_bias": self.market_bias,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "risk_reward": self.risk_reward,
            "drawings": self.drawings,
            "metadata": self.metadata,
        }