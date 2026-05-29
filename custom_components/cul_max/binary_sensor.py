"""Binary sensor entities for MAX! window/door contacts and battery status."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import CulMaxConfigEntry
from .const import (
    CLIMATE_DEVICE_TYPES,
    DEVICE_CUBE,
    DEVICE_PUSH_BUTTON,
    DEVICE_SHUTTER_CONTACT,
    DOMAIN,
    STALE_TIMEOUT_CLIMATE,
    STALE_TIMEOUT_CUBE,
    STALE_TIMEOUT_PUSH_BUTTON,
    STALE_TIMEOUT_SHUTTER_CONTACT,
    STALE_TIMEOUT_VIRTUAL,
)
from .coordinator import CulMaxCoordinator, KnownDevice
from .protocol import MaxMessage, ShutterContactState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities for all known devices."""
    coordinator: CulMaxCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [CulMaxPairingModeSensor(coordinator)]
    contact_addresses: set[str] = set()
    battery_addresses: set[str] = set()
    stale_addresses: set[str] = set()
    pending_addresses: set[str] = set()

    for device in coordinator.get_all_devices():
        if device.device_type == DEVICE_SHUTTER_CONTACT:
            entities.append(CulMaxShutterContact(coordinator, device))
            contact_addresses.add(device.address)
        if not device.is_virtual:
            entities.append(CulMaxBatterySensor(coordinator, device))
            battery_addresses.add(device.address)
        entities.append(CulMaxStaleSensor(coordinator, device))
        stale_addresses.add(device.address)
        entities.append(CulMaxConfigPendingSensor(coordinator, device))
        pending_addresses.add(device.address)

    @callback
    def on_new_device(msg: MaxMessage, decoded: Any) -> None:
        device = coordinator.get_device(msg.src_hex)
        if not device:
            return
        new: list[BinarySensorEntity] = []
        if (
            device.device_type == DEVICE_SHUTTER_CONTACT
            and device.address not in contact_addresses
        ):
            contact_addresses.add(device.address)
            new.append(CulMaxShutterContact(coordinator, device))
        if not device.is_virtual and device.address not in battery_addresses:
            battery_addresses.add(device.address)
            new.append(CulMaxBatterySensor(coordinator, device))
        if device.address not in stale_addresses:
            stale_addresses.add(device.address)
            new.append(CulMaxStaleSensor(coordinator, device))
        if device.address not in pending_addresses:
            pending_addresses.add(device.address)
            new.append(CulMaxConfigPendingSensor(coordinator, device))
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.add_global_listener(on_new_device))
    async_add_entities(entities)


class CulMaxPairingModeSensor(BinarySensorEntity):
    """Integration-wide sensor showing whether MAX! pairing mode is active."""

    _attr_has_entity_name = True
    _attr_name = "Pairing Mode"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:link-variant-plus"

    def __init__(self, coordinator: CulMaxCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = (
            f"{DOMAIN}_pairing_mode_{coordinator.host.replace('.', '_')}_{coordinator.port}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"controller_{coordinator.host}:{coordinator.port}")},
            name=f"MAX! CUL ({coordinator.host}:{coordinator.port})",
            manufacturer="eQ-3 / CULFW",
            model="MAX! via CUL",
        )
        self._refresh_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_pairing_state_listener(self._on_pairing_state_update)
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._on_timer,
                timedelta(seconds=1),
            )
        )

    def _refresh_state(self) -> None:
        self._attr_is_on = self._coordinator.is_pairing_mode

    @callback
    def _on_pairing_state_update(self) -> None:
        self._refresh_state()
        self.async_write_ha_state()

    @callback
    def _on_timer(self, now) -> None:
        if not self._coordinator.is_pairing_mode:
            return
        self._refresh_state()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pairing_until = self._coordinator.pairing_until
        return {
            "pairing_until": pairing_until.isoformat() if pairing_until else None,
            "remaining_seconds": self._coordinator.get_pairing_remaining_seconds(),
            "host": self._coordinator.host,
            "port": self._coordinator.port,
        }


