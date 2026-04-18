from datetime import timedelta
import logging
import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import time
import hmac
import hashlib
from collections import deque

from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.config_entries import ConfigEntry

from binance.client import Client

from .constants import (
    DOMAIN,
    CONF_API_SECRET,
    CONF_DOMAIN,
    DEFAULT_DOMAIN,
    CONF_NATIVE_CURRENCY,
    DEFAULT_CURRENCY,
    CONF_ENABLE_BALANCES,
    CONF_ENABLE_FUNDING,
    CONF_ENABLE_EXCHANGES,
    CONF_ENABLE_EARN,
    CONF_BALANCES,
    CONF_EXCHANGES,
    CONF_MIN_NATIVE_VALUE,
    DEFAULT_MIN_NATIVE_VALUE,
    ENDPOINT_EARN_FLEXIBLE,
    ENDPOINT_EARN_LOCKED,
)
from .binance.binance_sensor import BinanceSensor, BinanceValueSensor, BinancePortfolioTotalSensor
from .binance.binance_exchange_sensor import BinanceExchangeSensor

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=1)


class BinanceCoordinator(DataUpdateCoordinator):
    """Coordinator to retrieve data from Binance."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        configured_balances,
        configured_exchanges,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.config = {**entry.data, **entry.options}
        self.api_key = self.config[CONF_API_KEY]
        self.api_secret = self.config[CONF_API_SECRET]
        self.conf_name = self.config[CONF_NAME]
        self.tld = self.config.get(CONF_DOMAIN, DEFAULT_DOMAIN)
        self.native_currency = str(self.config.get(CONF_NATIVE_CURRENCY, DEFAULT_CURRENCY)).upper()
        self.min_native_value = float(self.config.get(CONF_MIN_NATIVE_VALUE, DEFAULT_MIN_NATIVE_VALUE) or DEFAULT_MIN_NATIVE_VALUE)
        self.enabled_feature = {
            "balance": self.config.get(CONF_ENABLE_BALANCES, False),
            "exchanges": self.config.get(CONF_ENABLE_EXCHANGES, False),
            "funding": self.config.get(CONF_ENABLE_FUNDING, False),
            "earn": self.config.get(CONF_ENABLE_EARN, False),
        }

        self.client = None
        self.async_add_entities = None
        self.balances = []
        self.funding_balances = []
        self.earn_balances = []
        self.tickers = {}
        self.all_prices = {}
        self.symbol_info = {}
        self.asset_symbols = {}
        self.conversion_cache = {}
        self.created_dynamic_entities = set()
        self.total_portfolio_value = None

        self.configured_balances = self._parse_configured_items(configured_balances)
        self.configured_exchanges = self._parse_configured_items(configured_exchanges)

        super().__init__(
            hass,
            _LOGGER,
            name="Binance Coordinator",
            update_interval=SCAN_INTERVAL,
        )



    def _is_ld_asset(self, asset: str) -> bool:
        return str(asset or "").upper().startswith("LD")

    def _get_effective_amount_for_asset(self, asset: str) -> float:
        asset = str(asset or "").upper()
        amount = 0.0
        for collection in (self.balances, self.earn_balances, self.funding_balances):
            for balance in collection or []:
                if str(balance.get("asset", "")).upper() != asset:
                    continue
                amount += float(balance.get("free", 0) or 0) + float(balance.get("locked", 0) or 0)
        return amount

    def should_expose_asset(self, asset: str) -> bool:
        asset = str(asset or "").upper()
        if not asset or self._is_ld_asset(asset):
            return False

        amount = self._get_effective_amount_for_asset(asset)
        if amount <= 0:
            return False

        # If the user explicitly configured assets, keep them visible as long as they exist.
        if self.configured_balances is not None:
            return asset in self.configured_balances

        _, value, _ = self.get_asset_native_price_and_value(asset, amount)
        if value is None:
            # In auto mode keep the list clean: assets that cannot be valued in the
            # native currency are hidden. This removes tiny/unpriced leftovers such
            # as ACA/ETHW from the default view.
            return False
        return value >= self.min_native_value

    def should_expose_symbol(self, symbol: str) -> bool:
        info = self.symbol_info.get(str(symbol or "").upper())
        if not info:
            return True
        return self.should_expose_asset(info.get("base"))

    def _parse_configured_items(self, items):
        if items is None:
            return None
        cleaned = [item.strip().upper() for item in str(items).split(",") if item.strip()]
        return cleaned or None

    def _get_signature(self, params):
        query_string = "&".join([f"{key}={value}" for key, value in params.items()])
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _api_call(self, method, url, params=None, is_post=False):
        params = dict(params or {})
        try:
            params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
            signature = self._get_signature(params)
            params["signature"] = signature
            headers = {"X-MBX-APIKEY": self.api_key}
            final_url = f"https://api.binance.{self.tld}{url}"

            session = async_get_clientsession(self.hass)
            async with session.request(
                "POST" if is_post else method,
                final_url,
                headers=headers,
                params=params,
            ) as response:
                response.raise_for_status()
                return await response.json()

        except aiohttp.ClientError as err:
            _LOGGER.error("Network error during API call to %s: %s", url, err, exc_info=True)
            raise UpdateFailed(f"Network error: {err}") from err
        except Exception as err:
            _LOGGER.error("Error during API call to %s: %s", url, err, exc_info=True)
            raise UpdateFailed(f"API call error: {err}") from err

    def get_device_info(self, device_type: str, name_suffix: str) -> DeviceInfo:
        identifiers = {(DOMAIN, f"{self.entry.entry_id}-{device_type}")}
        device_info_args = {
            "identifiers": identifiers,
            "manufacturer": "Binance",
            "name": f"{self.conf_name} Binance {name_suffix}",
            "model": f"Binance {name_suffix}",
            "configuration_url": f"https://www.binance.{self.tld}",
            "sw_version": "1.0.8",
            "entry_type": dr.DeviceEntryType.SERVICE,
        }

        if device_type != "account":
            device_info_args["via_device"] = (DOMAIN, f"{self.entry.entry_id}-account")

        return device_info_args

    @property
    def device_info_spot_balances(self) -> DeviceInfo:
        return self.get_device_info("balances", "Spot Balances")

    @property
    def device_info_funding_balances(self) -> DeviceInfo:
        return self.get_device_info("funding", "Funding Balances")

    @property
    def device_info_exchanges(self) -> DeviceInfo:
        return self.get_device_info("exchanges", "Exchanges")

    @property
    def device_info_spot_values(self) -> DeviceInfo:
        return self.get_device_info("values", "Spot Values")

    async def _update_feature_data(self, feature_name, update_method):
        if self.enabled_feature.get(feature_name):
            try:
                await update_method()
            except Exception as err:
                _LOGGER.error("Error updating %s: %s", feature_name, err, exc_info=True)

    async def _async_update_data(self):
        if not self.client:
            await self.init_client()

        try:
            if not self.symbol_info:
                await self.update_exchange_metadata()

            if self.enabled_feature.get("balance"):
                await self.update_balances()
                await self.update_earn_balances()

            await self._update_feature_data("exchanges", self.update_tickers)
            await self._update_feature_data("funding", self.update_funding_balances)

            self._recalculate_total_portfolio_value()
            await self._ensure_dynamic_entities()

            _LOGGER.debug(
                "Binance refresh complete: spot=%s earn=%s funding=%s tickers=%s total=%s",
                len(self.balances),
                len(self.earn_balances),
                len(self.funding_balances),
                len(self.tickers),
                self.total_portfolio_value,
            )

            return {
                "balances": self.balances,
                "earn_balances": self.earn_balances,
                "tickers": self.tickers,
                "funding_balances": self.funding_balances,
                "portfolio_total": self.total_portfolio_value,
            }
        except Exception as err:
            _LOGGER.error("Error updating Binance data: %s", err, exc_info=True)
            raise UpdateFailed(f"Error updating data: {err}") from err

    async def init_client(self):
        if self.client is not None:
            return

        try:
            self.client = await self.hass.async_add_executor_job(
                lambda: Client(self.api_key, self.api_secret, requests_params={"timeout": 30}, tld=self.tld)
            )
        except Exception as err:
            _LOGGER.error("Error initializing Binance client: %s", err, exc_info=True)
            self.client = None
            raise UpdateFailed(f"Could not initialize Binance client: {err}") from err

    async def update_exchange_metadata(self):
        if self.client is None:
            await self.init_client()

        info = await self.hass.async_add_executor_job(self.client.get_exchange_info)
        self.symbol_info = {}
        self.asset_symbols = {}
        for symbol_row in info.get("symbols", []):
            symbol = str(symbol_row.get("symbol", "")).upper()
            base = str(symbol_row.get("baseAsset", "")).upper()
            quote = str(symbol_row.get("quoteAsset", "")).upper()
            status = str(symbol_row.get("status", "")).upper()
            if not symbol or not base or not quote or status != "TRADING":
                continue
            self.symbol_info[symbol] = {"base": base, "quote": quote}
            self.asset_symbols.setdefault(base, set()).add(symbol)
            self.asset_symbols.setdefault(quote, set()).add(symbol)

    async def update_balances(self):
        if self.client is None:
            await self.init_client()

        account_info = await self.hass.async_add_executor_job(self.client.get_account)
        balances = []
        for balance in account_info.get("balances", []):
            asset = str(balance.get("asset", "")).upper()
            free = float(balance.get("free", 0) or 0)
            locked = float(balance.get("locked", 0) or 0)
            if self.configured_balances and asset not in self.configured_balances:
                continue
            if not self.configured_balances and free <= 0 and locked <= 0:
                continue
            balances.append({
                "asset": asset,
                "free": f"{free:.8f}",
                "locked": f"{locked:.8f}",
            })

        self.balances = balances
        _LOGGER.debug("Loaded %s raw spot balances", len(self.balances))

    async def _fetch_simple_earn_positions(self, kind: str):
        if self.client is None:
            await self.init_client()

        if kind == "flexible":
            wrapper_name = "get_simple_earn_flexible_product_position"
            endpoint = ENDPOINT_EARN_FLEXIBLE
        else:
            wrapper_name = "get_simple_earn_locked_product_position"
            endpoint = ENDPOINT_EARN_LOCKED

        wrapper = getattr(self.client, wrapper_name, None)
        if callable(wrapper):
            return await self.hass.async_add_executor_job(lambda: wrapper(size=100))

        return await self._api_call("GET", endpoint, params={"size": 100})

    async def update_earn_balances(self):
        if self.client is None:
            await self.init_client()

        try:
            flexible_resp = await self._fetch_simple_earn_positions("flexible")
            locked_resp = await self._fetch_simple_earn_positions("locked")
        except Exception as err:
            _LOGGER.error(
                "Error fetching Simple Earn balances; Spot entities will stay pure-spot: %s",
                err,
                exc_info=True,
            )
            self.earn_balances = []
            return

        earn_rows = []

        for row in (flexible_resp or {}).get("rows", []):
            asset = str(row.get("asset", "")).upper()
            amount = float(row.get("totalAmount", 0) or 0)
            if not asset or amount <= 0:
                continue
            if self.configured_balances and asset not in self.configured_balances:
                continue
            earn_rows.append({"asset": asset, "free": f"{amount:.8f}", "locked": "0.00000000"})

        for row in (locked_resp or {}).get("rows", []):
            asset = str(row.get("asset", "")).upper()
            amount = float(row.get("amount", 0) or 0)
            if not asset or amount <= 0:
                continue
            if self.configured_balances and asset not in self.configured_balances:
                continue
            earn_rows.append({"asset": asset, "free": f"{amount:.8f}", "locked": "0.00000000"})

        self.earn_balances = earn_rows
        self._merge_earn_into_spot()
        _LOGGER.debug("Loaded %s Simple Earn positions", len(self.earn_balances))

    def _merge_earn_into_spot(self):
        merged = {}

        # Keep the merge phase purely about combining spot + earn balances.
        # Visibility filtering happens later, once prices and conversions are ready.
        for balance in self.balances:
            asset = str(balance.get("asset", "")).upper()
            if not asset or self._is_ld_asset(asset):
                continue
            merged[asset] = {
                "asset": asset,
                "free": float(balance.get("free", 0) or 0),
                "locked": float(balance.get("locked", 0) or 0),
            }

        for balance in self.earn_balances:
            asset = str(balance.get("asset", "")).upper()
            if not asset or self._is_ld_asset(asset):
                continue
            merged.setdefault(asset, {"asset": asset, "free": 0.0, "locked": 0.0})
            merged[asset]["free"] += float(balance.get("free", 0) or 0)
            merged[asset]["locked"] += float(balance.get("locked", 0) or 0)

        self.balances = [
            {
                "asset": asset,
                "free": f"{values['free']:.8f}",
                "locked": f"{values['locked']:.8f}",
            }
            for asset, values in merged.items()
            if values["free"] > 0 or values["locked"] > 0
        ]

    async def update_tickers(self):
        if self.client is None:
            await self.init_client()

        prices = await self.hass.async_add_executor_job(self.client.get_all_tickers)
        price_map = {str(row["symbol"]).upper(): row for row in prices if row.get("symbol") and row.get("price")}
        self.all_prices = price_map

        if self.configured_exchanges:
            wanted = set(self.configured_exchanges)
        else:
            wanted = set()
            for balance in self.balances:
                asset = str(balance.get("asset", "")).upper()
                if asset == self.native_currency:
                    continue
                direct_symbol = f"{asset}{self.native_currency}"
                reverse_symbol = f"{self.native_currency}{asset}"
                if direct_symbol in price_map:
                    wanted.add(direct_symbol)
                elif reverse_symbol in price_map:
                    wanted.add(reverse_symbol)
                elif f"{asset}USDT" in price_map:
                    wanted.add(f"{asset}USDT")
                elif f"USDT{asset}" in price_map:
                    wanted.add(f"USDT{asset}")

        self.tickers = {symbol: price_map[symbol] for symbol in wanted if symbol in price_map}
        self.conversion_cache = {}

    async def update_funding_balances(self):
        if self.client is None:
            await self.init_client()

        try:
            raw_balances = await self.hass.async_add_executor_job(self.client.funding_wallet)
            normalized = []
            for balance in raw_balances:
                if not balance:
                    continue
                asset = str(balance.get("asset", balance.get("coin", ""))).upper()
                free = float(balance.get("free", balance.get("freeAmount", 0)) or 0)
                locked = float(balance.get("locked", 0) or 0)
                if self.configured_balances and asset not in self.configured_balances:
                    continue
                if not self.configured_balances and free <= 0 and locked <= 0:
                    continue
                if self._is_ld_asset(asset):
                    continue
                normalized.append({
                    "asset": asset,
                    "free": f"{free:.8f}",
                    "locked": f"{locked:.8f}",
                })
            self.funding_balances = normalized

        except Exception as err:
            _LOGGER.error("Error during funding call: %s", err, exc_info=True)

    def _get_price_value(self, symbol: str):
        ticker = self.all_prices.get(symbol) or self.tickers.get(symbol)
        if ticker is None:
            return None
        try:
            return float(ticker["price"])
        except (TypeError, ValueError, KeyError):
            return None

    def _find_conversion_rate(self, asset: str, target: str):
        asset = str(asset).upper()
        target = str(target).upper()
        if asset == target:
            return 1.0, [target]

        cache_key = (asset, target)
        if cache_key in self.conversion_cache:
            return self.conversion_cache[cache_key]

        visited = set([asset])
        queue = deque([(asset, 1.0, [asset])])
        while queue:
            current_asset, current_rate, path = queue.popleft()
            for symbol in self.asset_symbols.get(current_asset, set()):
                info = self.symbol_info.get(symbol)
                if not info:
                    continue
                base = info["base"]
                quote = info["quote"]
                price = self._get_price_value(symbol)
                if price is None or price <= 0:
                    continue

                if current_asset == base:
                    next_asset = quote
                    next_rate = current_rate * price
                    next_path = path + [f"{symbol}", next_asset]
                elif current_asset == quote:
                    next_asset = base
                    next_rate = current_rate / price
                    next_path = path + [f"{symbol}(inv)", next_asset]
                else:
                    continue

                if next_asset == target:
                    self.conversion_cache[cache_key] = (next_rate, next_path)
                    return next_rate, next_path

                if next_asset not in visited and len(next_path) <= 9:
                    visited.add(next_asset)
                    queue.append((next_asset, next_rate, next_path))

        self.conversion_cache[cache_key] = (None, None)
        return None, None

    def get_balance_for_asset(self, asset: str, account_type: str = "spot"):
        balances = self.funding_balances if account_type == "funding" else self.balances
        asset = str(asset).upper()
        for balance in balances:
            if str(balance.get("asset", "")).upper() == asset:
                return balance
        return None

    def get_asset_native_price_and_value(self, asset: str, amount: float):
        rate, path = self._find_conversion_rate(asset, self.native_currency)
        if rate is None:
            return None, None, None
        total = round(float(amount) * rate, 8)
        return rate, total, path

    def _recalculate_total_portfolio_value(self):
        total = 0.0
        found = False
        for balance in self.balances:
            amount = float(balance.get("free", 0) or 0) + float(balance.get("locked", 0) or 0)
            if amount <= 0:
                continue
            _, value, _ = self.get_asset_native_price_and_value(balance.get("asset"), amount)
            if value is None:
                continue
            total += value
            found = True
        self.total_portfolio_value = round(total, 8) if found else None

    async def _ensure_dynamic_entities(self):
        if self.async_add_entities is None:
            return

        new_entities = []
        for balance in self.balances:
            asset = str(balance.get("asset", "")).upper()
            if not asset or not self.should_expose_asset(asset):
                continue
            value_uid = f"{self.conf_name}_binance_{asset}_spot_value"
            if value_uid not in self.created_dynamic_entities:
                new_entities.append(BinanceValueSensor(self, asset))
                self.created_dynamic_entities.add(value_uid)

            if self.enabled_feature.get("exchanges") and not self.configured_exchanges:
                for symbol in (f"{asset}{self.native_currency}", f"{self.native_currency}{asset}"):
                    if symbol in self.tickers and self.should_expose_symbol(symbol):
                        ex_uid = f"{self.conf_name}_binance_{symbol}_exchange"
                        if ex_uid not in self.created_dynamic_entities:
                            new_entities.append(BinanceExchangeSensor(self, self.tickers[symbol]))
                            self.created_dynamic_entities.add(ex_uid)
                        break

        total_uid = f"{self.conf_name}_binance_portfolio_total"
        if total_uid not in self.created_dynamic_entities:
            new_entities.append(BinancePortfolioTotalSensor(self))
            self.created_dynamic_entities.add(total_uid)

        if new_entities:
            self.async_add_entities(new_entities, True)

    async def check_sensor_exists(self, entity_id):
        entity_registry = er.async_get(self.hass)
        return entity_registry.async_get(entity_id) is not None

    async def add_new_sensor(self, sensor_data, account_type):
        sensor = BinanceSensor(self, self.conf_name, sensor_data, account_type)
        if self.async_add_entities is not None:
            self.async_add_entities([sensor], True)

    async def universal_transfer(self, type, asset, amount, from_symbol=None, to_symbol=None):
        params = {
            "type": type,
            "asset": asset,
            "amount": amount,
        }
        if from_symbol:
            params["fromSymbol"] = from_symbol
        if to_symbol:
            params["toSymbol"] = to_symbol
        return await self._api_call("POST", "/sapi/v1/asset/transfer", params, is_post=True)

    async def async_config_entry_first_refresh(self):
        try:
            await self.async_refresh()
        except Exception as err:
            _LOGGER.error(
                "Error during first refresh of Binance config entry: %s",
                err,
                exc_info=True,
            )
            raise UpdateFailed(f"Initial data fetch error: {err}") from err
