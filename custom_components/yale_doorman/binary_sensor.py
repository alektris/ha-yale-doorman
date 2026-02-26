"""Binary sensor platform for the Yale Doorman L3S integration."""

from __future__ import annotations

from yalexs_ble import ConnectionInfo, DoorStatus, LockInfo, LockState

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up Yale Doorman binary sensor entities."""
    data = entry.runtime_data
    lock = data.lock

    entities: list[YaleDoormanEntity] = []

    # Door sensor — only add if lock reports door sense capability
    if lock.lock_info and lock.lock_info.door_sense:
        entities.append(YaleDoormanDoorSensor(data))

    # Connectivity sensor — tells if the integration thinks it's in range/connected
    entities.append(YaleDoormanConnectivitySensor(data))

    async_add_entities(entities)


class YaleDoormanDoorSensor(YaleDoormanEntity, BinarySensorEntity):
    """Yale Doorman door open/closed sensor."""

    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_translation_key = "door"

    def __init__(self, data: YaleDoormanData) -> None:
        """Initialize the door sensor."""
        super().__init__(data)
        self._attr_unique_id = f"{self._device.address}_door"

    @callback
    def _async_update_state(
        self,
        new_state: LockState,
        lock_info: LockInfo,
        connection_info: ConnectionInfo,
    ) -> None:
        """Update the door state."""
        self._attr_is_on = new_state.door in (
            DoorStatus.OPENED,
            DoorStatus.AJAR,
        )
        super()._async_update_state(new_state, lock_info, connection_info)


class YaleDoormanConnectivitySensor(YaleDoormanEntity, BinarySensorEntity):
    """Yale Doorman Bluetooth connectivity sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "connectivity"

    def __init__(self, data: YaleDoormanData) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(data)
        self._attr_unique_id = f"{self._device.address}_connectivity"

    @property
    def available(self) -> bool:
        """Always available so it can show disconnected state."""
        return True

    @property
    def is_on(self) -> bool:
        """Return true if the lock is reachable (available)."""
        return self._attr_available

    @callback
    def _async_update_state(
        self,
        new_state: LockState,
        lock_info: LockInfo,
        connection_info: ConnectionInfo,
    ) -> None:
        """Update the connectivity state."""
        # The base entity updates self._attr_available based on BLE presence.
        super()._async_update_state(new_state, lock_info, connection_info)

