"""The Yale Doorman L3S integration."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from yalexs_ble import (
    AuthError,
    ConnectionInfo,
    LockInfo,
    LockState,
    PushLock,
    YaleXSBLEError,
    close_stale_connections_by_address,
    local_name_is_unique,
)

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import CALLBACK_TYPE, CoreState, Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

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
    DEVICE_TIMEOUT,
)
from .models import YaleDoormanData

_LOGGER = logging.getLogger(__name__)

type YaleDoormanConfigEntry = ConfigEntry[YaleDoormanData]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.LOCK,
    Platform.SENSOR,
]


def _parse_time(time_str: str) -> time:
    """Parse HH:MM time string."""
    try:
        return datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        return time(0, 0)


async def async_setup_entry(
    hass: HomeAssistant, entry: YaleDoormanConfigEntry
) -> bool:
    """Set up Yale Doorman L3S from a config entry."""
    local_name = entry.data[CONF_LOCAL_NAME]
    address = entry.data[CONF_ADDRESS]
    key = entry.data[CONF_KEY]
    slot = entry.data[CONF_SLOT]
    has_unique_local_name = local_name_is_unique(local_name)
    always_connected = entry.options.get(
        CONF_ALWAYS_CONNECTED, DEFAULT_ALWAYS_CONNECTED
    )

    # Always initialize in passive mode (matches official yalexs_ble integration).
    # This ensures BLE advertisements are always processed correctly.
    # During active hours, we add periodic polling on top.
    push_lock = PushLock(
        local_name, address, None, key, slot, always_connected=False
    )
    id_ = local_name if has_unique_local_name else address
    push_lock.set_name(f"{entry.title} ({id_})")

    # Close any stale connections
    await close_stale_connections_by_address(address)

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update from a BLE callback."""
        push_lock.update_advertisement(
            service_info.device, service_info.advertisement
        )

    shutdown_callback: CALLBACK_TYPE | None = await push_lock.start()

    @callback
    def _async_shutdown(event: Event | None = None) -> None:
        nonlocal shutdown_callback
        if shutdown_callback:
            shutdown_callback()
            shutdown_callback = None

    entry.async_on_unload(_async_shutdown)

    # Check for existing advertisement
    if service_info := _async_find_existing_service_info(
        hass, local_name, address
    ):
        push_lock.update_advertisement(
            service_info.device, service_info.advertisement
        )
    elif hass.state is CoreState.starting:
        raise ConfigEntryNotReady(
            f"{local_name} ({address}) not advertising yet"
        )

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            _bluetooth_callback_matcher(local_name, push_lock.address),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    # Wait for first update from the lock
    try:
        await _async_wait_for_first_update(push_lock, local_name)
    except ConfigEntryAuthFailed:
        raise
    except Exception as ex:
        _LOGGER.error("Failed to get first update: %s", ex)
        raise ConfigEntryNotReady(str(ex)) from ex

    entry.runtime_data = YaleDoormanData(entry.title, push_lock, always_connected)

    # Track device unavailability
    @callback
    def _async_device_unavailable(
        _service_info: bluetooth.BluetoothServiceInfoBleak,
    ) -> None:
        push_lock.reset_advertisement_state()

    entry.async_on_unload(
        bluetooth.async_track_unavailable(
            hass, _async_device_unavailable, push_lock.address
        )
    )

    # Track auth failures for re-auth
    @callback
    def _async_state_changed(
        new_state: LockState,
        lock_info: LockInfo,
        connection_info: ConnectionInfo,
    ) -> None:
        if new_state.auth and not new_state.auth.successful:
            entry.async_start_reauth(hass)

    entry.async_on_unload(push_lock.register_callback(_async_state_changed))

    # Set up active hours scheduling
    _setup_active_hours(hass, entry, push_lock)

    # Forward entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_shutdown)
    )

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


