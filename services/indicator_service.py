import pandas as pd


def calculate_sma(prices, period):
    """
    Calculate Simple Moving Average (SMA)
    """
    series = pd.Series(prices)
    return series.rolling(period).mean().tolist()


def calculate_ema(prices, period):
    """
    Calculate Exponential Moving Average (EMA)
    """
    series = pd.Series(prices)
    return series.ewm(span=period, adjust=False).mean().tolist()