"""Sensor platform for the Yale Doorman L3S integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from yalexs_ble import ConnectionInfo, LockInfo, LockState

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import YaleDoormanConfigEntry
from .entity import YaleDoormanEntity
from .models import YaleDoormanData


@dataclass(frozen=True, kw_only=True)
class YaleDoormanSensorEntityDescription(SensorEntityDescription):
    """Describes a Yale Doorman sensor entity."""

    value_fn: Callable[
        [LockState, LockInfo, ConnectionInfo], int | float | None
    ]


SENSORS: tuple[YaleDoormanSensorEntityDescription, ...] = (
    YaleDoormanSensorEntityDescription(
        key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        has_entity_name=True,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda state, info, connection: (
            state.battery.percentage if state.battery else None
        ),
    ),
    YaleDoormanSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        has_entity_name=True,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_registry_enabled_default=False,
        value_fn=lambda state, info, connection: (
            state.battery.voltage if state.battery else None
        ),
    ),
    YaleDoormanSensorEntityDescription(
        key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        has_entity_name=True,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_registry_enabled_default=False,
        value_fn=lambda state, info, connection: connection.rssi,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleDoormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Yale Doorman sensor entities."""
    data = entry.runtime_data
    async_add_entities(
        YaleDoormanSensor(description, data) for description in SENSORS
    )


class YaleDoormanSensor(YaleDoormanEntity, SensorEntity):
    """Yale Doorman sensor entity."""

    entity_description: YaleDoormanSensorEntityDescription

    def __init__(
        self,
        description: YaleDoormanSensorEntityDescription,
        data: YaleDoormanData,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data)
        self._attr_unique_id = f"{data.lock.address}_{description.key}"

    @callback
    def _async_update_state(
        self,
        new_state: LockState,
        lock_info: LockInfo,
        connection_info: ConnectionInfo,
    ) -> None:
        """Update the sensor value."""
        self._attr_native_value = self.entity_description.value_fn(
            new_state, lock_info, connection_info
        )
        super()._async_update_state(new_state, lock_info, connection_info)
