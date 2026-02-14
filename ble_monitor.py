"""BLE communication module for Yale Doorman L3S.

Uses the yalexs-ble PushLock class for event-driven BLE communication
with automatic disconnect/reconnect to save battery.

Key integration detail: PushLock expects to receive BLEDevice and
AdvertisementData from the platform's Bluetooth stack (normally Home
Assistant). We use a BleakScanner to discover the lock and continuously
feed advertisement updates to PushLock via update_advertisement().
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from yalexs_ble import PushLock, LockState, LockInfo, ConnectionInfo
from yalexs_ble.const import (
    LockStatus,
    DoorStatus,
    BatteryState,
    AutoLockState,
    AutoLockMode,
    YALE_MFR_ID,
    COMMAND_SERVICE_UUID,
)

from config import Config
from state import StateManager

_LOGGER = logging.getLogger(__name__)

# Map yalexs-ble LockStatus to simple strings
LOCK_STATUS_MAP = {
    LockStatus.LOCKED: "locked",
    LockStatus.UNLOCKED: "unlocked",
    LockStatus.LOCKING: "locking",
    LockStatus.UNLOCKING: "unlocking",
    LockStatus.JAMMED: "jammed",
    LockStatus.SECUREMODE: "locked",
    LockStatus.UNKNOWN: "unknown",
    LockStatus.UNKNOWN_01: "calibrating",
    LockStatus.UNKNOWN_06: "unknown",
}

# Map yalexs-ble DoorStatus to simple strings
DOOR_STATUS_MAP = {
    DoorStatus.CLOSED: "closed",
    DoorStatus.OPENED: "open",
    DoorStatus.AJAR: "ajar",
    DoorStatus.UNKNOWN: "unknown",
    DoorStatus.UNKNOWN_04: "unknown",
}


def _is_yale_device(device: BLEDevice, adv: AdvertisementData) -> bool:
    """Check if a BLE device is a Yale/August lock."""
    if adv.service_uuids and COMMAND_SERVICE_UUID in adv.service_uuids:
        return True
    if adv.manufacturer_data and YALE_MFR_ID in adv.manufacturer_data:
        return True
    name = device.name or adv.local_name or ""
    if name.startswith(("Aug-", "Yale-", "YD-")):
        return True
    return False


async def scan_for_yale_locks(timeout: float = 15.0) -> list[dict]:
    """Scan for Yale/August BLE devices.

    Returns a list of discovered lock devices.
    """
    _LOGGER.info("Scanning for Yale BLE devices (%0.0fs)...", timeout)
    found = []

    def detection_callback(device: BLEDevice, adv: AdvertisementData):
        if _is_yale_device(device, adv):
            name = device.name or adv.local_name or "Unknown"
            info = {
                "address": device.address,
                "name": name,
                "rssi": adv.rssi or 0,
                "service_uuids": list(adv.service_uuids) if adv.service_uuids else [],
            }
            # Avoid duplicates
            if not any(f["address"] == info["address"] for f in found):
                found.append(info)
                _LOGGER.info(
                    "  Found: %s (%s) RSSI: %d",
                    info["name"],
                    info["address"],
                    info["rssi"],
                )

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()

    _LOGGER.info("Scan complete. Found %d Yale device(s)", len(found))
    return found


class YaleBLEMonitor:
    """BLE monitor for Yale Doorman L3S lock.

    Uses yalexs-ble PushLock for event-driven updates with
    automatic disconnect/reconnect to conserve battery.

    Important: PushLock needs advertisement data fed to it via
    update_advertisement() so that connection_info (RSSI etc.)
    is available when callbacks fire. We run a BleakScanner
    continuously to provide this.
    """

    def __init__(self, config: Config, state_manager: StateManager):
        self._config = config
        self._state = state_manager
        self._push_lock: PushLock | None = None
        self._cancel_push_lock: Callable | None = None
        self._scanner: BleakScanner | None = None
        self._running = False
        self._activity_callbacks: list[Callable] = []
        self._device_found = False

    def register_activity_callback(self, callback: Callable) -> None:
        """Register a callback for when activity is detected."""
        self._activity_callbacks.append(callback)

    def _notify_activity(self) -> None:
        """Notify all activity callbacks."""
        for cb in self._activity_callbacks:
            try:
                cb()
            except Exception as e:
                _LOGGER.error("Activity callback error: %s", e)

    def _on_state_change(
        self,
        lock_state: LockState,
        lock_info: LockInfo | None,
        conn_info: ConnectionInfo | None,
    ) -> None:
        """Handle state change from PushLock."""
        _LOGGER.debug(
            "State change received - lock: %s, door: %s, battery: %s",
            lock_state.lock if lock_state else None,
            lock_state.door if lock_state else None,
            lock_state.battery if lock_state else None,
        )

        changed = False

        if lock_state.lock is not None:
            status_str = LOCK_STATUS_MAP.get(lock_state.lock, "unknown")
            if self._state.update_lock_state(status_str, source="notification"):
                changed = True

        if lock_state.door is not None:
            status_str = DOOR_STATUS_MAP.get(lock_state.door, "unknown")
            if self._state.update_door_state(status_str, source="notification"):
                changed = True

        if lock_state.battery is not None:
            if self._state.update_battery(
                lock_state.battery.percentage,
                lock_state.battery.voltage,
                source="notification",
            ):
                changed = True

        if lock_state.auto_lock is not None:
            enabled = lock_state.auto_lock.mode != AutoLockMode.OFF
            self._state.update_auto_lock(enabled, lock_state.auto_lock.duration)

        if lock_state.auth is not None:
            if not lock_state.auth.successful:
                _LOGGER.warning("BLE authentication failed!")

        if lock_info is not None:
            self._state.update_lock_info(
                model=lock_info.model or "",
                serial=lock_info.serial or "",
                firmware=lock_info.firmware or "",
            )

        if conn_info is not None:
            self._state.update_connection(True, conn_info.rssi)

        if changed:
            self._notify_activity()

    def _matches_our_lock(self, device: BLEDevice, adv: AdvertisementData) -> bool:
        """Check if a discovered device matches our configured lock."""
        address = self._config.lock_address
        name = self._config.lock_name

        if address and device.address.upper() == address.upper():
            return True
        if name:
            device_name = device.name or adv.local_name or ""
            if device_name == name:
                return True
        return False

    def _on_advertisement(self, device: BLEDevice, adv: AdvertisementData) -> None:
        """Handle BLE advertisement from scanner.

        Feeds matching advertisements to PushLock so it has
        up-to-date BLEDevice and AdvertisementData (needed for
        connection_info / RSSI).
        """
        if not self._push_lock or not self._running:
            return

        if not self._matches_our_lock(device, adv):
            return

        # Feed advertisement to PushLock — this sets _ble_device,
        # _advertisement_data, and triggers state updates if needed
        self._push_lock.update_advertisement(device, adv)

        if not self._device_found:
            self._device_found = True
            _LOGGER.info(
                "Lock advertisement received: %s (%s) RSSI: %d",
                device.name or adv.local_name,
                device.address,
                adv.rssi or 0,
            )

    async def start(self) -> None:
        """Start monitoring the lock via BLE.

        1. Creates PushLock with key/address
        2. Starts a BleakScanner that feeds advertisements to PushLock
        3. Starts PushLock which will connect on first advertisement
        """
        if not self._config.lock_key:
            _LOGGER.error(
                "No BLE key configured. Run with --auth-only first to obtain keys."
            )
            return

        _LOGGER.info(
            "Starting BLE monitor for lock (name=%s, address=%s)",
            self._config.lock_name or "auto",
            self._config.lock_address or "auto",
        )

        self._push_lock = PushLock(
            local_name=self._config.lock_name or None,
            address=self._config.lock_address or None,
            key=self._config.lock_key,
            key_index=self._config.lock_key_index,
            idle_disconnect_delay=self._config.idle_disconnect_delay,
            always_connected=self._config.always_connected,
        )

        # Register our state change callback
        self._push_lock.register_callback(self._on_state_change)

        # Start the advertisement scanner — this continuously feeds
        # BLEDevice + AdvertisementData to PushLock via update_advertisement()
        self._scanner = BleakScanner(
            detection_callback=self._on_advertisement,
        )
        await self._scanner.start()

        # Start PushLock (it will use get_device() to find the BLE device,
        # then schedule an update)
        self._cancel_push_lock = await self._push_lock.start()
        self._running = True
        self._state.update_connection(False)

        _LOGGER.info("BLE monitor started, waiting for lock advertisements...")

    async def stop(self) -> None:
        """Stop monitoring."""
        self._running = False

        # Cancel PushLock (uses the cancel callback, not .stop())
        if self._cancel_push_lock:
            self._cancel_push_lock()
            self._cancel_push_lock = None

        # Stop the advertisement scanner
        if self._scanner:
            try:
                await self._scanner.stop()
            except Exception as e:
                _LOGGER.debug("Scanner stop error (expected): %s", e)
            self._scanner = None

        # Disconnect PushLock
        if self._push_lock:
            try:
                await self._push_lock._execute_forced_disconnect("shutdown")
            except Exception as e:
                _LOGGER.debug("Disconnect error: %s", e)
            self._push_lock = None

        self._device_found = False
        self._state.update_connection(False)
        _LOGGER.info("BLE monitor stopped")

    async def poll_state(self) -> None:
        """Manually request a state update from the lock.

        This triggers a connect → read → disconnect cycle.
        """
        if self._push_lock and self._running:
            _LOGGER.debug("Initiating poll update...")
            try:
                await self._push_lock.update()
            except Exception as e:
                _LOGGER.warning("Poll update failed: %s", e)
                self._state.update_connection(False)

    @property
    def is_connected(self) -> bool:
        """Check if currently connected to the lock."""
        if self._push_lock:
            return self._push_lock.is_connected
        return False

    @property
    def lock_state(self) -> LockState | None:
        """Get the current lock state from PushLock."""
        if self._push_lock:
            return self._push_lock.lock_state
        return None

    def get_diagnostics(self) -> dict:
        """Get diagnostic info about the BLE connection."""
        return {
            "running": self._running,
            "connected": self.is_connected,
            "device_found": self._device_found,
            "lock_name": self._push_lock.name if self._push_lock else None,
            "lock_address": self._push_lock.address if self._push_lock else None,
        }
