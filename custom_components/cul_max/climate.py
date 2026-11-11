"""Climate entities for MAX! thermostats (HeatingThermostat + WallMountedThermostat)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from . import CulMaxConfigEntry
from .const import (
    DEVICE_HEATING_THERMOSTAT,
    DEVICE_HEATING_THERMOSTAT_PLUS,
    DEVICE_WALL_THERMOSTAT,
    DOMAIN,
    MODE_AUTO,
    MODE_BOOST,
    MODE_MANUAL,
    MODE_VACATION,
    MODE_NAMES,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_OFF,
    CLIMATE_DEVICE_TYPES,
)
from .coordinator import CulMaxCoordinator, KnownDevice
from .protocol import (
    MaxMessage,
    ThermostatState,
    format_week_profile_by_day,
    format_week_profile_lines,
)

_LOGGER = logging.getLogger(__name__)

HVAC_MODE_MAP = {
    MODE_AUTO:    HVACMode.AUTO,
    MODE_MANUAL:  HVACMode.HEAT,
    2:            HVACMode.AUTO,   # vacation — treat as auto
    MODE_BOOST:   HVACMode.HEAT,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities for all known thermostat devices."""
    coordinator: CulMaxCoordinator = entry.runtime_data
    entities = []
    known_addresses: set[str] = set()

    for device in coordinator.get_all_devices():
        if device.device_type in CLIMATE_DEVICE_TYPES:
            entities.append(CulMaxClimate(coordinator, device))
            known_addresses.add(device.address)

    # Also handle dynamically paired devices
    @callback
    def on_new_device(msg: MaxMessage, decoded: Any) -> None:
        device = None
        if isinstance(decoded, KnownDevice):
            device = decoded
        else:
            device = coordinator.get_device(msg.src_hex)

        if (
            device
            and device.device_type in CLIMATE_DEVICE_TYPES
            and device.address not in known_addresses
        ):
            known_addresses.add(device.address)
            async_add_entities([CulMaxClimate(coordinator, device)])

    entry.async_on_unload(coordinator.add_global_listener(on_new_device))

    async_add_entities(entities)


