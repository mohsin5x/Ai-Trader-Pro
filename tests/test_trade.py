from services.trade_service import *

print("Balance:", get_balance())

buy(60000)

print(get_position())

sell(62000)

print("Balance:", get_balance())

print(get_history())