"""Diagnostics download for MAX! via CUL (integration and single device)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import CulMaxConfigEntry
from .const import DOMAIN

TO_REDACT = {"host"}


def _device_details(coordinator, address: str) -> dict[str, Any]:
    device = coordinator.get_device(address)
    if device is None:
        return {}
    data = asdict(device)
    data["pairing_state"] = coordinator.get_pairing_state(address)
    data["pending_queue"] = coordinator.get_pending_queue_details(address)
    data["external_temperature"] = coordinator.get_external_temperature_status(address)
    if device.device_type in (1, 2, 3):
        data["week_profile_validation"] = coordinator.get_week_profile_validation(address)
    return data


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CulMaxConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "send_budget": coordinator.get_cul_credit_status(),
        "send_profile": coordinator.send_profile.name,
        "virtual_wall_thermostat": f"{coordinator.virtual_wall_thermostat_address:06X}",
        "topology": coordinator.export_topology(),
        "devices": {
            device.address: _device_details(coordinator, device.address)
            for device in coordinator.get_all_devices()
        },
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: CulMaxConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    addresses = [ident for domain, ident in device.identifiers if domain == DOMAIN]
    if not addresses:
        return {}
    if addresses[0] == coordinator.controller_identifier:
        return {
            "send_budget": coordinator.get_cul_credit_status(),
            "send_profile": coordinator.send_profile.name,
            "devices": len(coordinator.get_all_devices()),
        }
    return _device_details(coordinator, addresses[0])