class CulMaxClimate(ClimateEntity):
    """Climate entity for a MAX! HeatingThermostat or WallMountedThermostat."""

    _attr_has_entity_name = False
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = TEMP_MIN
    _attr_max_temp = TEMP_MAX
    _attr_target_temperature_step = 0.5
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = ["none", "boost"]

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address
        self._state: ThermostatState | None = None

        self._attr_unique_id = f"{DOMAIN}_{self._address}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=device.name,
            manufacturer="eQ-3",
            model=coordinator.get_device_registry_model(device),
        )

        # Set default values to prevent AttributeError
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_native_target_temperature = None
        self._attr_native_current_temperature = None
        self._attr_hvac_action = HVACAction.IDLE
        self._attr_preset_mode = "none"
        self._attr_available = False
        # Feedback for the last write: idle / sending / confirmed / failed
        self._command_status = "idle"
        self._command_error: str | None = None
        self._command_requested: str | None = None

    def _raw_mode(self) -> int:
        """Return the last raw MAX! mode, defaulting conservatively to manual."""
        if self._state is not None:
            return self._state.mode
        last = self._device.last_state or {}
        mode = last.get("mode")
        return int(mode) if mode is not None else MODE_MANUAL

    def _temperature_write_mode(self) -> int:
        """Choose a SetTemperature mode that preserves the current operating style."""
        raw_mode = self._raw_mode()
        if raw_mode in (MODE_AUTO, MODE_VACATION):
            return MODE_AUTO
        return MODE_MANUAL

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_listener(self._address, self._on_message)
        )
        self.async_on_remove(
            self._coordinator.add_week_profile_listener(self._address, self._on_week_profile_update)
        )
        # Pending-queue progress (e.g. week profile upload) changes attributes.
        self.async_on_remove(
            self._coordinator.add_diagnostic_listener(self._address, self._on_week_profile_update)
        )
        # Restore last known state if available
        last = self._device.last_state
        if last:
            self._apply_state_dict(last)
            self._attr_available = True

    @callback
    def _on_message(self, msg: MaxMessage, decoded: ThermostatState | None) -> None:
        if decoded is None:
            return
        self._state = decoded
        self._apply_state_dict(decoded.__dict__)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _on_week_profile_update(self) -> None:
        """Refresh attributes when the stored week profile changes."""
        self.async_write_ha_state()

    def _apply_state_dict(self, state: dict) -> None:
        """Apply state dict (from ThermostatState or stored last_state)."""
        self._attr_native_target_temperature = state.get("desired_temperature")
        measured = state.get("measured_temperature")
        if measured is not None:
            self._attr_native_current_temperature = measured
        mode = state.get("mode", MODE_MANUAL)
        self._attr_hvac_mode = self._hvac_mode_for(mode, self._attr_native_target_temperature)
        self._attr_preset_mode = "boost" if mode == MODE_BOOST else "none"

        valve = state.get("valve_position", 0)
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_action = HVACAction.IDLE
        elif valve and valve > 0:
            self._attr_hvac_action = HVACAction.HEATING
        else:
            self._attr_hvac_action = HVACAction.IDLE

    @staticmethod
    def _hvac_mode_for(mode: int, target: float | None) -> HVACMode:
        """Map MAX! mode + target to HA; manual at 4.5 °C is the MAX! 'off'."""
        if mode == MODE_MANUAL and target is not None and target <= TEMP_OFF:
            return HVACMode.OFF
        return HVAC_MODE_MAP.get(mode, HVACMode.HEAT)

    def _restore_confirmed_state(self) -> None:
        """Drop optimistic values and show the last state reported by the device."""
        last = self._device.last_state
        if last:
            self._apply_state_dict(last)

    async def _async_write_with_feedback(
        self,
        *,
        description: str,
        temperature: float,
        mode: int,
        optimistic_target: float | None,
        optimistic_hvac: HVACMode,
        optimistic_preset: str = "none",
    ) -> None:
        """Show the requested value at once, then confirm or roll back on ACK.

        The thermostat's ACK carries its new mode and target, which the
        coordinator applies to this entity before the call returns, so after
        success the displayed values are the device-confirmed ones.
        """
        self._attr_native_target_temperature = optimistic_target
        self._attr_hvac_mode = optimistic_hvac
        self._attr_preset_mode = optimistic_preset
        self._command_status = "sending"
        self._command_error = None
        self._command_requested = description
        self.async_write_ha_state()
        try:
            await self._coordinator.async_set_temperature(
                self._address, temperature, mode=mode
            )
        except Exception as err:
            self._command_status = "failed"
            self._command_error = str(err)
            self._restore_confirmed_state()
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"{self._device.name}: {description} wurde nicht bestätigt ({err})"
            ) from err
        self._command_status = "confirmed"
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        effective_week_profile = self._coordinator.get_effective_week_profile(self._address)
        attrs: dict[str, Any] = {
            "command_status": self._command_status,
            "command_requested": self._command_requested,
            "command_error": self._command_error,
            "address": self._address,
            "serial_number": self._device.serial_number or None,
            "firmware_version": self._device.firmware_version or None,
            "is_paired": self._coordinator.is_device_paired(self._address),
            "pairing_state": self._coordinator.get_pairing_state(self._address),
            "paired_elsewhere_central": self._device.foreign_central or None,
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
            "mode_detail": MODE_NAMES.get(self._raw_mode(), self._raw_mode()),
            "mode_is_temporary": self._raw_mode() == MODE_VACATION,
            "expected_week_profile_temperature": self._coordinator.get_expected_week_profile_temperature(self._address),
            "group_id": self._device.group_id,
            "linked_partners": self._device.linked_partners,
            "comfort_temperature": self._device.comfort_temperature,
            "eco_temperature": self._device.eco_temperature,
            "window_open_temperature": self._device.window_open_temperature,
            "window_open_duration_min": self._device.window_open_duration,
            "measurement_offset": self._device.measurement_offset,
            "peer_names": self._coordinator.get_peer_names(self._address),
            "peer_labels": self._coordinator.get_peer_labels(self._address),
            "supported_partner_types": self._coordinator.get_supported_partner_type_names(self._device.device_type),
        }
        validation = self._coordinator.get_week_profile_validation(self._address)
        attrs["week_profile_validation"] = validation.get("state")
        attrs["week_profile_validation_reason"] = validation.get("reason")
        attrs["window_open_active"] = validation.get("window_open_active")
        attrs["open_window_partners"] = validation.get("open_window_partners")
        attrs["open_window_partner_names"] = validation.get("open_window_partner_names")
        attrs["actual_target_temperature"] = validation.get("actual_target_temperature")
        attrs["temperature_delta_to_expected"] = validation.get("temperature_delta")
        attrs.update(self._coordinator.get_pending_queue_details(self._address))
        if effective_week_profile:
            attrs["week_profile_lines"] = format_week_profile_lines(effective_week_profile)
            attrs.update(
                {
                    f"week_profile_{day}": value
                    for day, value in format_week_profile_by_day(effective_week_profile).items()
                }
            )
            if effective_week_profile != self._device.week_profile:
                attrs["week_profile_source"] = "linked_partner"
        if self._state and hasattr(self._state, 'valve_position'):
            attrs["valve_position"] = self._state.valve_position
            attrs["battery_low"] = self._state.battery_low
            attrs["rf_error"] = self._state.rf_error
            attrs["panel_locked"] = self._state.panel_locked
            if self._state.display_actual_temperature is not None:
                attrs["display_actual_temperature"] = self._state.display_actual_temperature
            if self._state.heater_temperature is not None:
                attrs["heater_temperature"] = self._state.heater_temperature
            if self._state.until is not None:
                attrs["until"] = self._state.until
            if self._state.boost_duration is not None:
                attrs["boost_duration_min"] = self._state.boost_duration
        return attrs

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        temperature = float(temperature)
        mode = self._temperature_write_mode()
        await self._async_write_with_feedback(
            description=f"Solltemperatur {temperature:.1f} °C",
            temperature=temperature,
            mode=mode,
            optimistic_target=temperature,
            optimistic_hvac=self._hvac_mode_for(mode, temperature),
        )

    def _heat_target(self) -> float:
        """Target used when switching to HEAT (never the 4.5 °C 'off' value)."""
        current = self._attr_native_target_temperature
        if current is not None and current > TEMP_OFF:
            return current
        return self._device.comfort_temperature or 20.0

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_write_with_feedback(
                description="Aus",
                temperature=TEMP_MIN,
                mode=MODE_MANUAL,
                optimistic_target=TEMP_MIN,
                optimistic_hvac=HVACMode.OFF,
            )
        elif hvac_mode == HVACMode.AUTO:
            expected = self._coordinator.get_expected_week_profile_temperature(self._address)
            await self._async_write_with_feedback(
                description="Automatik (Wochenprogramm)",
                temperature=0.0,
                mode=MODE_AUTO,
                optimistic_target=expected if expected is not None else self._attr_native_target_temperature,
                optimistic_hvac=HVACMode.AUTO,
            )
        else:
            target = self._heat_target()
            await self._async_write_with_feedback(
                description=f"Manuell {target:.1f} °C",
                temperature=target,
                mode=MODE_MANUAL,
                optimistic_target=target,
                optimistic_hvac=HVACMode.HEAT,
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == "boost":
            await self._async_write_with_feedback(
                description="Boost",
                temperature=self._attr_native_target_temperature or 20.0,
                mode=MODE_BOOST,
                optimistic_target=self._attr_native_target_temperature,
                optimistic_hvac=HVACMode.HEAT,
                optimistic_preset="boost",
            )
            return
        if self._raw_mode() != MODE_BOOST:
            return
        # Leaving boost: return to the week program.
        await self.async_set_hvac_mode(HVACMode.AUTO)
