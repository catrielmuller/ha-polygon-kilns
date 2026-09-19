"""Program selector for the Polygon Kilns integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .coordinator import PolygonConfigEntry, PolygonKilnsCoordinator
from .entity import PolygonKilnEntity


async def async_setup_entry(hass, entry: PolygonConfigEntry, async_add_entities):
    """Set up the program selectors, adding kilns discovered later on."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_kilns() -> None:
        new_ids = [k for k in coordinator.data.kilns if k not in known]
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities(
            PolygonKilnProgramSelect(coordinator, kiln_id) for kiln_id in new_ids
        )

    _add_new_kilns()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_kilns))


class PolygonKilnProgramSelect(PolygonKilnEntity, SelectEntity):
    """Select the program that the start button will run."""

    _attr_translation_key = "program"

    def __init__(self, coordinator: PolygonKilnsCoordinator, kiln_id: str) -> None:
        """Initialize the selector."""
        super().__init__(coordinator, kiln_id)
        self._attr_unique_id = f"{kiln_id}_program"

    @property
    def _schedules(self) -> list[dict]:
        """Return the kiln's programs."""
        return self.coordinator.data.schedules.get(self.kiln_id, [])

    @property
    def options(self) -> list[str]:
        """Return the available program names."""
        return [str(s.get("name", s.get("schedNum"))) for s in self._schedules]

    @property
    def current_option(self) -> str | None:
        """Return the selected program name."""
        sched_num = self.coordinator.selected_programs.get(self.kiln_id)
        if sched_num is None:
            return None
        for schedule in self._schedules:
            if schedule.get("schedNum") == sched_num:
                return str(schedule.get("name", sched_num))
        return None

    async def async_select_option(self, option: str) -> None:
        """Remember the selected program in the coordinator."""
        for schedule in self._schedules:
            if str(schedule.get("name", schedule.get("schedNum"))) == option:
                await self.coordinator.async_select_program(
                    self.kiln_id, int(schedule["schedNum"])
                )
                self.async_write_ha_state()
                return
        raise HomeAssistantError(
            f"Programa inválido para el horno {self.kiln_id}: {option}"
        )
