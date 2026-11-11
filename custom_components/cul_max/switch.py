"""Vacation mode switch on the CUL controller device."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CulMaxConfigEntry
from .const import DOMAIN
from .coordinator import CulMaxCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([CulMaxVacationSwitch(entry.runtime_data)])


def controller_unique_id(coordinator: CulMaxCoordinator, key: str) -> str:
    return f"{DOMAIN}_{key}_{coordinator.host.replace('.', '_')}_{coordinator.port}"


class CulMaxVacationSwitch(SwitchEntity):
    """On = all thermostats hold the vacation temperature until the return time."""

    _attr_has_entity_name = True
    _attr_translation_key = "vacation"

    def __init__(self, coordinator: CulMaxCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = controller_unique_id(coordinator, "vacation")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.controller_identifier)},
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_vacation_listener(self._on_update))

    @callback
    def _on_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._coordinator.get_vacation_status()["active"]

    @property
    def icon(self) -> str:
        return "mdi:airplane" if self.is_on else "mdi:airplane-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._coordinator.get_vacation_status()
        counts = status["counts"]
        return {
            "temperature": status["temperature"],
            "return_at": status["end"],
            "preheat_hours": status["preheat_hours"],
            "thermostats_until": status["device_end"],
            "started_at": status["started_at"],
            "confirmed": counts.get("confirmed", 0),
            "pending": counts.get("pending", 0),
            "failed": counts.get("failed", 0) + counts.get("restore_failed", 0),
            "restored": counts.get("restored", 0),
            "devices": status["devices"],
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            await self._coordinator.async_start_vacation()
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.async_end_vacation(reason="manual")
