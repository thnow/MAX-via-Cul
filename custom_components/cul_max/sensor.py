"""Diagnostic sensor entities for MAX! devices."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import CulMaxConfigEntry
from .const import (
    CLIMATE_DEVICE_TYPES,
    DEVICE_HEATING_THERMOSTAT,
    DEVICE_HEATING_THERMOSTAT_PLUS,
    DOMAIN,
)
from .coordinator import CulMaxCoordinator, KnownDevice
from .protocol import MaxMessage, format_week_profile_lines


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up diagnostic sensor entities for all known devices."""
    coordinator: CulMaxCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [CulMaxSendBudgetSensor(coordinator)]
    known_ids: set[str] = set()

    for device in coordinator.get_all_devices():
        for entity in _build_diagnostic_entities(coordinator, device):
            entities.append(entity)
            known_ids.add(entity.unique_id)

    @callback
    def on_new_device(msg: MaxMessage, decoded: object) -> None:
        device = coordinator.get_device(msg.src_hex)
        if not device:
            return
        new_entities: list[SensorEntity] = []
        for entity in _build_diagnostic_entities(coordinator, device):
            if entity.unique_id not in known_ids:
                known_ids.add(entity.unique_id)
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.add_global_listener(on_new_device))
    async_add_entities(entities)


