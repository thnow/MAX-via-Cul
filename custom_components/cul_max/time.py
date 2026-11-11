"""Vacation return time of day on the CUL controller device."""
from __future__ import annotations

import datetime as dt

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import CulMaxConfigEntry
from .const import DOMAIN
from .coordinator import CulMaxCoordinator
from .date import DEFAULT_RETURN_TIME, combine_local
from .switch import controller_unique_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([CulMaxVacationEndTime(entry.runtime_data)])


class CulMaxVacationEndTime(TimeEntity):
    """Time of day of the planned return."""

    _attr_has_entity_name = True
    _attr_translation_key = "vacation_end_time"
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator: CulMaxCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = controller_unique_id(coordinator, "vacation_end_time")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.controller_identifier)},
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_vacation_listener(self._on_update))

    @callback
    def _on_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> dt.time | None:
        end = self._coordinator.vacation_end()
        return end.time() if end else DEFAULT_RETURN_TIME

    async def async_set_value(self, value: dt.time) -> None:
        value = value.replace(second=0, microsecond=0)
        current = self._coordinator.vacation_end()
        if current is not None:
            new_end = combine_local(current.date(), value)
        else:
            # no date yet: the next occurrence of that time
            today = dt_util.now().date()
            new_end = combine_local(today, value)
            if new_end <= dt_util.now():
                new_end = combine_local(today + dt.timedelta(days=1), value)
        if new_end <= dt_util.now():
            raise HomeAssistantError("Die Rückkehr muss in der Zukunft liegen.")
        try:
            await self._coordinator.async_set_vacation_settings(end=new_end)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
