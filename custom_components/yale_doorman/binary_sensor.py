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

    # Doorbell sensor — always add, can report via BLE
    entities.append(YaleDoormanDoorbellSensor(data))

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


class YaleDoormanDoorbellSensor(YaleDoormanEntity, BinarySensorEntity):
    """Yale Doorman doorbell ring sensor."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_translation_key = "doorbell"

    def __init__(self, data: YaleDoormanData) -> None:
        """Initialize the doorbell sensor."""
        super().__init__(data)
        self._attr_unique_id = f"{self._device.address}_doorbell"
        self._attr_is_on = False

    @callback
    def _async_update_state(
        self,
        new_state: LockState,
        lock_info: LockInfo,
        connection_info: ConnectionInfo,
    ) -> None:
        """Update the doorbell state.

        Note: Doorbell ring detection depends on lock model support.
        The Doorman L3S may not expose doorbell events via BLE —
        this sensor is included for models that do support it.
        """
        # Doorbell state isn't directly in LockState from yalexs-ble.
        # This sensor remains as a placeholder for potential future
        # detection via advertisement data or unknown state bytes.
        super()._async_update_state(new_state, lock_info, connection_info)
