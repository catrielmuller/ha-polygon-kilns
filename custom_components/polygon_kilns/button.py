"""Buttons for the Polygon Kilns integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .api import PolygonKilnsApiError
from .coordinator import PolygonConfigEntry, PolygonKilnsCoordinator
from .entity import PolygonKilnEntity


async def async_setup_entry(hass, entry: PolygonConfigEntry, async_add_entities):
    """Set up the kiln buttons, adding kilns discovered later on."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_kilns() -> None:
        new_ids = [k for k in coordinator.data.kilns if k not in known]
        if not new_ids:
            return
        known.update(new_ids)
        entities: list[ButtonEntity] = []
        for kiln_id in new_ids:
            entities.append(PolygonKilnStartButton(coordinator, kiln_id))
            entities.append(PolygonKilnStopButton(coordinator, kiln_id))
        async_add_entities(entities)

    _add_new_kilns()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_kilns))


class PolygonKilnStartButton(PolygonKilnEntity, ButtonEntity):
    """Start the program currently chosen in the program select."""

    _attr_translation_key = "start"

    def __init__(self, coordinator: PolygonKilnsCoordinator, kiln_id: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator, kiln_id)
        self._attr_unique_id = f"{kiln_id}_start"

    async def async_press(self) -> None:
        """Start the selected program now."""
        sched_num = self.coordinator.selected_programs.get(self.kiln_id)
        if sched_num is None:
            raise HomeAssistantError(
                "Elegí primero un programa en el selector del horno"
            )
        try:
            await self.coordinator.client.async_request_start(self.kiln_id, sched_num)
        except PolygonKilnsApiError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()


class PolygonKilnStopButton(PolygonKilnEntity, ButtonEntity):
    """Stop the kiln via the stopRequested flag."""

    _attr_translation_key = "stop"

    def __init__(self, coordinator: PolygonKilnsCoordinator, kiln_id: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator, kiln_id)
        self._attr_unique_id = f"{kiln_id}_stop"

    async def async_press(self) -> None:
        """Request a stop."""
        try:
            await self.coordinator.client.async_stop_kiln(self.kiln_id)
        except PolygonKilnsApiError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
