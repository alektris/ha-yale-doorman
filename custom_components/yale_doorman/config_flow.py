"""Config flow for the Yale Doorman L3S integration."""
from __future__ import annotations
import logging
import re
from typing import Any
import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from .const import (
    CONF_ALWAYS_CONNECTED,
    CONF_KEY,
    CONF_LOCAL_NAME,
    CONF_SLOT,
    CONF_WEEKDAY_END,
    CONF_WEEKDAY_START,
    CONF_WEEKEND_DAYS,
    CONF_WEEKEND_END,
    CONF_WEEKEND_START,
    DEFAULT_ALWAYS_CONNECTED,
    DEFAULT_WEEKDAY_END,
    DEFAULT_WEEKDAY_START,
    DEFAULT_WEEKEND_DAYS,
    DEFAULT_WEEKEND_END,
    DEFAULT_WEEKEND_START,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
MAC_REGEX = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
HEX_KEY_REGEX = re.compile(r"^[0-9A-Fa-f]{32}$")
TIME_REGEX = re.compile(r"^\d{1,2}:\d{2}$")

class YaleDoormanConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_key: str | None = None
        self._discovered_slot: int = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> YaleDoormanOptionsFlow:
        return YaleDoormanOptionsFlow(config_entry)

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        """Handle bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info

        # Try to retrieve key from yalexs_ble config cache
        key, slot = self._try_get_key_from_cache(discovery_info.address)
        if key:
            self._discovered_key = key
            self._discovered_slot = slot
            _LOGGER.debug("Found key in yalexs_ble cache for %s", discovery_info.address)

        self.context["title_placeholders"] = {
            "name": discovery_info.name,
            "address": discovery_info.address,
        }
        return await self.async_step_user()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial setup step."""
        if user_input is not None and CONF_ADDRESS in user_input:
            if user_input[CONF_ADDRESS] == "manual":
                return await self.async_step_manual()

            address = user_input[CONF_ADDRESS]
            for discovery in async_discovered_service_info(self.hass):
                if discovery.address == address:
                    self._discovery_info = discovery
                    break

            # Check cache for key
            key, slot = self._try_get_key_from_cache(address)
            if key:
                self._discovered_key = key
                self._discovered_slot = slot

            return await self.async_step_manual()

        if self._discovery_info:
             return await self.async_step_manual()

        # Scan for devices
        devices = {}
        for discovery in async_discovered_service_info(self.hass):
            if (
                465 in discovery.manufacturer_data
                or "0000fe24-0000-1000-8000-00805f9b34fb" in discovery.service_uuids
            ):
                devices[discovery.address] = f"{discovery.name} ({discovery.address})"

        if not devices:
            return await self.async_step_manual()

        devices["manual"] = "Enter Manually"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(devices)}),
            description_placeholders={},
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle manual entry."""
        errors: dict[str, str] = {}
        default_address, default_name, default_key, default_slot = "", "", "", 1

        if self._discovery_info:
            default_address = self._discovery_info.address
            default_name = self._discovery_info.name
        if self._discovered_key:
            default_key = self._discovered_key
        if self._discovered_slot:
            default_slot = self._discovered_slot

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            if not MAC_REGEX.match(address):
                errors[CONF_ADDRESS] = "invalid_mac"
            key = user_input[CONF_KEY].strip().lower()
            if not HEX_KEY_REGEX.match(key):
                errors[CONF_KEY] = "invalid_key"
            slot = user_input[CONF_SLOT]
            if slot < 0 or slot > 255:
                errors[CONF_SLOT] = "invalid_slot"

            if not errors:
                local_name = user_input.get(CONF_LOCAL_NAME, "").strip()
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                title = local_name or f"Yale Doorman ({address[-8:]})"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_ADDRESS: address,
                        CONF_LOCAL_NAME: local_name,
                        CONF_KEY: key,
                        CONF_SLOT: slot,
                    },
                    options={
                        CONF_ALWAYS_CONNECTED: DEFAULT_ALWAYS_CONNECTED,
                        CONF_WEEKDAY_START: DEFAULT_WEEKDAY_START,
                        CONF_WEEKDAY_END: DEFAULT_WEEKDAY_END,
                        CONF_WEEKEND_START: DEFAULT_WEEKEND_START,
                        CONF_WEEKEND_END: DEFAULT_WEEKEND_END,
                        CONF_WEEKEND_DAYS: DEFAULT_WEEKEND_DAYS,
                    },
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS, default=default_address): str,
                vol.Optional(CONF_LOCAL_NAME, default=default_name): str,
                vol.Required(CONF_KEY, default=default_key): str,
                vol.Required(CONF_SLOT, default=default_slot): int,
            }),
            errors=errors,
            description_placeholders={"name": default_name, "address": default_address},
        )

    def _try_get_key_from_cache(self, address: str) -> tuple[str | None, int]:
        try:
            from homeassistant.components.yalexs_ble.config_cache import async_get_validated_config
            if config := async_get_validated_config(self.hass, address):
                return config.key, config.slot
        except ImportError:
            pass
        except Exception as ex:
            _LOGGER.debug("Error retrieving key from yalexs_ble cache: %s", ex)
        return None, 1

class YaleDoormanOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        weekend_options = [
            {"value": "0", "label": "Monday"},
            {"value": "1", "label": "Tuesday"},
            {"value": "2", "label": "Wednesday"},
            {"value": "3", "label": "Thursday"},
            {"value": "4", "label": "Friday"},
            {"value": "5", "label": "Saturday"},
            {"value": "6", "label": "Sunday"},
        ]

        # Use self.config_entry (standard)
        current_weekend_days = self.config_entry.options.get(
            CONF_WEEKEND_DAYS, DEFAULT_WEEKEND_DAYS
        )
        # Ensure defaults are strings for the selector
        current_weekend_days = [str(x) for x in current_weekend_days]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ALWAYS_CONNECTED,
                        default=self.config_entry.options.get(
                            CONF_ALWAYS_CONNECTED, DEFAULT_ALWAYS_CONNECTED
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_WEEKEND_DAYS,
                        default=current_weekend_days,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=weekend_options,
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_WEEKDAY_START,
                        default=self.config_entry.options.get(
                            CONF_WEEKDAY_START, DEFAULT_WEEKDAY_START
                        ),
                    ): str,
                    vol.Required(
                        CONF_WEEKDAY_END,
                        default=self.config_entry.options.get(
                            CONF_WEEKDAY_END, DEFAULT_WEEKDAY_END
                        ),
                    ): str,
                    vol.Required(
                        CONF_WEEKEND_START,
                        default=self.config_entry.options.get(
                            CONF_WEEKEND_START, DEFAULT_WEEKEND_START
                        ),
                    ): str,
                    vol.Required(
                        CONF_WEEKEND_END,
                        default=self.config_entry.options.get(
                            CONF_WEEKEND_END, DEFAULT_WEEKEND_END
                        ),
                    ): str,
                }
            ),
        )
