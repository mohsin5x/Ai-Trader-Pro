def generate_signal(current_price, ema):

    if current_price > ema:
        return {
            "signal": "BUY",
            "confidence": 80,
            "reason": "Price is above EMA"
        }

    elif current_price < ema:
        return {
            "signal": "SELL",
            "confidence": 80,
            "reason": "Price is below EMA"
        }

    return {
        "signal": "WAIT",
        "confidence": 50,
        "reason": "No clear trend"
    }