class CulMaxShutterContact(BinarySensorEntity):
    """Binary sensor for a MAX! ShutterContact (window/door)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._contact_state: ShutterContactState | None = None

        self._attr_unique_id = f"{DOMAIN}_{self._address}_contact"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=device.name,
            manufacturer="Virtual" if device.is_virtual else "eQ-3",
            model=coordinator.get_device_registry_model(device),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_listener(self._address, self._on_message)
        )
        last = self._device.last_state
        if last:
            self._attr_is_on = last.get("is_open", False)

    @callback
    def _on_message(self, msg: MaxMessage, decoded: ShutterContactState | None) -> None:
        if not isinstance(decoded, ShutterContactState):
            return
        self._contact_state = decoded
        self._attr_is_on = decoded.is_open
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "address": self._address,
            "serial_number": self._device.serial_number or None,
            "firmware_version": self._device.firmware_version or None,
            "is_paired": self._coordinator.is_device_paired(self._address),
            "pairing_state": self._coordinator.get_pairing_state(self._address),
            "device_label": (
                f"{self._device.serial_number} / {self._address}"
                if self._device.serial_number
                else self._address
            ),
            "is_virtual": self._device.is_virtual,
            "superseded_by": self._device.superseded_by or None,
            "duplicate_reason": self._device.duplicate_reason or None,
            "pending_config": self._device.pending_config,
            "config_pending": bool(self._device.pending_config),
            "last_command": self._device.last_command or None,
            "group_id": self._device.group_id,
            "linked_partners": self._device.linked_partners,
            "peer_names": self._coordinator.get_peer_names(self._address),
            "peer_labels": self._coordinator.get_peer_labels(self._address),
            "supported_partner_types": self._coordinator.get_supported_partner_type_names(self._device.device_type),
        }
        if self._contact_state:
            attrs["battery_low"] = self._contact_state.battery_low
            attrs["rf_error"] = self._contact_state.rf_error
        return attrs

    @property
    def icon(self) -> str:
        """Show a more European-style window icon for open/closed state."""
        return "mdi:window-open-variant" if self.is_on else "mdi:window-closed-variant"


class CulMaxBatterySensor(BinarySensorEntity):
    """Battery status sensor for any MAX! device."""

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address

        self._attr_unique_id = f"{DOMAIN}_{self._address}_battery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=device.name,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_listener(self._address, self._on_message)
        )
        last = self._device.last_state
        if last:
            self._attr_is_on = last.get("battery_low", False)

    @callback
    def _on_message(self, msg: MaxMessage, decoded: Any) -> None:
        if decoded is None:
            return
        battery_low = getattr(decoded, "battery_low", None)
        if battery_low is not None:
            self._attr_is_on = battery_low
            self.async_write_ha_state()


class CulMaxStaleSensor(BinarySensorEntity):
    """Diagnostic sensor indicating a device has not been heard from in too long."""

    _attr_has_entity_name = True
    _attr_name = "Stale"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._timeout = _stale_timeout_for_device(device)

        self._attr_unique_id = f"{DOMAIN}_{self._address}_stale"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=device.name,
        )
        self._refresh_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_listener(self._address, self._on_message)
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._on_timer,
                timedelta(minutes=5),
            )
        )

    @callback
    def _on_message(self, msg: MaxMessage, decoded: Any) -> None:
        self._refresh_state()
        self.async_write_ha_state()

    @callback
    def _on_timer(self, now) -> None:
        self._refresh_state()
        self.async_write_ha_state()

    def _refresh_state(self) -> None:
        last_seen = dt_util.parse_datetime(self._device.last_seen)
        self._attr_available = last_seen is not None
        if last_seen is None:
            self._attr_is_on = None
            return
        self._attr_is_on = (dt_util.utcnow() - last_seen) > self._timeout

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "address": self._address,
            "serial_number": self._device.serial_number or None,
            "firmware_version": self._device.firmware_version or None,
            "is_paired": self._coordinator.is_device_paired(self._address),
            "pairing_state": self._coordinator.get_pairing_state(self._address),
            "device_label": (
                f"{self._device.serial_number} / {self._address}"
                if self._device.serial_number
                else self._address
            ),
            "is_virtual": self._device.is_virtual,
            "superseded_by": self._device.superseded_by or None,
            "duplicate_reason": self._device.duplicate_reason or None,
            "pending_config": self._device.pending_config,
            "config_pending": bool(self._device.pending_config),
            "last_command": self._device.last_command or None,
            "last_seen": self._device.last_seen or None,
            "stale_after_hours": round(self._timeout.total_seconds() / 3600, 2),
        }


class CulMaxConfigPendingSensor(BinarySensorEntity):
    """Diagnostic sensor mirroring Homegear/FHEM-style config pending state."""

    _attr_has_entity_name = True
    _attr_name = "Config Pending"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_config_pending"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=device.name,
        )
        self._refresh_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    def _refresh_state(self) -> None:
        self._attr_is_on = bool(self._device.pending_config)

    @callback
    def _on_diagnostics_update(self) -> None:
        self._refresh_state()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "address": self._address,
            "serial_number": self._device.serial_number or None,
            "is_paired": self._coordinator.is_device_paired(self._address),
            "pairing_state": self._coordinator.get_pairing_state(self._address),
            "device_label": (
                f"{self._device.serial_number} / {self._address}"
                if self._device.serial_number
                else self._address
            ),
            "pending_config": self._device.pending_config,
            "pending_config_count": len(self._device.pending_config),
            "last_command": self._device.last_command or None,
            **self._coordinator.get_pending_queue_details(self._address),
        }


def _stale_timeout_for_device(device: KnownDevice) -> timedelta:
    """Return the stale timeout based on the MAX! device type."""
    if device.is_virtual:
        return STALE_TIMEOUT_VIRTUAL
    if device.device_type in CLIMATE_DEVICE_TYPES:
        return STALE_TIMEOUT_CLIMATE
    if device.device_type == DEVICE_SHUTTER_CONTACT:
        return STALE_TIMEOUT_SHUTTER_CONTACT
    if device.device_type == DEVICE_PUSH_BUTTON:
        return STALE_TIMEOUT_PUSH_BUTTON
    if device.device_type == DEVICE_CUBE:
        return STALE_TIMEOUT_CUBE
    return STALE_TIMEOUT_SHUTTER_CONTACT
