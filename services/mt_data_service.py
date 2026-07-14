import MetaTrader5 as mt5
import threading
import time
from datetime import datetime


class MT5DataService:
    def __init__(self):
        self.connected = False
        self.broker = ""
        self.server = ""
        self.account = None
        self.lock = threading.Lock()

    # --------------------------------------------------
    # MT5 CONNECTION
    # --------------------------------------------------
    def connect(self):
        with self.lock:
            if mt5.initialize():

                info = mt5.account_info()

                if info:
                    self.connected = True
                    self.account = info
                    self.server = info.server
                    self.broker = info.company
                    return True

            self.connected = False
            return False

    # --------------------------------------------------
    def disconnect(self):
        mt5.shutdown()
        self.connected = False

    # --------------------------------------------------
    def is_connected(self):
        return self.connected

    # --------------------------------------------------
    def reconnect(self):
        self.disconnect()
        time.sleep(1)
        return self.connect()

    # --------------------------------------------------
    # AUTO SYMBOL DETECTION
    # --------------------------------------------------
    def find_symbol(self, symbol):

        symbols = mt5.symbols_get()

        if symbols is None:
            return None

        symbol = symbol.upper()

        # Exact match
        for s in symbols:
            if s.name.upper() == symbol:
                mt5.symbol_select(s.name, True)
                return s.name

        # Startswith match
        for s in symbols:
            if s.name.upper().startswith(symbol):
                mt5.symbol_select(s.name, True)
                return s.name

        # Contains match
        for s in symbols:
            if symbol in s.name.upper():
                mt5.symbol_select(s.name, True)
                return s.name

        return None

    # --------------------------------------------------
    # LIVE QUOTE
    # --------------------------------------------------
    def get_quote(self, symbol):

        if not self.connected:
            return None

        broker_symbol = self.find_symbol(symbol)

        if broker_symbol is None:
            return None

        tick = mt5.symbol_info_tick(broker_symbol)

        if tick is None:
            return None

        return {
            "symbol": broker_symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": round((tick.ask - tick.bid), 5),
            "time": datetime.fromtimestamp(tick.time),
            "broker": self.broker,
            "server": self.server,
        }


# Singleton
mt5_service = MT5DataService()