from services.indicator_service import calculate_sma, calculate_ema

prices = [10, 20, 30, 40, 50, 60, 70, 80]

sma = calculate_sma(prices, 3)
ema = calculate_ema(prices, 3)

print("SMA:", sma)
print("EMA:", ema)