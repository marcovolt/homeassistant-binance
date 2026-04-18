import logging
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .constants import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .binance.binance_sensor import (
    BinanceSensor,
    BinanceValueSensor,
    BinancePortfolioTotalSensor,
    BinancePortfolioTotalGraphSensor,
)
from .binance.binance_exchange_sensor import BinanceExchangeSensor

_LOGGER = logging.getLogger(__name__)


def is_valid_string(value):
    return isinstance(value, str) and value.strip() != ""


async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Setup the Binance sensors."""

    try:
        entry_id = config.entry_id
        conf_name = config.data.get('name')

        if not all(is_valid_string(val) for val in [entry_id, conf_name]):
            _LOGGER.error("Invalid configuration data.")
            return

        coordinator = hass.data[DOMAIN].get(entry_id)
        if coordinator is None:
            _LOGGER.error("Coordinator for entry_id not found.")
            return
        coordinator.async_add_entities = async_add_entities

        sensors = []

        balances = (coordinator.data or {}).get("balances", [])
        for balance in balances:
            if not isinstance(balance, dict) or not all(key in balance for key in ["asset", "free", "locked"]):
                _LOGGER.error("Invalid balance data: %s", balance)
                continue
            asset = str(balance.get("asset", "")).upper()
            if not coordinator.should_expose_asset(asset):
                continue
            balance_sensor = BinanceSensor(coordinator, conf_name, balance)
            value_sensor = BinanceValueSensor(coordinator, asset)
            if balance_sensor.is_valid:
                sensors.append(balance_sensor)
            sensors.append(value_sensor)
            coordinator.created_dynamic_entities.add(value_sensor.unique_id)

        funding_balances = (coordinator.data or {}).get("funding_balances", [])
        for balance in funding_balances:
            if not isinstance(balance, dict) or not all(key in balance for key in ["asset", "free", "locked"]):
                _LOGGER.error("Invalid funding balance data: %s", balance)
                continue
            asset = str(balance.get("asset", "")).upper()
            if not coordinator.should_expose_asset(asset):
                continue
            sensor = BinanceSensor(coordinator, conf_name, balance, 'funding')
            if sensor.is_valid:
                sensors.append(sensor)

        tickers = (coordinator.data or {}).get("tickers", {})
        for symbol, ticker in tickers.items():
            if not isinstance(ticker, dict) or "price" not in ticker:
                _LOGGER.error("Invalid ticker data for symbol %s: %s", symbol, ticker)
                continue
            if not coordinator.should_expose_symbol(symbol):
                continue
            sensor = BinanceExchangeSensor(coordinator, ticker)
            if sensor.is_valid:
                sensors.append(sensor)
                coordinator.created_dynamic_entities.add(sensor.unique_id)

        sensors.append(BinancePortfolioTotalSensor(coordinator))
        sensors.append(BinancePortfolioTotalGraphSensor(coordinator))
        coordinator.created_dynamic_entities.add(f"{conf_name}_binance_portfolio_total")
        coordinator.created_dynamic_entities.add(f"{conf_name}_binance_portfolio_total_graph")

        async_add_entities(sensors, True)

    except Exception as e:
        _LOGGER.error("Unexpected error during sensor setup: %s", e, exc_info=True)
