"""Topology picture of the MAX! installation (rooms, devices, links)."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import CulMaxConfigEntry
from .const import DOMAIN
from .coordinator import CulMaxCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([CulMaxTopologyImage(hass, entry.runtime_data)])


class CulMaxTopologyImage(ImageEntity):
    """SVG overview: HA areas as rooms, devices, on-device links, problems."""

    _attr_has_entity_name = True
    _attr_translation_key = "topology"
    _attr_content_type = "image/svg+xml"

    def __init__(self, hass: HomeAssistant, coordinator: CulMaxCoordinator) -> None:
        super().__init__(hass)
        self._coordinator = coordinator
        self._svg = ""
        self._attr_unique_id = (
            f"{DOMAIN}_topology_{coordinator.host.replace('.', '_')}_{coordinator.port}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.controller_identifier)},
        )

    async def async_added_to_hass(self) -> None:
        self._refresh(write=False)
        self.async_on_remove(
            async_track_time_interval(self.hass, self._on_timer, timedelta(seconds=60))
        )

    @callback
    def _on_timer(self, _now) -> None:
        self._refresh(write=True)

    @callback
    def _refresh(self, *, write: bool) -> None:
        svg = self._coordinator.render_topology()
        if svg != self._svg:
            self._svg = svg
            self._attr_image_last_updated = dt_util.utcnow()
            if write:
                self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        self._refresh(write=False)
        return self._svg.encode("utf-8")