class CulMaxSendBudgetSensor(SensorEntity):
    """Remaining CUL send credit (culfw credit_10ms) and the active send profile."""

    _attr_has_entity_name = True
    _attr_translation_key = "send_budget"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:radio-tower"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "credit_10ms"

    def __init__(self, coordinator: CulMaxCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = (
            f"{DOMAIN}_send_budget_{coordinator.host.replace('.', '_')}_{coordinator.port}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.controller_identifier)},
            name=coordinator.display_name,
            manufacturer="eQ-3 / CULFW",
            model="MAX! via CUL",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_cul_status_listener(self._on_update))
        self.async_on_remove(
            async_track_time_interval(self.hass, self._on_timer, timedelta(seconds=60))
        )

    @callback
    def _on_update(self) -> None:
        self.async_write_ha_state()

    @callback
    def _on_timer(self, now) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        status = self._coordinator.get_cul_credit_status()
        return status["credit_10ms"] if status["credit_known"] else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._coordinator.get_cul_credit_status()
        profile = self._coordinator.send_profile
        return {
            "credit_max": status["credit_max"],
            "budget_seconds": round(status["credit_max"] / 100, 1),
            "recovery_per_second": status["recovery_per_second"],
            "recovery_measured": status["recovery_measured"],
            "send_profile": profile.name,
            "set_temperature_ack_timeout": profile.set_temperature_timeout,
            "set_temperature_retries": profile.set_temperature_retries,
            "queued_commands": status["queued_commands"],
        }


class CulMaxLastSeenSensor(SensorEntity):
    """Timestamp sensor showing the last RF contact of a MAX! device."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_seen"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_last_seen"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
            manufacturer="Virtual" if device.is_virtual else "eQ-3",
            model=coordinator.get_device_registry_model(device),
        )
        self._sync_from_device()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    def _sync_from_device(self) -> None:
        self._attr_native_value = dt_util.parse_datetime(self._device.last_seen)

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        self._sync_from_device()

    @property
    def available(self) -> bool:
        return self._attr_native_value is not None


class CulMaxIdentitySensor(SensorEntity):
    """Diagnostic sensor exposing serial number and RF address together."""

    _attr_has_entity_name = True
    _attr_translation_key = "identity"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:card-account-details-outline"

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_identity"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    def _sync_from_device(self) -> None:
        serial = self._device.serial_number.strip()
        self._attr_native_value = f"{serial} / {self._address}" if serial else self._address

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "address": self._address,
            "serial_number": self._device.serial_number or None,
            "firmware_version": self._device.firmware_version or None,
            "is_paired": self._coordinator.is_device_paired(self._address),
            "pairing_state": self._coordinator.get_pairing_state(self._address),
            "device_name": self._device.name,
            "is_virtual": self._device.is_virtual,
            "superseded_by": self._device.superseded_by or None,
            "duplicate_reason": self._device.duplicate_reason or None,
            "pending_config": self._device.pending_config,
            "config_pending": bool(self._device.pending_config),
            "last_command": self._device.last_command or None,
            "peer_names": self._coordinator.get_peer_names(self._address),
            "peer_labels": self._coordinator.get_peer_labels(self._address),
            "supported_partner_types": self._coordinator.get_supported_partner_type_names(self._device.device_type),
            "last_time_sync_at": self._device.last_time_sync_at or None,
            "last_reported_time": self._device.last_reported_time or None,
            **self._coordinator.get_pending_queue_details(self._address),
        }


class CulMaxPairingStateSensor(SensorEntity):
    """Diagnostic sensor exposing whether a device is paired or only discovered."""

    _attr_has_entity_name = True
    _attr_translation_key = "pairing_state"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:link-variant"

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_pairing_state"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    def _sync_from_device(self) -> None:
        self._attr_native_value = self._coordinator.get_pairing_state(self._address)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "address": self._address,
            "serial_number": self._device.serial_number or None,
            "is_paired": self._coordinator.is_device_paired(self._address),
            "is_virtual": self._device.is_virtual,
        }


class CulMaxLastAckSensor(SensorEntity):
    """Timestamp sensor showing the last successful ACK for a MAX! device."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_ack"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_last_ack"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    def _sync_from_device(self) -> None:
        self._attr_native_value = dt_util.parse_datetime(self._device.last_ack_at)

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()


class CulMaxLastCommandSuccessSensor(SensorEntity):
    """Timestamp sensor showing the last successful write command for a device."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_command_success"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_last_command_success"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    def _sync_from_device(self) -> None:
        self._attr_native_value = dt_util.parse_datetime(self._device.last_command_success_at)

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()


class CulMaxLastTimeSyncSensor(SensorEntity):
    """Timestamp sensor showing the last outgoing time sync for a device."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_time_sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_last_time_sync"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    def _sync_from_device(self) -> None:
        self._attr_native_value = dt_util.parse_datetime(self._device.last_time_sync_at)

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()


class CulMaxRetryCountSensor(SensorEntity):
    """Diagnostic counter for retries on a MAX! device."""

    _attr_has_entity_name = True
    _attr_translation_key = "retry_count"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "retries"

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_retry_count"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    def _sync_from_device(self) -> None:
        self._attr_native_value = self._device.total_retry_count

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        return {"last_command_retries": self._device.last_command_retries}


class CulMaxCommunicationStatusSensor(SensorEntity):
    """Summary diagnostic sensor for communication health and recent failures."""

    _attr_has_entity_name = True
    _attr_translation_key = "communication"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_communication"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    def _sync_from_device(self) -> None:
        success = dt_util.parse_datetime(self._device.last_command_success_at)
        error = dt_util.parse_datetime(self._device.last_send_error_at)
        if self._device.last_send_error and (not success or (error and error >= success)):
            self._attr_native_value = "error"
        elif success or self._device.last_seen:
            self._attr_native_value = "ok"
        else:
            self._attr_native_value = "unknown"

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "last_send_error": self._device.last_send_error or None,
            "last_send_error_at": self._device.last_send_error_at or None,
            "last_command_success_at": self._device.last_command_success_at or None,
            "last_ack_at": self._device.last_ack_at or None,
            "last_seen": self._device.last_seen or None,
            "last_command_retries": self._device.last_command_retries,
            "total_retry_count": self._device.total_retry_count,
            "serial_number": self._device.serial_number or None,
            "is_paired": self._coordinator.is_device_paired(self._address),
            "pairing_state": self._coordinator.get_pairing_state(self._address),
            "superseded_by": self._device.superseded_by or None,
            "duplicate_reason": self._device.duplicate_reason or None,
            "pending_config": self._device.pending_config,
            "config_pending": bool(self._device.pending_config),
            "last_command": self._device.last_command or None,
            "peer_names": self._coordinator.get_peer_names(self._address),
            "peer_labels": self._coordinator.get_peer_labels(self._address),
            "last_time_sync_at": self._device.last_time_sync_at or None,
            "last_reported_time": self._device.last_reported_time or None,
            **self._coordinator.get_pending_queue_details(self._address),
        }


class CulMaxPeersSensor(SensorEntity):
    """Readable summary of linked partners for one MAX! device."""

    _attr_has_entity_name = True
    _attr_translation_key = "peers"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:account-network-outline"

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_peers"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_diagnostics_update)
        )

    def _sync_from_device(self) -> None:
        self._attr_native_value = self._coordinator.get_peer_summary(self._address)

    @callback
    def _on_diagnostics_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "linked_partners": self._device.linked_partners,
            "peer_names": self._coordinator.get_peer_names(self._address),
            "peer_labels": self._coordinator.get_peer_labels(self._address),
            "group_id": self._device.group_id,
            "is_paired": self._coordinator.is_device_paired(self._address),
            "pairing_state": self._coordinator.get_pairing_state(self._address),
            "config_pending": bool(self._device.pending_config),
            "pending_config": self._device.pending_config,
            **self._coordinator.get_pending_queue_details(self._address),
        }


