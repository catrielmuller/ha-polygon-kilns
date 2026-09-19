"""Scheduled start arm/disarm switch for the Polygon Kilns integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .coordinator import PolygonConfigEntry, PolygonKilnsCoordinator
from .entity import PolygonKilnEntity


async def async_setup_entry(hass, entry: PolygonConfigEntry, async_add_entities):
    """Set up the scheduled start switches, adding kilns discovered later on."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_kilns() -> None:
        new_ids = [k for k in coordinator.data.kilns if k not in known]
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities(
            PolygonKilnScheduledStartSwitch(coordinator, kiln_id)
            for kiln_id in new_ids
        )

    _add_new_kilns()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_kilns))


class PolygonKilnScheduledStartSwitch(PolygonKilnEntity, SwitchEntity):
    """Arm or disarm the scheduled start of a kiln."""

    _attr_translation_key = "scheduled_start_armed"

    def __init__(self, coordinator: PolygonKilnsCoordinator, kiln_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, kiln_id)
        self._attr_unique_id = f"{kiln_id}_scheduled_start_armed"

    @property
    def is_on(self) -> bool:
        """Return True if a scheduled start is armed."""
        start = self.coordinator.scheduled_starts.get(self.kiln_id)
        return bool(start and start.armed)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the pending start details."""
        start = self.coordinator.scheduled_starts.get(self.kiln_id)
        if not start:
            return None
        return {
            "sched_num": start.sched_num,
            "start_at": start.start_at.isoformat(),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Arm the scheduled start."""
        start = self.coordinator.scheduled_starts.get(self.kiln_id)
        if start is None:
            raise HomeAssistantError(
                "Configurá primero la fecha/hora de inicio programado"
            )
        await self.coordinator.async_set_scheduled_start_armed(self.kiln_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disarm the scheduled start."""
        await self.coordinator.async_set_scheduled_start_armed(self.kiln_id, False)