def _setup_active_hours(
    hass: HomeAssistant,
    entry: YaleDoormanConfigEntry,
    push_lock: PushLock,
) -> None:
    """Set up active hours scheduling.

    The PushLock is always initialized with always_connected=False so that
    BLE advertisement processing works correctly at all times (matching the
    official yalexs_ble integration behavior).

    During active hours we add periodic polling via push_lock.update() which
    forces a connect → read state → disconnect cycle every 30 seconds,
    giving near-real-time updates without breaking the library internals.
    """
    if not entry.options.get(CONF_ALWAYS_CONNECTED, DEFAULT_ALWAYS_CONNECTED):
        # Schedule disabled — pure passive mode, identical to official integration
        return

    wd_start_str = entry.options.get(CONF_WEEKDAY_START, DEFAULT_WEEKDAY_START)
    wd_end_str = entry.options.get(CONF_WEEKDAY_END, DEFAULT_WEEKDAY_END)
    we_start_str = entry.options.get(CONF_WEEKEND_START, DEFAULT_WEEKEND_START)
    we_end_str = entry.options.get(CONF_WEEKEND_END, DEFAULT_WEEKEND_END)

    wd_start = _parse_time(wd_start_str)
    wd_end = _parse_time(wd_end_str)
    we_start = _parse_time(we_start_str)
    we_end = _parse_time(we_end_str)

    weekend_days = entry.options.get(CONF_WEEKEND_DAYS, DEFAULT_WEEKEND_DAYS)
    weekend_days = [int(x) for x in weekend_days]

    polling_unsub: CALLBACK_TYPE | None = None
    is_currently_active: bool = False

    async def _async_poll_lock(now: datetime) -> None:
        """Poll the lock for a state update."""
        try:
            await push_lock.update()
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("Scheduled poll failed (will retry): %s", ex)

    def _is_in_active_window(now: datetime) -> bool:
        """Return True if current time falls within the active window."""
        is_weekend = now.weekday() in weekend_days
        start = we_start if is_weekend else wd_start
        end = we_end if is_weekend else wd_end
        current = now.time()
        if start <= end:
            return start <= current < end
        # Spans midnight
        return start <= current or current < end

    @callback
    def _check_schedule(now: datetime) -> None:
        """Check schedule and start/stop polling as needed."""
        nonlocal polling_unsub, is_currently_active

        should_be_active = _is_in_active_window(now)

        if should_be_active and not is_currently_active:
            _LOGGER.info("Entering active hours — starting periodic polling")
            is_currently_active = True
            polling_unsub = async_track_time_interval(
                hass,
                _async_poll_lock,
                timedelta(seconds=30),
            )
            # Trigger an immediate poll
            hass.async_create_task(push_lock.update())

        elif not should_be_active and is_currently_active:
            _LOGGER.info("Exiting active hours — stopping periodic polling")
            is_currently_active = False
            if polling_unsub is not None:
                polling_unsub()
                polling_unsub = None

    # Check every minute
    entry.async_on_unload(
        async_track_time_interval(
            hass, _check_schedule, timedelta(minutes=1)
        )
    )

    # Clean up polling on unload
    @callback
    def _cleanup() -> None:
        nonlocal polling_unsub
        if polling_unsub is not None:
            polling_unsub()
            polling_unsub = None

    entry.async_on_unload(_cleanup)

    # Run immediate check
    _check_schedule(dt_util.now())


async def _async_options_updated(
    hass: HomeAssistant, entry: YaleDoormanConfigEntry
) -> None:
    """Handle options update — reload integration."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_wait_for_first_update(
    push_lock: PushLock, local_name: str
) -> None:
    """Wait for the first update from the push lock."""
    try:
        await push_lock.wait_for_first_update(DEVICE_TIMEOUT)
    except AuthError as ex:
        raise ConfigEntryAuthFailed(str(ex)) from ex
    except (YaleXSBLEError, TimeoutError) as ex:
        raise ConfigEntryNotReady(
            f"{ex}; Try moving the Bluetooth adapter closer to {local_name}"
        ) from ex


@callback
def _async_find_existing_service_info(
    hass: HomeAssistant, local_name: str, address: str
) -> bluetooth.BluetoothServiceInfoBleak | None:
    """Find existing service info for the lock."""
    return bluetooth.async_last_service_info(hass, address, connectable=True)


def _bluetooth_callback_matcher(
    local_name: str, address: str
) -> bluetooth.BluetoothCallbackMatcher:
    """Create a Bluetooth callback matcher."""
    # Match exclusively by MAC address.
    # We do not specify connectable=True/False so we receive ALL packets
    # (both connectable and non-connectable scan responses).
    return bluetooth.BluetoothCallbackMatcher(address=address)


async def async_unload_entry(
    hass: HomeAssistant, entry: YaleDoormanConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
