
"""Binance integration setup."""

from __future__ import annotations

import logging

from binance.exceptions import BinanceAPIException

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .constants import (
    DOMAIN,
    SERVICE_WITHDRAW,
    UNDO_UPDATE_LISTENER,
    CONF_BALANCES,
    CONF_EXCHANGES,
)
from .coordinator import BinanceCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Binance integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_update_options(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload the config entry when options are updated."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Binance from a config entry."""
    _LOGGER.debug("Setting up Binance config entry %s", entry.entry_id)

    data = hass.data.setdefault(DOMAIN, {})

    undo_listener = entry.add_update_listener(async_update_options)
    data[entry.entry_id] = {UNDO_UPDATE_LISTENER: undo_listener}

    coordinator = BinanceCoordinator(
        hass,
        entry,
        configured_balances=(entry.options.get(CONF_BALANCES) if entry.options else None) or entry.data.get(CONF_BALANCES),
        configured_exchanges=(entry.options.get(CONF_EXCHANGES) if entry.options else None) or entry.data.get(CONF_EXCHANGES),
    )

    await coordinator.async_config_entry_first_refresh()
    data[entry.entry_id] = coordinator

    async def handle_withdraw_service(call: ServiceCall) -> None:
        """Handle a withdrawal service call."""
        entity_id = call.data.get("entity_id")
        entity_registry = er.async_get(hass)

        entity_entry = entity_registry.entities.get(entity_id)
        if entity_entry is None:
            _LOGGER.error("Entity not found for ID: %s", entity_id)
            return

        coordinator_for_entity = hass.data[DOMAIN].get(entity_entry.config_entry_id)
        if not coordinator_for_entity:
            _LOGGER.error(
                "Coordinator not found for entry_id: %s", entity_entry.config_entry_id
            )
            return

        currency = getattr(entity_entry, "unit_of_measurement", None)
        account_type = getattr(entity_entry, "account_type", "spot")
        amount = call.data.get("amount")
        address = call.data.get("address")
        name = call.data.get("name")
        address_tag = call.data.get("address_tag")

        if not currency:
            _LOGGER.error("Unable to determine currency for entity %s", entity_id)
            return

        api_params = {
            "coin": currency,
            "amount": amount,
            "address": address,
        }

        api_params["walletType"] = 0 if account_type == "spot" else 1

        if name is not None:
            api_params["name"] = name
        if address_tag is not None:
            api_params["addressTag"] = address_tag

        try:
            result = await hass.async_add_executor_job(
                lambda: coordinator_for_entity.client.withdraw(**api_params)
            )
            _LOGGER.info("Withdrawal succeeded: %s", result)
        except BinanceAPIException as err:
            _LOGGER.error("Binance API error during withdrawal: %s", err)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Unexpected withdrawal error: %s", err, exc_info=True)

    if "withdraw_service_registered" not in data:
        hass.services.async_register(
            DOMAIN, SERVICE_WITHDRAW, handle_withdraw_service
        )
        data["withdraw_service_registered"] = True

    try:
        device_registry = dr.async_get(hass)
        device_info = coordinator.get_device_info("account", "Account")

        device_registry.async_get_or_create(
            config_entry_id=coordinator.entry.entry_id,
            identifiers=device_info["identifiers"],
            manufacturer=device_info["manufacturer"],
            name=device_info["name"],
            model=device_info["model"],
            configuration_url=device_info["configuration_url"],
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error registering Binance Account device: %s", err)

    name = entry.data.get(CONF_NAME, "Binance")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Successfully set up Binance config entry: %s", name)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if unload_ok:
            undo_listener = hass.data[DOMAIN].get(entry.entry_id)
            if isinstance(undo_listener, dict):
                listener = undo_listener.get(UNDO_UPDATE_LISTENER)
                if listener:
                    listener()
            hass.data[DOMAIN].pop(entry.entry_id, None)
        return unload_ok
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error unloading Binance config entry: %s", err)
        return False
