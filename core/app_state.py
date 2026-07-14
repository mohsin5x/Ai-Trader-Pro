"""
AI Trader Pro
Global Application State
========================
Centralized, thread-safe application state coordinator. 
Tracks the extended connection lifecycle to prevent UI status locks
during asynchronous data provider transitions.
"""

import threading
from models.chart_model import ChartModel
from models.strategy_result import StrategyResult


class AppState:
    """
    Shared application state machine.

    Every UI panel reads from this object to maintain a unified, thread-safe
    representation of data, layout, and background worker lifecycles.
    """

    def __init__(self):
        # Thread Safety
        self._lock = threading.Lock()

        # Market
        self.symbol = "BTCUSDT"
        self.timeframe = "15m"

        # Selected Strategy
        self.strategy = "ICT Smart Money"

        # Theme
        self.theme = "dark"

        # Latest Price
        self.current_price = 0.0

        # Chart Data
        self.chart = ChartModel()

        # AI Result
        self.analysis = StrategyResult()

        # UI Layout State
        self.chart_fullscreen = False

        # --- CONNECTION LIFECYCLE STATE MACHINE ---
        # Replaces ambiguous binary flags with explicit operational phases:
        # "DISCONNECTED", "INITIALIZING", "CONNECTED", "FAILED"
        self.connection_status = "DISCONNECTED"
        self.status_message = "System Ready"
        self.connected = False
        self.loading = False

    def set_symbol(self, symbol: str):
        with self._lock:
            self.symbol = symbol
            self.chart.symbol = symbol

    def set_timeframe(self, timeframe: str):
        with self._lock:
            self.timeframe = timeframe
            self.chart.timeframe = timeframe

    def set_strategy(self, strategy: str):
        with self._lock:
            self.strategy = strategy

    def set_price(self, price: float):
        with self._lock:
            self.current_price = price
            self.chart.current_price = price

    def set_analysis(self, result: StrategyResult):
        with self._lock:
            self.analysis = result

    # ------------------------------------------------------------------
    # Lifecycle State Transitions
    # ------------------------------------------------------------------
    def set_initializing(self, message: str = "Connecting to data source..."):
        """Puts the UI into an active but non-blocking loading phase."""
        with self._lock:
            self.connection_status = "INITIALIZING"
            self.status_message = message
            self.loading = True
            self.connected = False

    def set_connected(self, message: str = "Live data link active"):
        """Clears loading locks and confirms an established connection."""
        with self._lock:
            self.connection_status = "CONNECTED"
            self.status_message = message
            self.loading = False
            self.connected = True

    def set_disconnected(self, message: str = "Data link offline"):
        """Clears all locks and resets state to safe default defaults."""
        with self._lock:
            self.connection_status = "DISCONNECTED"
            self.status_message = message
            self.loading = False
            self.connected = False

    def set_failed(self, error_message: str):
        """Captures connection failures without stopping the UI loop."""
        with self._lock:
            self.connection_status = "FAILED"
            self.status_message = f"Error: {error_message}"
            self.loading = False
            self.connected = False

    def sync_provider_status(self, provider):
        """
        Queries the current active data provider safely.
        Ensures the UI state perfectly mirrors background worker initialization.
        """
        if not provider:
            self.set_disconnected("No provider configured")
            return

        # Check if the provider is currently attempting an async background initialization
        is_initializing = getattr(provider, "_init_thread_active", False)
        is_ok = provider.is_configured()

        if is_initializing:
            self.set_initializing(f"Initializing {provider.display_name}...")
        elif is_ok:
            self.set_connected(f"{provider.display_name} Connected")
        else:
            if provider.name == "mt5":
                self.set_failed("MT5 Terminal unreachable. Verify application is open and active.")
            else:
                self.set_failed(f"{provider.display_name} offline")