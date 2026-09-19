"""Binary sensors for the Polygon Kilns integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import callback

from .coordinator import PolygonConfigEntry, PolygonKilnsCoordinator
from .entity import PolygonKilnEntity


@dataclass(frozen=True, kw_only=True)
class PolygonBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Polygon kiln binary sensor."""

    is_on_fn: Callable[[dict[str, Any]], bool | None]


def _field_is_true(field: str) -> Callable[[dict[str, Any]], bool | None]:
    """Return a checker for a boolean kiln field."""
    return lambda kiln: (bool(kiln[field]) if field in kiln else None)


BINARY_SENSORS: tuple[PolygonBinarySensorDescription, ...] = (
    PolygonBinarySensorDescription(
        key="thermocouple_error",
        translation_key="thermocouple_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=_field_is_true("thermocoupleError"),
    ),
    PolygonBinarySensorDescription(
        key="sensor_fault",
        translation_key="sensor_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=_field_is_true("sensorFault"),
    ),
    PolygonBinarySensorDescription(
        key="overheat_fault",
        translation_key="overheat_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=_field_is_true("overheatFault"),
    ),
)


async def async_setup_entry(hass, entry: PolygonConfigEntry, async_add_entities):
    """Set up Polygon kiln binary sensors, adding kilns discovered later on."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_kilns() -> None:
        new_ids = [k for k in coordinator.data.kilns if k not in known]
        if not new_ids:
            return
        known.update(new_ids)
        entities: list[BinarySensorEntity] = []
        for kiln_id in new_ids:
            entities.append(PolygonKilnOnlineSensor(coordinator, kiln_id))
            entities.extend(
                PolygonKilnBinarySensor(coordinator, kiln_id, description)
                for description in BINARY_SENSORS
            )
        async_add_entities(entities)

    _add_new_kilns()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_kilns))


class PolygonKilnBinarySensor(PolygonKilnEntity, BinarySensorEntity):
    """A binary sensor reading a boolean kiln field."""

    entity_description: PolygonBinarySensorDescription

    def __init__(
        self,
        coordinator: PolygonKilnsCoordinator,
        kiln_id: str,
        description: PolygonBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, kiln_id)
        self.entity_description = description
        self._attr_unique_id = f"{kiln_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        return self.entity_description.is_on_fn(self.kiln)


class PolygonKilnOnlineSensor(PolygonKilnEntity, BinarySensorEntity):
    """Connectivity sensor based on the kiln's lastSeen timestamp."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "online"

    def __init__(self, coordinator: PolygonKilnsCoordinator, kiln_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, kiln_id)
        self._attr_unique_id = f"{kiln_id}_online"

    @property
    def is_on(self) -> bool | None:
        """Return True if the kiln reported in recently."""
        if not self.kiln:
            return None
        return self.coordinator.kiln_is_online(self.kiln)
