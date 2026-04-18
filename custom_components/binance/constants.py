# constants.py

from enum import IntFlag

DOMAIN = 'binance'
DEFAULT_NAME = 'Binance'
DATA_BINANCE = 'binance_cache'

CONF_API_SECRET = 'api_secret'
CONF_NATIVE_CURRENCY = 'native_currency'
CONF_BALANCES = 'balances'
CONF_EXCHANGES = 'exchanges'
CONF_DOMAIN = 'domain'
CONF_ENABLE_BALANCES = 'enable_balances'
CONF_ENABLE_EXCHANGES = 'enable_exchanges'
CONF_ENABLE_EARN = 'enable_earn'
CONF_ENABLE_FUNDING = 'enable_funding'
CONF_MIN_NATIVE_VALUE = 'min_native_value'
DEFAULT_DOMAIN = 'com'

DEFAULT_CURRENCY = 'EUR'
DEFAULT_MIN_NATIVE_VALUE = 0.5

ENDPOINT_EARN_FLEXIBLE = '/sapi/v1/simple-earn/flexible/position'
ENDPOINT_EARN_LOCKED = '/sapi/v1/simple-earn/locked/position'

SERVICE_WITHDRAW = 'withdraw'

CURRENCY_ICONS = {
    'BTC': 'mdi:currency-btc',
    'ETH': 'mdi:currency-eth',
    'EUR': 'mdi:currency-eur',
    'LTC': 'mdi:litecoin',
    'USD': 'mdi:currency-usd',
    'USDT': 'mdi:currency-usd',
    'BNB': 'mdi:currency-bnb',
}

DEFAULT_COIN_ICON = 'mdi:bitcoin'
ATTRIBUTION = 'Data provided by Binance'
ATTR_UNIT = 'unit'
ATTR_FREE = 'free'
ATTR_LOCKED = 'locked'
ATTR_NATIVE_BALANCE = 'native_balance'
ATTR_NATIVE_UNIT = 'native_unit'
ATTR_TOTAL_REWARDS = 'total_rewards'
ATTR_PRICE_IN_NATIVE = 'price_in_native'
ATTR_CONVERSION_PATH = 'conversion_path'
QUOTE_ASSETS = ['EUR', 'USD', 'USDT', 'USDC', 'BUSD', 'BTC']
UNDO_UPDATE_LISTENER = 'undo_update_listener'


class BinanceEntityFeature(IntFlag):
    """Supported features of the entity."""

    EXT_WITHDRAW = 1
