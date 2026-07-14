"""
AI Trader Pro
Chart Data Model
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class ChartModel:
    """
    Holds everything required to render the chart.

    The ChartWidget should only draw this model.
    """

    # OHLCV Data
    candles: List[Dict[str, Any]] = field(default_factory=list)
    volume: List[float] = field(default_factory=list)

    # Indicators
    ema20: List[float] = field(default_factory=list)
    ema50: List[float] = field(default_factory=list)
    sma200: List[float] = field(default_factory=list)

    rsi: List[float] = field(default_factory=list)
    macd: List[float] = field(default_factory=list)
    signal_line: List[float] = field(default_factory=list)

    # Drawing Objects
    drawings: List[Dict[str, Any]] = field(default_factory=list)

    # Chart State
    symbol: str = "BTCUSDT"
    timeframe: str = "15m"

    current_price: float = 0.0

    last_update: str = ""

    def clear_drawings(self):
        """Remove all drawings from the chart."""
        self.drawings.clear()

    def add_drawing(self, drawing: Dict[str, Any]):
        """Add a drawing instruction."""
        self.drawings.append(drawing)

    def clear(self):
        """Clear all chart data."""
        self.candles.clear()
        self.volume.clear()

        self.ema20.clear()
        self.ema50.clear()
        self.sma200.clear()

        self.rsi.clear()
        self.macd.clear()
        self.signal_line.clear()

        self.drawings.clear()