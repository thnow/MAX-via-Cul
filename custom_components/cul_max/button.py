"""Button entities for applying or discarding staged MAX! configuration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CulMaxConfigEntry
from .const import CLIMATE_DEVICE_TYPES, DOMAIN
from .coordinator import CulMaxCoordinator, KnownDevice
from .protocol import MaxMessage


@dataclass(frozen=True, kw_only=True)
class CulMaxButtonDescription(ButtonEntityDescription):
    """Description for one MAX! config action button."""

    action: str


BUTTON_TYPES: tuple[CulMaxButtonDescription, ...] = (
    CulMaxButtonDescription(
        key="save_config",
        name="Save Configuration",
        icon="mdi:content-save",
        entity_category=EntityCategory.CONFIG,
        action="save",
    ),
    CulMaxButtonDescription(
        key="discard_config",
        name="Discard Draft",
        icon="mdi:restore",
        entity_category=EntityCategory.CONFIG,
        action="discard",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up config action buttons for MAX! climate devices."""
    coordinator: CulMaxCoordinator = entry.runtime_data
    entities: list[ButtonEntity] = []
    known_ids: set[str] = set()

    for device in coordinator.get_all_devices():
        if device.device_type not in CLIMATE_DEVICE_TYPES:
            continue
        for description in BUTTON_TYPES:
            entity = CulMaxConfigButton(coordinator, device, description)
            entities.append(entity)
            known_ids.add(entity.unique_id)

    @callback
    def on_new_device(msg: MaxMessage, decoded: object) -> None:
        device = coordinator.get_device(msg.src_hex)
        if device is None or device.device_type not in CLIMATE_DEVICE_TYPES:
            return
        new_entities: list[ButtonEntity] = []
        for description in BUTTON_TYPES:
            entity = CulMaxConfigButton(coordinator, device, description)
            if entity.unique_id in known_ids:
                continue
            known_ids.add(entity.unique_id)
            new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.add_global_listener(on_new_device))
    async_add_entities(entities)


class CulMaxConfigButton(ButtonEntity):
    """Button entity to save or discard staged device configuration."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CulMaxCoordinator,
        device: KnownDevice,
        description: CulMaxButtonDescription,
    ) -> None:
        self._coordinator = coordinator
        self._device = device
        self.entity_description = description
        self._address = device.address

        self._attr_name = description.name
        self._attr_unique_id = f"{DOMAIN}_{self._address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=device.name,
            manufacturer="eQ-3",
            model=coordinator.get_device_registry_model(device),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    @callback
    def _on_diagnostics_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "draft_pending": self._coordinator.has_config_draft(self._address),
            "draft_values": self._coordinator.get_config_draft(self._address),
        }

    async def async_press(self) -> None:
        if self.entity_description.action == "save":
            await self._coordinator.async_apply_config_draft(self._address)
        else:
            await self._coordinator.async_discard_config_draft(self._address)
