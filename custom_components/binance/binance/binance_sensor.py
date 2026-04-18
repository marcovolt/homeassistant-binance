from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from ..constants import (
    DEFAULT_COIN_ICON,
    ATTRIBUTION,
    ATTR_FREE,
    ATTR_LOCKED,
    ATTR_NATIVE_BALANCE,
    CURRENCY_ICONS,
    ATTR_NATIVE_UNIT,
    BinanceEntityFeature,
    ATTR_PRICE_IN_NATIVE,
    ATTR_CONVERSION_PATH,
)
import logging
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import callback

_LOGGER = logging.getLogger(__name__)


class BinanceSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Binance balance sensor."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, name, balance, account_type='spot'):
        super().__init__(coordinator)
        self._name = f"{name} {balance['asset']} {account_type.capitalize()} Balance"
        self._asset = balance["asset"]
        self._state = None
        self._free = 0.0
        self._locked = 0.0
        self._native = coordinator.native_currency
        self._native_balance = None
        self._price_in_native = None
        self._conversion_path = None
        self._coordinator = coordinator
        self._attr_unique_id = f"{name}_binance_{balance['asset']}_{account_type}_balance"
        self._attr_available = True
        self._attr_device_class = None
        self.account_type = account_type
        self._attr_supported_features = BinanceEntityFeature.EXT_WITHDRAW
        self._apply_balance(balance)

    def _apply_balance(self, balance):
        self._free = float(balance.get("free", 0) or 0)
        self._locked = float(balance.get("locked", 0) or 0)
        self._state = round(self._free + self._locked, 8)
        self._price_in_native, self._native_balance, self._conversion_path = self._coordinator.get_asset_native_price_and_value(
            self._asset, self._state
        )

    @property
    def name(self):
        return self._name

    @property
    def device_info(self):
        if self.account_type == 'spot':
            return self.coordinator.device_info_spot_balances
        return self.coordinator.device_info_funding_balances

    @property
    def native_value(self):
        return self._state

    @property
    def native_unit_of_measurement(self):
        return self._asset

    @property
    def icon(self):
        return CURRENCY_ICONS.get(self._asset, DEFAULT_COIN_ICON)

    @property
    def extra_state_attributes(self):
        return {
            ATTR_ATTRIBUTION: ATTRIBUTION,
            ATTR_NATIVE_BALANCE: self._native_balance,
            ATTR_NATIVE_UNIT: self._native,
            ATTR_FREE: self._free,
            ATTR_LOCKED: self._locked,
            ATTR_PRICE_IN_NATIVE: self._price_in_native,
            ATTR_CONVERSION_PATH: self._conversion_path,
        }

    @property
    def is_valid(self):
        return isinstance(self._name, str) and isinstance(self._asset, str)

    @callback
    def _handle_coordinator_update(self) -> None:
        balances = self._coordinator.data.get("funding_balances", []) if self.account_type == 'funding' else self._coordinator.data.get("balances", [])
        balance = next((row for row in balances if row.get("asset") == self._asset), None)
        if balance:
            self._attr_available = True
            self._apply_balance(balance)
        else:
            self._attr_available = False
        self.async_write_ha_state()


class BinanceValueSensor(CoordinatorEntity, SensorEntity):
    """Per-coin value in native currency."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None

    def __init__(self, coordinator, asset):
        super().__init__(coordinator)
        self._asset = asset
        self._native = coordinator.native_currency
        self._attr_unique_id = f"{coordinator.conf_name}_binance_{asset}_spot_value"
        self._attr_name = f"{coordinator.conf_name} {asset} Spot Value"
        self._attr_available = True
        self._value = None
        self._price = None
        self._path = None
        self._update_from_coordinator()

    @property
    def device_info(self):
        return self.coordinator.device_info_spot_values

    @property
    def native_value(self):
        return self._value

    @property
    def native_unit_of_measurement(self):
        return self._native

    @property
    def icon(self):
        return CURRENCY_ICONS.get(self._asset, DEFAULT_COIN_ICON)

    @property
    def extra_state_attributes(self):
        return {
            ATTR_ATTRIBUTION: ATTRIBUTION,
            ATTR_PRICE_IN_NATIVE: self._price,
            ATTR_CONVERSION_PATH: self._path,
            ATTR_NATIVE_UNIT: self._native,
        }

    def _update_from_coordinator(self):
        balance = self.coordinator.get_balance_for_asset(self._asset, "spot")
        if not balance:
            self._attr_available = False
            self._value = None
            return
        amount = float(balance.get("free", 0) or 0) + float(balance.get("locked", 0) or 0)
        price, value, path = self.coordinator.get_asset_native_price_and_value(self._asset, amount)
        self._price = price
        self._value = value
        self._path = path
        self._attr_available = value is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_from_coordinator()
        self.async_write_ha_state()


class BinancePortfolioTotalSensor(CoordinatorEntity, SensorEntity):
    """Total spot portfolio value in native currency."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None
    _attr_icon = "mdi:wallet"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._native = coordinator.native_currency
        self._attr_unique_id = f"{coordinator.conf_name}_binance_portfolio_total"
        self._attr_name = f"{coordinator.conf_name} Portfolio Total"

    @property
    def device_info(self):
        return self.coordinator.device_info_spot_values

    @property
    def native_value(self):
        return self.coordinator.total_portfolio_value

    @property
    def native_unit_of_measurement(self):
        return self._native

    @property
    def extra_state_attributes(self):
        return {
            ATTR_ATTRIBUTION: ATTRIBUTION,
            "tracked_assets": len(self.coordinator.data.get("balances", [])),
            "min_native_value_filter": self.coordinator.min_native_value,
        }


class BinancePortfolioTotalGraphSensor(CoordinatorEntity, SensorEntity):
    """Graph/statistics-friendly copy of total spot portfolio value."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = None
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._native = coordinator.native_currency
        self._attr_unique_id = f"{coordinator.conf_name}_binance_portfolio_total_graph"
        self._attr_name = f"{coordinator.conf_name} Portfolio Total Graph"

    @property
    def device_info(self):
        return self.coordinator.device_info_spot_values

    @property
    def native_value(self):
        return self.coordinator.total_portfolio_value

    @property
    def native_unit_of_measurement(self):
        return self._native

    @property
    def extra_state_attributes(self):
        return {
            ATTR_ATTRIBUTION: ATTRIBUTION,
            "tracked_assets": len(self.coordinator.data.get("balances", [])),
            "graph_only": True,
            "source_sensor": f"sensor.{self.coordinator.conf_name.lower()}_binance_portfolio_total",
            "min_native_value_filter": self.coordinator.min_native_value,
        }

