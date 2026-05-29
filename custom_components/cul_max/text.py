"""Text entities for editing MAX! week profiles per day."""
from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CulMaxConfigEntry
from .const import CLIMATE_DEVICE_TYPES, DOMAIN
from .coordinator import CulMaxCoordinator, KnownDevice
from .protocol import (
    MaxMessage,
    WEEK_PROFILE_DAY_NAMES,
    format_week_profile_by_day,
)

DAY_INDEXES = (2, 3, 4, 5, 6, 0, 1)
DAY_SORT_ORDERS = {
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    6: 5,
    0: 6,
    1: 7,
}
DAY_SHORT_LABELS = {
    0: "Sa",
    1: "So",
    2: "Mo",
    3: "Di",
    4: "Mi",
    5: "Do",
    6: "Fr",
}
DAY_LONG_LABELS = {
    0: "Samstag",
    1: "Sonntag",
    2: "Montag",
    3: "Dienstag",
    4: "Mittwoch",
    5: "Donnerstag",
    6: "Freitag",
}
DAY_KEYS = {
    0: "saturday",
    1: "sunday",
    2: "monday",
    3: "tuesday",
    4: "wednesday",
    5: "thursday",
    6: "friday",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up text entities for week profile editing."""
    coordinator: CulMaxCoordinator = entry.runtime_data
    entities: list[TextEntity] = []
    known_ids: set[str] = set()

    for device in coordinator.get_all_devices():
        if device.device_type not in CLIMATE_DEVICE_TYPES:
            continue
        for day_index in DAY_INDEXES:
            entity = CulMaxWeekProfileDayText(coordinator, device, day_index)
            entities.append(entity)
            known_ids.add(entity.unique_id)

    @callback
    def on_new_device(msg: MaxMessage, decoded: object) -> None:
        device = coordinator.get_device(msg.src_hex)
        if not device or device.device_type not in CLIMATE_DEVICE_TYPES:
            return
        new_entities: list[TextEntity] = []
        for day_index in DAY_INDEXES:
            entity = CulMaxWeekProfileDayText(coordinator, device, day_index)
            if entity.unique_id not in known_ids:
                known_ids.add(entity.unique_id)
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.add_global_listener(on_new_device))
    async_add_entities(entities)


class CulMaxWeekProfileDayText(TextEntity):
    """Editable one-line week profile for a single weekday."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-clock"
    _attr_native_max = 255

    def __init__(
        self,
        coordinator: CulMaxCoordinator,
        device: KnownDevice,
        day_index: int,
    ) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._day_index = day_index
        self._day_key = DAY_KEYS[day_index]
        self._day_label = WEEK_PROFILE_DAY_NAMES[day_index]
        self._day_long_label = DAY_LONG_LABELS[day_index]
        self._attr_entity_registry_enabled_default = True

        self._attr_name = f"{DAY_SORT_ORDERS[day_index]} {self._day_long_label}"
        self._attr_suggested_object_id = (
            f"week_profile_{DAY_SORT_ORDERS[day_index]}_{self._day_key}"
        )
        self._attr_unique_id = f"{DOMAIN}_{self._address}_week_profile_{self._day_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=device.name,
            manufacturer="eQ-3",
            model=coordinator.get_device_registry_model(device),
        )
        self._sync_from_device()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_week_profile_listener(self._address, self._on_week_profile_update)
        )

    def _sync_from_device(self) -> None:
        self._attr_native_value = self._coordinator.get_week_profile_day_value(
            self._address,
            self._day_key,
        )

    @callback
    def _on_week_profile_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    async def async_set_value(self, value: str) -> None:
        await self._coordinator.async_set_week_profile_day_draft(
            self._address,
            self._day_key,
            value,
        )
        self._sync_from_device()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        effective_week_profile = self._coordinator.get_effective_week_profile(self._address)
        by_day = format_week_profile_by_day(effective_week_profile)
        return {
            "weekday": self._day_long_label,
            "weekday_short": DAY_SHORT_LABELS[self._day_index],
            "weekday_index": DAY_SORT_ORDERS[self._day_index],
            "draft_pending": self._coordinator.has_config_draft(self._address),
            "week_profile_source": (
                "device"
                if effective_week_profile == self._device.week_profile
                else "linked_partner"
            ),
            "format_example": "18,07:00,23,15:30,18",
            "format_hint": "Temperatur,HH:MM,Temperatur,HH:MM,... letzter Wert gilt bis 24:00",
            "all_days_preview": [
                f"{DAY_LONG_LABELS[idx]}: {self._coordinator.get_week_profile_day_value(self._address, DAY_KEYS[idx])}"
                for idx in DAY_INDEXES
            ],
        }
