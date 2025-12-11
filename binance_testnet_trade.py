"""
Binance Testnet Trading Example
自动化下单/撤单/账户信息（测试网）
"""
import ccxt
import time
from loguru import logger

API_KEY = 'YOUR_TESTNET_API_KEY'
API_SECRET = 'YOUR_TESTNET_API_SECRET'

# 使用币安测试网
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    },
    'urls': {
        'api': {
            'public': 'https://testnet.binancefuture.com/fapi/v1',
            'private': 'https://testnet.binancefuture.com/fapi/v1',
        }
    }
})

SYMBOL = 'BTCUSDT'

# 获取账户余额
def get_balance():
    balance = exchange.fetch_balance()
    usdt = balance['total'].get('USDT', 0)
    logger.info(f"USDT Balance: {usdt}")
    return usdt

# 下单（市价单）
def place_order(symbol, side, amount):
    order = exchange.create_order(
        symbol=symbol,
        type='MARKET',
        side=side,
        amount=amount
    )
    logger.info(f"Order placed: {order}")
    return order

# 查询持仓
def get_positions():
    positions = exchange.fapiPrivateGetPositionRisk()
    for pos in positions:
        if pos['symbol'] == SYMBOL:
            logger.info(f"Position: {pos}")
    return positions

if __name__ == "__main__":
    get_balance()
    # 示例：做多1张合约
    place_order(SYMBOL, 'buy', 0.001)
    time.sleep(2)
    get_positions()
    # 示例：做空1张合约
    place_order(SYMBOL, 'sell', 0.001)
    time.sleep(2)
    get_positions()
