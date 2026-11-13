"""Event entities for MAX! PushButtons (Eco Taster)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CulMaxConfigEntry
from .const import DEVICE_PUSH_BUTTON, DOMAIN
from .coordinator import CulMaxCoordinator, KnownDevice
from .protocol import MaxMessage, PushButtonState

PUSH_BUTTON_EVENT_TYPES = ["auto", "eco"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one event entity per paired push button."""
    coordinator: CulMaxCoordinator = entry.runtime_data
    known: set[str] = set()
    entities: list[EventEntity] = []
    for device in coordinator.get_all_devices():
        if device.device_type == DEVICE_PUSH_BUTTON:
            known.add(device.address)
            entities.append(CulMaxPushButtonEvent(coordinator, device))

    @callback
    def on_new_device(msg: MaxMessage, decoded: Any) -> None:
        device = coordinator.get_device(msg.src_hex)
        if device is None or device.device_type != DEVICE_PUSH_BUTTON or device.address in known:
            return
        known.add(device.address)
        async_add_entities([CulMaxPushButtonEvent(coordinator, device)])

    entry.async_on_unload(coordinator.add_global_listener(on_new_device))
    async_add_entities(entities)


class CulMaxPushButtonEvent(EventEntity):
    """Fires 'auto' or 'eco' when the button is pressed."""

    _attr_has_entity_name = True
    _attr_translation_key = "push_button"
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = PUSH_BUTTON_EVENT_TYPES

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{device.address}_push_button"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            via_device_id=coordinator.controller_device_id,
            name=device.name,
            manufacturer="eQ-3",
            model=coordinator.get_device_registry_model(device),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self._address, self._on_message))

    @callback
    def _on_message(self, msg: MaxMessage, decoded: Any) -> None:
        # Repeated telegrams arrive with decoded=None and are not presses.
        if not isinstance(decoded, PushButtonState):
            return
        if decoded.button not in PUSH_BUTTON_EVENT_TYPES:
            return
        self._trigger_event(decoded.button)
        self.async_write_ha_state()
