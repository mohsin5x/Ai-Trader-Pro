balance = 10000

position = None

trade_history = []


def buy(price):

    global balance
    global position

    if position is None:

        position = {
            "entry": price
        }

        trade_history.append(
            f"BUY at {price:.2f}"
        )


def sell(price):

    global balance
    global position

    if position:

        profit = price - position["entry"]

        balance += profit

        trade_history.append(
            f"SELL at {price:.2f}  Profit: {profit:.2f}"
        )

        position = None


def get_balance():
    return balance


def get_position():
    return position


def get_history():
    return trade_history