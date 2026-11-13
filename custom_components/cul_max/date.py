"""Vacation return date on the CUL controller device."""
from __future__ import annotations

import datetime as dt

from homeassistant.components.date import DateEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .errors import CulMaxError, ha_error
from . import CulMaxConfigEntry
from .const import DOMAIN
from .coordinator import CulMaxCoordinator
from .switch import controller_unique_id

DEFAULT_RETURN_TIME = dt.time(18, 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([CulMaxVacationEndDate(entry.runtime_data)])


def combine_local(day: dt.date, at: dt.time) -> dt.datetime:
    return dt.datetime.combine(day, at, tzinfo=dt_util.get_default_time_zone())


class CulMaxVacationEndDate(DateEntity):
    """Day of the planned return (time is a separate entity)."""

    _attr_has_entity_name = True
    _attr_translation_key = "vacation_end_date"
    _attr_icon = "mdi:calendar-import"

    def __init__(self, coordinator: CulMaxCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = controller_unique_id(coordinator, "vacation_end_date")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.controller_identifier)},
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_vacation_listener(self._on_update))

    @callback
    def _on_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> dt.date | None:
        end = self._coordinator.vacation_end()
        return end.date() if end else None

    async def async_set_value(self, value: dt.date) -> None:
        current = self._coordinator.vacation_end()
        new_end = combine_local(value, current.time() if current else DEFAULT_RETURN_TIME)
        if new_end <= dt_util.now():
            raise ha_error(CulMaxError("return_in_future"))
        try:
            await self._coordinator.async_set_vacation_settings(end=new_end)
        except ValueError as err:
            raise ha_error(err) from err
