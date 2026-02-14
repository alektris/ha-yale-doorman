"""Lock platform for the Yale Doorman L3S integration."""

from __future__ import annotations

from typing import Any

from yalexs_ble import ConnectionInfo, LockInfo, LockState, LockStatus

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import YaleDoormanConfigEntry
from .entity import YaleDoormanEntity
from .models import YaleDoormanData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleDoormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Yale Doorman lock entities."""
    async_add_entities([YaleDoormanLock(entry.runtime_data)])


class YaleDoormanLock(YaleDoormanEntity, LockEntity):
    """Yale Doorman L3S lock entity."""

    _attr_name = None  # Use device name

    @callback
    def _async_update_state(
        self,
        new_state: LockState,
        lock_info: LockInfo,
        connection_info: ConnectionInfo,
    ) -> None:
        """Update the lock state."""
        self._attr_is_locked = False
        self._attr_is_locking = False
        self._attr_is_unlocking = False
        self._attr_is_jammed = False

        lock_state = new_state.lock

        if lock_state is LockStatus.LOCKED:
            self._attr_is_locked = True
        elif lock_state is LockStatus.LOCKING:
            self._attr_is_locking = True
        elif lock_state is LockStatus.UNLOCKING:
            self._attr_is_unlocking = True
        elif lock_state is LockStatus.SECUREMODE:
            self._attr_is_locked = True
        elif lock_state in (
            LockStatus.UNKNOWN_01,
            LockStatus.UNKNOWN_06,
            LockStatus.JAMMED,
        ):
            self._attr_is_jammed = True
        elif lock_state is LockStatus.UNKNOWN:
            self._attr_is_locked = None

        super()._async_update_state(new_state, lock_info, connection_info)

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the lock."""
        await self._device.lock()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock."""
        await self._device.unlock()
