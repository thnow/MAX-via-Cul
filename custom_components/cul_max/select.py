"""Selects: summer mode valve position (CUL device), boost duration (radiator thermostats)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .errors import ha_error
from . import CulMaxConfigEntry
from .const import DEVICE_HEATING_THERMOSTAT, DEVICE_HEATING_THERMOSTAT_PLUS, DOMAIN
from .coordinator import SUMMER_VALVE_CLOSED, SUMMER_VALVE_OPEN, CulMaxCoordinator, KnownDevice
from .protocol import BOOST_DURATIONS, MaxMessage
from .switch import controller_unique_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CulMaxCoordinator = entry.runtime_data
    entities: list[SelectEntity] = [CulMaxSummerValveSelect(coordinator)]
    known: set[str] = set()
    for device in coordinator.get_all_devices():
        if device.device_type in HEATING_THERMOSTAT_TYPES:
            entities.append(CulMaxBoostDurationSelect(coordinator, device))
            known.add(device.address)

    @callback
    def on_new_device(msg: MaxMessage, decoded: object) -> None:
        device = coordinator.get_device(msg.src_hex)
        if device is None or device.device_type not in HEATING_THERMOSTAT_TYPES:
            return
        if device.address in known:
            return
        known.add(device.address)
        async_add_entities([CulMaxBoostDurationSelect(coordinator, device)])

    entry.async_on_unload(coordinator.add_global_listener(on_new_device))
    async_add_entities(entities)


HEATING_THERMOSTAT_TYPES = (DEVICE_HEATING_THERMOSTAT, DEVICE_HEATING_THERMOSTAT_PLUS)


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


class CulMaxBoostDurationSelect(SelectEntity):
    """How long the boost button opens the valve (ConfigValve).

    Unknown until set here: the thermostat cannot report its value.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "boost_duration"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:rocket-launch"
    _attr_options = [str(minutes) for minutes in BOOST_DURATIONS]

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{device.address}_boost_duration"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device.address)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_update)
        )

    @callback
    def _on_update(self) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        value = self._coordinator.get_temperature_config_value(self._address, "boost_duration")
        return None if value is None else str(int(value))

    async def async_select_option(self, option: str) -> None:
        try:
            await self._coordinator.async_set_temperature_config_draft(
                self._address, "boost_duration", int(option)
            )
        except ValueError as err:
            raise ha_error(err) from err
        self.async_write_ha_state()
