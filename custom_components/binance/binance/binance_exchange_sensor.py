from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from ..constants import DEFAULT_COIN_ICON, ATTRIBUTION, CURRENCY_ICONS, QUOTE_ASSETS
import logging
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import callback

_LOGGER = logging.getLogger(__name__)


class BinanceExchangeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Binance Exchange Sensor."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None

    def __init__(self, coordinator, ticker):
        super().__init__(coordinator)
        self._name = f"{coordinator.conf_name} {ticker['symbol']} Exchange"
        self._symbol = ticker["symbol"]
        self._state = None
        self._unit_of_measurement = self._determine_unit(ticker["symbol"])
        self._attr_unique_id = f"{coordinator.conf_name}_binance_{ticker['symbol']}_exchange"
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info_exchanges
        # Avoid writing state before Home Assistant has attached the entity.
        self._attr_available = True
        self._state = None

    @property
    def name(self):
        return self._name

    @property
    def native_value(self):
        return self._state

    @property
    def native_unit_of_measurement(self):
        return self._unit_of_measurement

    @property
    def icon(self):
        return CURRENCY_ICONS.get(self._unit_of_measurement, DEFAULT_COIN_ICON)

    @property
    def extra_state_attributes(self):
        return {ATTR_ATTRIBUTION: ATTRIBUTION}

    def _determine_unit(self, symbol):
        for quote_asset in QUOTE_ASSETS:
            if symbol.endswith(quote_asset):
                return quote_asset
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        new_price = self._coordinator.data.get("tickers", {}).get(self._symbol, {}).get("price")
        if new_price is not None:
            try:
                self._state = float(new_price)
                self._attr_available = True
            except (TypeError, ValueError):
                self._attr_available = False
        else:
            self._attr_available = False
        self.async_write_ha_state()

    @property
    def is_valid(self):
        return self._unit_of_measurement is not None
