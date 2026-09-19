"""Base entity for the Polygon Kilns integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PolygonKilnsCoordinator


class PolygonKilnEntity(CoordinatorEntity[PolygonKilnsCoordinator]):
    """Entity bound to a single kiln."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PolygonKilnsCoordinator,
        kiln_id: str,
    ) -> None:
        """Initialize the kiln-bound entity."""
        super().__init__(coordinator)
        self.kiln_id = kiln_id

    @property
    def kiln(self) -> dict[str, Any]:
        """Return the latest data for this kiln."""
        return self.coordinator.data.kilns.get(self.kiln_id, {})

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device this entity belongs to."""
        kiln = self.kiln
        return DeviceInfo(
            identifiers={(DOMAIN, self.kiln_id)},
            name=kiln.get("name", self.kiln_id),
            manufacturer="Polygon",
            model=kiln.get("kilnType", "Horno de cerámica"),
            sw_version=str(kiln.get("fwVersion", "")) or None,
        )

    @property
    def available(self) -> bool:
        """Entities stay available even if the kiln is offline."""
        return super().available and self.kiln_id in self.coordinator.data.kilns
