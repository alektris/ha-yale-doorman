"""Config flow for the Yale Doorman L3S integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import (
    CONF_ACTIVE_HOURS_END,
    CONF_ACTIVE_HOURS_START,
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_ALWAYS_CONNECTED,
    CONF_IDLE_POLL_INTERVAL,
    CONF_KEY,
    CONF_LOCAL_NAME,
    CONF_SLOT,
    DEFAULT_ACTIVE_HOURS_END,
    DEFAULT_ACTIVE_HOURS_START,
    DEFAULT_ACTIVE_POLL_INTERVAL,
    DEFAULT_ALWAYS_CONNECTED,
    DEFAULT_IDLE_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

MAC_REGEX = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
HEX_KEY_REGEX = re.compile(r"^[0-9A-Fa-f]{32}$")
TIME_REGEX = re.compile(r"^\d{1,2}:\d{2}$")


class YaleDoormanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Yale Doorman L3S."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> YaleDoormanOptionsFlow:
        """Get the options flow handler."""
        return YaleDoormanOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate BLE address
            address = user_input[CONF_ADDRESS].strip().upper()
            if not MAC_REGEX.match(address):
                errors[CONF_ADDRESS] = "invalid_mac"

            # Validate BLE key
            key = user_input[CONF_KEY].strip().lower()
            if not HEX_KEY_REGEX.match(key):
                errors[CONF_KEY] = "invalid_key"

            # Validate slot
            slot = user_input[CONF_SLOT]
            if slot < 0 or slot > 255:
                errors[CONF_SLOT] = "invalid_slot"

            if not errors:
                local_name = user_input.get(CONF_LOCAL_NAME, "").strip()

                # Check for duplicate entries
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
                        CONF_ACTIVE_HOURS_START: DEFAULT_ACTIVE_HOURS_START,
                        CONF_ACTIVE_HOURS_END: DEFAULT_ACTIVE_HOURS_END,
                        CONF_ACTIVE_POLL_INTERVAL: DEFAULT_ACTIVE_POLL_INTERVAL,
                        CONF_IDLE_POLL_INTERVAL: DEFAULT_IDLE_POLL_INTERVAL,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_LOCAL_NAME, default=""): str,
                    vol.Required(CONF_KEY): str,
                    vol.Required(CONF_SLOT, default=1): int,
                }
            ),
            errors=errors,
        )


class YaleDoormanOptionsFlow(OptionsFlow):
    """Options flow for Yale Doorman L3S."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate time format
            start = user_input.get(
                CONF_ACTIVE_HOURS_START, DEFAULT_ACTIVE_HOURS_START
            )
            end = user_input.get(
                CONF_ACTIVE_HOURS_END, DEFAULT_ACTIVE_HOURS_END
            )
            if not TIME_REGEX.match(start):
                errors[CONF_ACTIVE_HOURS_START] = "invalid_time"
            if not TIME_REGEX.match(end):
                errors[CONF_ACTIVE_HOURS_END] = "invalid_time"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ALWAYS_CONNECTED,
                        default=current.get(
                            CONF_ALWAYS_CONNECTED,
                            DEFAULT_ALWAYS_CONNECTED,
                        ),
                    ): bool,
                    vol.Required(
                        CONF_ACTIVE_HOURS_START,
                        default=current.get(
                            CONF_ACTIVE_HOURS_START,
                            DEFAULT_ACTIVE_HOURS_START,
                        ),
                    ): str,
                    vol.Required(
                        CONF_ACTIVE_HOURS_END,
                        default=current.get(
                            CONF_ACTIVE_HOURS_END,
                            DEFAULT_ACTIVE_HOURS_END,
                        ),
                    ): str,
                    vol.Required(
                        CONF_ACTIVE_POLL_INTERVAL,
                        default=current.get(
                            CONF_ACTIVE_POLL_INTERVAL,
                            DEFAULT_ACTIVE_POLL_INTERVAL,
                        ),
                    ): vol.All(int, vol.Range(min=30, max=3600)),
                    vol.Required(
                        CONF_IDLE_POLL_INTERVAL,
                        default=current.get(
                            CONF_IDLE_POLL_INTERVAL,
                            DEFAULT_IDLE_POLL_INTERVAL,
                        ),
                    ): vol.All(int, vol.Range(min=300, max=7200)),
                }
            ),
            errors=errors,
        )
