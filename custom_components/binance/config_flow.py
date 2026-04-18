"""Config flow for Binance."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .constants import (
    DOMAIN,
    CONF_API_SECRET,
    CONF_DOMAIN,
    CONF_NATIVE_CURRENCY,
    CONF_BALANCES,
    CONF_EXCHANGES,
    CONF_ENABLE_BALANCES,
    CONF_ENABLE_EXCHANGES,
    CONF_ENABLE_FUNDING,
    CONF_ENABLE_EARN,
    CONF_MIN_NATIVE_VALUE,
    DEFAULT_MIN_NATIVE_VALUE,
)


def _normalize_csv(value: str | None) -> str:
    if not value:
        return ""
    items = [item.strip().upper() for item in str(value).split(",") if item.strip()]
    return ",".join(items)


def _normalize_min_native_value(value) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return DEFAULT_MIN_NATIVE_VALUE
    return max(0.0, round(numeric, 8))


USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_API_KEY): cv.string,
        vol.Required(CONF_API_SECRET): cv.string,
        vol.Required(CONF_DOMAIN, default="com"): cv.string,
        vol.Optional(CONF_NATIVE_CURRENCY, default="EUR"): cv.string,
        vol.Optional(CONF_ENABLE_BALANCES, default=True): cv.boolean,
        vol.Optional(CONF_ENABLE_EXCHANGES, default=True): cv.boolean,
        vol.Optional(CONF_ENABLE_FUNDING, default=False): cv.boolean,
        vol.Optional(CONF_ENABLE_EARN, default=False): cv.boolean,
        vol.Optional(CONF_MIN_NATIVE_VALUE, default=DEFAULT_MIN_NATIVE_VALUE): vol.Coerce(float),
    }
)


class BinanceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_NAME])
            self._abort_if_unique_id_configured()
            self.context["user_input"] = user_input
            if user_input.get(CONF_ENABLE_BALANCES):
                return await self.async_step_balances()
            if user_input.get(CONF_ENABLE_EXCHANGES):
                return await self.async_step_exchanges()
            return self.async_create_entry(title=user_input[CONF_NAME], data=self.context["user_input"])
        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    async def async_step_balances(self, user_input=None):
        errors = {}
        if user_input is not None:
            self.context["user_input"][CONF_BALANCES] = _normalize_csv(user_input.get(CONF_BALANCES))
            if self.context["user_input"].get(CONF_ENABLE_EXCHANGES):
                return await self.async_step_exchanges()
            return self.async_create_entry(title=self.context["user_input"][CONF_NAME], data=self.context["user_input"])
        return self.async_show_form(
            step_id="balances",
            data_schema=vol.Schema({vol.Optional(CONF_BALANCES, default=""): cv.string}),
            errors=errors,
        )

    async def async_step_exchanges(self, user_input=None):
        errors = {}
        if user_input is not None:
            self.context["user_input"][CONF_EXCHANGES] = _normalize_csv(user_input.get(CONF_EXCHANGES))
            return self.async_create_entry(title=self.context["user_input"][CONF_NAME], data=self.context["user_input"])
        return self.async_show_form(
            step_id="exchanges",
            data_schema=vol.Schema({vol.Optional(CONF_EXCHANGES, default=""): cv.string}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BinanceOptionsFlowHandler()


class BinanceOptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        current_config = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            cleaned = {
                CONF_DOMAIN: str(user_input.get(CONF_DOMAIN, current_config.get(CONF_DOMAIN, "com")) or "com").strip(),
                CONF_NATIVE_CURRENCY: str(user_input.get(CONF_NATIVE_CURRENCY, current_config.get(CONF_NATIVE_CURRENCY, "EUR")) or "EUR").strip().upper(),
                CONF_ENABLE_BALANCES: bool(user_input.get(CONF_ENABLE_BALANCES, current_config.get(CONF_ENABLE_BALANCES, True))),
                CONF_BALANCES: _normalize_csv(user_input.get(CONF_BALANCES)),
                CONF_ENABLE_EXCHANGES: bool(user_input.get(CONF_ENABLE_EXCHANGES, current_config.get(CONF_ENABLE_EXCHANGES, True))),
                CONF_EXCHANGES: _normalize_csv(user_input.get(CONF_EXCHANGES)),
                CONF_ENABLE_FUNDING: bool(user_input.get(CONF_ENABLE_FUNDING, current_config.get(CONF_ENABLE_FUNDING, False))),
                CONF_ENABLE_EARN: bool(user_input.get(CONF_ENABLE_EARN, current_config.get(CONF_ENABLE_EARN, False))),
                CONF_MIN_NATIVE_VALUE: _normalize_min_native_value(user_input.get(CONF_MIN_NATIVE_VALUE, current_config.get(CONF_MIN_NATIVE_VALUE, DEFAULT_MIN_NATIVE_VALUE))),
            }
            return self.async_create_entry(title="", data=cleaned)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_DOMAIN, default=str(current_config.get(CONF_DOMAIN, "com") or "com")): cv.string,
                vol.Required(CONF_NATIVE_CURRENCY, default=str(current_config.get(CONF_NATIVE_CURRENCY, "EUR") or "EUR").upper()): cv.string,
                vol.Optional(CONF_ENABLE_BALANCES, default=bool(current_config.get(CONF_ENABLE_BALANCES, True))): cv.boolean,
                vol.Optional(CONF_BALANCES, default=str(current_config.get(CONF_BALANCES, "") or "")): cv.string,
                vol.Optional(CONF_ENABLE_EXCHANGES, default=bool(current_config.get(CONF_ENABLE_EXCHANGES, True))): cv.boolean,
                vol.Optional(CONF_EXCHANGES, default=str(current_config.get(CONF_EXCHANGES, "") or "")): cv.string,
                vol.Optional(CONF_ENABLE_FUNDING, default=bool(current_config.get(CONF_ENABLE_FUNDING, False))): cv.boolean,
                vol.Optional(CONF_ENABLE_EARN, default=bool(current_config.get(CONF_ENABLE_EARN, False))): cv.boolean,
                vol.Optional(CONF_MIN_NATIVE_VALUE, default=float(current_config.get(CONF_MIN_NATIVE_VALUE, DEFAULT_MIN_NATIVE_VALUE))): vol.Coerce(float),
            }),
            errors={},
        )
