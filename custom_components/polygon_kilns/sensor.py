"""Sensors for the Polygon Kilns integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import callback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import PolygonConfigEntry, PolygonKilnsCoordinator
from .entity import PolygonKilnEntity

# Kiln states observed from the backend (Spanish) plus the English variants the
# firmware has reported; keep in sync with STARTABLE_STATES in const.py.
STATE_OPTIONS = ["En espera", "Enfriamiento", "Terminado", "idle", "finished"]

# Segment phases reported by the kiln while running a program.
SEGMENT_PHASE_OPTIONS = ["ramp", "hold"]


@dataclass(frozen=True, kw_only=True)
class PolygonSensorDescription(SensorEntityDescription):
    """Describes a Polygon kiln sensor."""

    value_fn: Callable[[dict[str, Any]], StateType | datetime]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def _eta(kiln: dict[str, Any]) -> datetime | None:
    """Estimated time of completion from etaSeconds."""
    eta_seconds = kiln.get("etaSeconds")
    if not eta_seconds:
        return None
    return dt_util.utcnow() + timedelta(seconds=float(eta_seconds))


def _elapsed(kiln: dict[str, Any]) -> float | None:
    """Elapsed seconds as minutes."""
    value = kiln.get("elapsedSeconds")
    return None if value is None else round(float(value) / 60, 1)


def _last_seen(kiln: dict[str, Any]) -> datetime | None:
    """Last contact timestamp."""
    if not (value := kiln.get("lastSeen")):
        return None
    return dt_util.parse_datetime(str(value))


def _progress(kiln: dict[str, Any]) -> int | None:
    """Progress as a percentage."""
    value = kiln.get("progress")
    return None if value is None else round(float(value) * 100)


def _stage(kiln: dict[str, Any]) -> str | None:
    """Current stage over total stages."""
    current = kiln.get("currentStage")
    if current is None:
        return None
    total = kiln.get("totalStages")
    return f"{current}/{total}" if total else str(current)


def _last_firing_attrs(firing: dict[str, Any]) -> dict[str, Any] | None:
    """Attributes of the most recent firing."""
    if not firing:
        return None
    return {
        "programa": firing.get("schedule"),
        "estado": firing.get("state"),
        "inicio": firing.get("startTime"),
        "fin": firing.get("endTime"),
        "energia_kwh": firing.get("energyKWh"),
        "costo": firing.get("cost"),
        "potencia_w": firing.get("powerWatts"),
    }


SENSORS: tuple[PolygonSensorDescription, ...] = (
    PolygonSensorDescription(
        key="temperature",
        translation_key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda kiln: kiln.get("temperature"),
    ),
    PolygonSensorDescription(
        key="setpoint",
        translation_key="setpoint",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        value_fn=lambda kiln: kiln.get("setpoint"),
    ),
    PolygonSensorDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_OPTIONS,
        value_fn=lambda kiln: kiln.get("state"),
    ),
    PolygonSensorDescription(
        key="stage",
        translation_key="stage",
        value_fn=_stage,
    ),
    PolygonSensorDescription(
        key="segment_phase",
        translation_key="segment_phase",
        device_class=SensorDeviceClass.ENUM,
        options=SEGMENT_PHASE_OPTIONS,
        value_fn=lambda kiln: kiln.get("segmentPhase"),
        entity_registry_enabled_default=False,
    ),
    PolygonSensorDescription(
        key="progress",
        translation_key="progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_progress,
    ),
    PolygonSensorDescription(
        key="eta",
        translation_key="eta",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_eta,
    ),
    PolygonSensorDescription(
        key="elapsed",
        translation_key="elapsed",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        value_fn=_elapsed,
    ),
    PolygonSensorDescription(
        key="energy",
        translation_key="energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda kiln: kiln.get("energyKWh"),
    ),
    PolygonSensorDescription(
        key="cost",
        translation_key="cost",
        # The backend reports cost in the account's local currency, which the
        # integration cannot know; without a unit, TOTAL statistics would be
        # meaningless, so this stays a plain value sensor.
        suggested_display_precision=2,
        value_fn=lambda kiln: kiln.get("cost"),
    ),
    PolygonSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda kiln: kiln.get("rssi"),
    ),
    PolygonSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=_last_seen,
    ),
)

LAST_FIRING_DESCRIPTION = PolygonSensorDescription(
    key="last_firing",
    translation_key="last_firing",
    value_fn=lambda kiln: kiln.get("schedule"),
    attrs_fn=_last_firing_attrs,
)


async def async_setup_entry(hass, entry: PolygonConfigEntry, async_add_entities):
    """Set up Polygon kiln sensors, adding entities for kilns seen later on."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_kilns() -> None:
        new_ids = [k for k in coordinator.data.kilns if k not in known]
        if not new_ids:
            return
        known.update(new_ids)
        entities: list[PolygonKilnSensor | PolygonLastFiringSensor] = []
        for kiln_id in new_ids:
            entities.extend(
                PolygonKilnSensor(coordinator, kiln_id, description)
                for description in SENSORS
            )
            entities.append(PolygonLastFiringSensor(coordinator, kiln_id))
        async_add_entities(entities)

    _add_new_kilns()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_kilns))


class PolygonKilnSensor(PolygonKilnEntity, SensorEntity):
    """A sensor reading a field of the kiln document."""

    entity_description: PolygonSensorDescription

    def __init__(
        self,
        coordinator: PolygonKilnsCoordinator,
        kiln_id: str,
        description: PolygonSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, kiln_id)
        self.entity_description = description
        self._attr_unique_id = f"{kiln_id}_{description.key}"

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.kiln)


class PolygonLastFiringSensor(PolygonKilnEntity, SensorEntity):
    """Sensor describing the most recent firing of the kiln."""

    entity_description: PolygonSensorDescription = LAST_FIRING_DESCRIPTION

    def __init__(self, coordinator: PolygonKilnsCoordinator, kiln_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, kiln_id)
        self._attr_unique_id = f"{kiln_id}_{LAST_FIRING_DESCRIPTION.key}"

    @property
    def _firing(self) -> dict[str, Any]:
        """Return the most recent firing."""
        return self.coordinator.data.last_firing.get(self.kiln_id, {})

    @property
    def native_value(self) -> StateType:
        """Return the program name of the last firing."""
        return self._firing.get("schedule")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return details of the last firing."""
        return _last_firing_attrs(self._firing)