class CulMaxExpectedWeekProfileTemperatureSensor(SensorEntity):
    """Current target temperature derived from the stored week profile."""

    _attr_has_entity_name = True
    _attr_translation_key = "expected_week_profile_temperature"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_expected_week_profile_temperature"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    def _sync_from_device(self) -> None:
        self._attr_native_value = self._coordinator.get_expected_week_profile_temperature(self._address)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_week_profile_listener(self._address, self._on_week_profile_update)
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._on_timer_tick,
                timedelta(minutes=1),
            )
        )

    @callback
    def _on_week_profile_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    @callback
    def _on_timer_tick(self, _now) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        effective_week_profile = self._coordinator.get_effective_week_profile(self._address)
        return {
            "expected_temperature_now": self._attr_native_value,
            "week_profile_lines": format_week_profile_lines(effective_week_profile) if effective_week_profile else [],
        }


class CulMaxWeekProfileValidationSensor(SensorEntity):
    """Best-effort validation whether the active device behavior matches the week profile."""

    _attr_has_entity_name = True
    _attr_translation_key = "week_profile_validation"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attrs: dict[str, Any] = {}
        self._attr_unique_id = f"{DOMAIN}_{self._address}_week_profile_validation"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )
        self._sync_from_device()

    def _sync_from_device(self) -> None:
        validation = self._coordinator.get_week_profile_validation(self._address)
        self._attr_native_value = validation.get("state")
        self._attrs = {
            "validation_reason": validation.get("reason"),
            "expected_temperature_now": validation.get("expected_temperature_now"),
            "actual_target_temperature": validation.get("actual_target_temperature"),
            "temperature_delta": validation.get("temperature_delta"),
            "mode_detail": validation.get("mode_detail"),
            "mode_is_temporary": validation.get("mode_is_temporary"),
            "config_pending": validation.get("config_pending"),
            "window_open_active": validation.get("window_open_active"),
            "open_window_partners": validation.get("open_window_partners"),
            "open_window_partner_names": validation.get("open_window_partner_names"),
            "week_profile_available": validation.get("week_profile_available"),
            "week_profile_source": validation.get("week_profile_source"),
            "last_time_sync_at": validation.get("last_time_sync_at"),
            "last_reported_time": validation.get("last_reported_time"),
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_update)
        )
        self.async_on_remove(
            self._coordinator.add_week_profile_listener(self._address, self._on_update)
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._on_timer_tick,
                timedelta(minutes=1),
            )
        )

    @callback
    def _on_update(self) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    @callback
    def _on_timer_tick(self, _now) -> None:
        self._sync_from_device()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs


class CulMaxValvePositionSensor(SensorEntity):
    """Valve opening of a radiator thermostat in percent (with history)."""

    _attr_has_entity_name = True
    _attr_translation_key = "valve_position"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:valve"

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._attr_unique_id = f"{DOMAIN}_{self._address}_valve_position"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            via_device=(DOMAIN, coordinator.controller_identifier),
            name=device.name,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.add_listener(self._address, self._on_message))

    @callback
    def _on_message(self, msg: MaxMessage | None, decoded: Any) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        value = (self._device.last_state or {}).get("valve_position")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None


def _build_diagnostic_entities(
    coordinator: CulMaxCoordinator,
    device: KnownDevice,
) -> list[SensorEntity]:
    """Build all diagnostic sensor entities for a device."""
    entities: list[SensorEntity] = [
        CulMaxIdentitySensor(coordinator, device),
        CulMaxPairingStateSensor(coordinator, device),
        CulMaxPeersSensor(coordinator, device),
        CulMaxLastSeenSensor(coordinator, device),
        CulMaxLastAckSensor(coordinator, device),
        CulMaxLastCommandSuccessSensor(coordinator, device),
        CulMaxRetryCountSensor(coordinator, device),
        CulMaxCommunicationStatusSensor(coordinator, device),
    ]
    if device.device_type in CLIMATE_DEVICE_TYPES:
        # only thermostats receive the time
        entities.append(CulMaxLastTimeSyncSensor(coordinator, device))
        entities.insert(3, CulMaxExpectedWeekProfileTemperatureSensor(coordinator, device))
        entities.insert(4, CulMaxWeekProfileValidationSensor(coordinator, device))
    if device.device_type in (DEVICE_HEATING_THERMOSTAT, DEVICE_HEATING_THERMOSTAT_PLUS):
        entities.insert(0, CulMaxValvePositionSensor(coordinator, device))
    return entities
