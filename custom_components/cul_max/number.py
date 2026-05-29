"""Configuration number entities for MAX! thermostat parameters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CulMaxConfigEntry
from .const import CLIMATE_DEVICE_TYPES, DOMAIN
from .coordinator import CulMaxCoordinator, KnownDevice
from .protocol import MaxMessage


@dataclass(frozen=True, kw_only=True)
class CulMaxNumberDescription(NumberEntityDescription):
    """Describes one MAX! config number entity."""

    getter: Callable[[KnownDevice], float]
    setter: Callable[[CulMaxCoordinator, str, float], object]


NUMBER_TYPES: tuple[CulMaxNumberDescription, ...] = (
    CulMaxNumberDescription(
        key="comfort_temperature",
        name="Comfort Temperature",
        native_min_value=4.5,
        native_max_value=30.5,
        native_step=0.5,
        mode=NumberMode.BOX,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        getter=lambda device: device.comfort_temperature,
        setter=lambda coordinator, address, value: coordinator.async_set_comfort_temperature(address, value),
    ),
    CulMaxNumberDescription(
        key="eco_temperature",
        name="Eco Temperature",
        native_min_value=4.5,
        native_max_value=30.5,
        native_step=0.5,
        mode=NumberMode.BOX,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        getter=lambda device: device.eco_temperature,
        setter=lambda coordinator, address, value: coordinator.async_set_eco_temperature(address, value),
    ),
    CulMaxNumberDescription(
        key="window_open_temperature",
        name="Window Open Temperature",
        native_min_value=4.5,
        native_max_value=30.5,
        native_step=0.5,
        mode=NumberMode.BOX,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        getter=lambda device: device.window_open_temperature,
        setter=lambda coordinator, address, value: coordinator.async_set_window_open_temperature(address, value),
    ),
    CulMaxNumberDescription(
        key="window_open_duration",
        name="Window Open Duration",
        native_min_value=0,
        native_max_value=60,
        native_step=5,
        mode=NumberMode.BOX,
        native_unit_of_measurement="min",
        device_class=None,
        getter=lambda device: float(device.window_open_duration),
        setter=lambda coordinator, address, value: coordinator.async_set_window_open_duration(address, int(value)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MAX! config number entities for all known thermostat devices."""
    coordinator: CulMaxCoordinator = entry.runtime_data
    entities: list[NumberEntity] = []
    known_ids: set[str] = set()

    for device in coordinator.get_all_devices():
        if device.device_type not in CLIMATE_DEVICE_TYPES:
            continue
        for description in NUMBER_TYPES:
            entity = CulMaxConfigNumber(coordinator, device, description)
            entities.append(entity)
            known_ids.add(entity.unique_id)

    @callback
    def on_new_device(msg: MaxMessage, decoded: object) -> None:
        device = coordinator.get_device(msg.src_hex)
        if device is None or device.device_type not in CLIMATE_DEVICE_TYPES:
            return
        new_entities: list[NumberEntity] = []
        for description in NUMBER_TYPES:
            entity = CulMaxConfigNumber(coordinator, device, description)
            if entity.unique_id in known_ids:
                continue
            known_ids.add(entity.unique_id)
            new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.add_global_listener(on_new_device))
    async_add_entities(entities)


class CulMaxConfigNumber(NumberEntity):
    """One editable MAX! thermostat configuration value."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: CulMaxCoordinator,
        device: KnownDevice,
        description: CulMaxNumberDescription,
    ) -> None:
        self._coordinator = coordinator
        self._device = device
        self.entity_description = description
        self._address = device.address

        self._attr_name = description.name
        self._attr_unique_id = f"{DOMAIN}_{self._address}_{description.key}"
        self._attr_native_min_value = description.native_min_value
        self._attr_native_max_value = description.native_max_value
        self._attr_native_step = description.native_step
        self._attr_mode = description.mode
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_device_class = description.device_class
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=device.name,
            manufacturer="eQ-3",
            model=coordinator.get_device_registry_model(device),
        )
        self._sync_from_device()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    def _sync_from_device(self) -> None:
        value = self._coordinator.get_temperature_config_value(
            self._address,
            self.entity_description.key,
        )
        if value is None:
            value = self.entity_description.getter(self._device)
        self._attr_native_value = value

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        await self._coordinator.async_set_temperature_config_draft(
            self._address,
            self.entity_description.key,
            value,
        )
        self._sync_from_device()
        self.async_write_ha_state()
