"""Scheduled start date/time entities for the Polygon Kilns integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .coordinator import PolygonConfigEntry, PolygonKilnsCoordinator
from .entity import PolygonKilnEntity


async def async_setup_entry(hass, entry: PolygonConfigEntry, async_add_entities):
    """Set up the scheduled start datetimes, adding kilns discovered later on."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_kilns() -> None:
        new_ids = [k for k in coordinator.data.kilns if k not in known]
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities(
            PolygonKilnScheduledStartDatetime(coordinator, kiln_id)
            for kiln_id in new_ids
        )

    _add_new_kilns()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_kilns))


class PolygonKilnScheduledStartDatetime(PolygonKilnEntity, DateTimeEntity):
    """Date and time at which the selected program will be started."""

    _attr_translation_key = "scheduled_start"

    def __init__(self, coordinator: PolygonKilnsCoordinator, kiln_id: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, kiln_id)
        self._attr_unique_id = f"{kiln_id}_scheduled_start"

    @property
    def native_value(self) -> datetime | None:
        """Return the configured start time."""
        if start := self.coordinator.scheduled_starts.get(self.kiln_id):
            return start.start_at
        return None

    async def async_set_value(self, value: datetime) -> None:
        """Set the start time, keeping any previous schedNum/armed state."""
        existing = self.coordinator.scheduled_starts.get(self.kiln_id)
        sched_num = (
            existing.sched_num
            if existing
            else self.coordinator.selected_programs.get(self.kiln_id)
        )
        if sched_num is None:
            raise HomeAssistantError(
                "Elegí primero un programa en el selector del horno"
            )
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt_util.get_default_time_zone())
        await self.coordinator.async_set_scheduled_start(
            self.kiln_id,
            sched_num,
            value,
            armed=existing.armed if existing else False,
        )
