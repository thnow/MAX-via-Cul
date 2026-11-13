"""Summer mode valve position (off / fully open) on the CUL controller device."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .errors import ha_error
from . import CulMaxConfigEntry
from .const import DOMAIN
from .coordinator import SUMMER_VALVE_CLOSED, SUMMER_VALVE_OPEN, CulMaxCoordinator
from .switch import controller_unique_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([CulMaxSummerValveSelect(entry.runtime_data)])


class CulMaxSummerValveSelect(SelectEntity):
    """What the thermostats do in summer mode: off (closed) or on (open)."""

    _attr_has_entity_name = True
    _attr_translation_key = "summer_valve"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:valve"
    _attr_options = [SUMMER_VALVE_CLOSED, SUMMER_VALVE_OPEN]

    def __init__(self, coordinator: CulMaxCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = controller_unique_id(coordinator, "summer_valve")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.controller_identifier)},
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_vacation_listener(self._on_update))

    @callback
    def _on_update(self) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str:
        return self._coordinator.get_summer_status()["valve"]

    async def async_select_option(self, option: str) -> None:
        try:
            await self._coordinator.async_set_summer_valve(option)
        except ValueError as err:
            raise ha_error(err) from err
