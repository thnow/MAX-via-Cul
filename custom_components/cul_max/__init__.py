"""MAX! via CUL custom integration for Home Assistant."""
from __future__ import annotations

from datetime import datetime
import json
import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CLIMATE_DEVICE_TYPES,
    CONF_HOST,
    CONF_OWN_ADDRESS,
    CONF_PORT,
    DEFAULT_OWN_ADDRESS,
    DEFAULT_PORT,
    DOMAIN,
    MODE_AUTO,
    MODE_BOOST,
    MODE_MANUAL,
    MODE_VACATION,
    PLATFORMS,
)
from .coordinator import CulMaxCoordinator
from .frontend import async_register_frontend

_LOGGER = logging.getLogger(__name__)

type CulMaxConfigEntry = ConfigEntry[CulMaxCoordinator]

DAY_FIELD_TO_LABEL = {
    "monday": "Mon",
    "tuesday": "Tue",
    "wednesday": "Wed",
    "thursday": "Thu",
    "friday": "Fri",
    "saturday": "Sat",
    "sunday": "Sun",
}

SERVICE_NAMES: tuple[str, ...] = (
    "start_pairing",
    "set_device_name",
    "wake_thermostats",
    "sync_time",
    "set_week_profile",
    "set_week_profile_days",
    "set_group_id",
    "set_temperature_config",
    "set_desired_temperature",
    "remove_group_id",
    "add_link_partner",
    "remove_link_partner",
    "associate_devices",
    "deassociate_devices",
    "create_virtual_shutter_contact",
    "delete_virtual_device",
    "send_virtual_shutter_contact_state",
    "create_room_association",
    "delete_room_association",
    "rebuild_room_association",
    "export_topology",
    "import_topology",
    "cleanup_superseded_devices",
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up shared integration resources."""

    async def _setup_frontend(_event=None) -> None:
        await async_register_frontend(hass)

    if hass.state == CoreState.running:
        await _setup_frontend()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _setup_frontend)

    return True


def _resolve_device_address(
    hass: HomeAssistant,
    call: ServiceCall,
) -> str | None:
    """Resolve a MAX! device address from address or entity_id."""
    address = call.data.get("address")
    if address:
        return str(address).upper()

    entity_id = call.data.get("entity_id")
    if not entity_id:
        return None

    return _resolve_device_address_from_entity_id(hass, entity_id)


def _resolve_device_address_from_entity_id(
    hass: HomeAssistant,
    entity_id: str,
) -> str | None:
    """Resolve a MAX! device address from an entity ID."""
    if not entity_id:
        return None

    state = hass.states.get(entity_id)
    if state:
        state_address = state.attributes.get("address")
        if state_address:
            return str(state_address).upper()

    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry and entry.unique_id.startswith(f"{DOMAIN}_"):
        return entry.unique_id.removeprefix(f"{DOMAIN}_").split("_", 1)[0].upper()

    return None


def _resolve_device_address_from_name(
    coordinator: CulMaxCoordinator,
    name: str,
) -> str | None:
    """Resolve a MAX! device address from its configured device name."""
    needle = name.strip().casefold()
    if not needle:
        return None

    exact_matches: list[str] = []
    partial_matches: list[str] = []
    for device in coordinator.get_all_devices():
        haystack = device.name.strip().casefold()
        if haystack == needle:
            exact_matches.append(device.address)
            continue
        if needle in haystack:
            partial_matches.append(device.address)

    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        _LOGGER.warning(
            "Ambiguous exact MAX! device name '%s' matches multiple addresses: %s",
            name,
            exact_matches,
        )
        return None
    if len(partial_matches) == 1:
        return partial_matches[0]
    if len(partial_matches) > 1:
        _LOGGER.warning(
            "Ambiguous partial MAX! device name '%s' matches multiple addresses: %s",
            name,
            partial_matches,
        )
        return None
    _LOGGER.warning("Unknown MAX! device name '%s'", name)
    return None


def _coerce_bool_value(value: object) -> bool:
    """Coerce service values like True/'true'/'on'/'1' to a real bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "on", "open", "yes"}:
            return True
        if normalized in {"0", "false", "off", "closed", "no"}:
            return False
    return bool(value)


def _resolve_device_addresses(
    hass: HomeAssistant,
    coordinator: CulMaxCoordinator,
    call: ServiceCall,
) -> list[str]:
    """Resolve one or more MAX! device addresses from explicit fields or entity IDs."""
    addresses: list[str] = []

    address = call.data.get("address")
    if address:
        addresses.append(str(address).upper())

    for raw_address in call.data.get("addresses", []) or []:
        addresses.append(str(raw_address).upper())

    entity_id = call.data.get("entity_id")
    if entity_id:
        resolved = _resolve_device_address(hass, call)
        if resolved:
            addresses.append(resolved)

    device_name = call.data.get("device_name")
    if device_name:
        resolved = _resolve_device_address_from_name(coordinator, str(device_name))
        if resolved:
            addresses.append(resolved)

    for entity in call.data.get("entity_ids", []) or []:
        resolved = _resolve_device_address_from_entity_id(hass, entity)
        if resolved:
            addresses.append(resolved)

    for device_name in call.data.get("device_names", []) or []:
        resolved = _resolve_device_address_from_name(coordinator, str(device_name))
        if resolved:
            addresses.append(resolved)

    return list(dict.fromkeys(addresses))


def _resolve_addresses_from_data(
    hass: HomeAssistant,
    coordinator: CulMaxCoordinator,
    data: dict,
    *,
    address_key: str | None = None,
    addresses_key: str | None = None,
    entity_id_key: str | None = None,
    entity_ids_key: str | None = None,
    device_name_key: str | None = None,
    device_names_key: str | None = None,
) -> list[str]:
    """Resolve one or more device addresses from arbitrary service data keys."""
    resolved: list[str] = []

    if address_key and data.get(address_key):
        resolved.append(str(data[address_key]).upper())
    if addresses_key:
        for address in data.get(addresses_key, []) or []:
            resolved.append(str(address).upper())
    if entity_id_key and data.get(entity_id_key):
        address = _resolve_device_address_from_entity_id(hass, str(data[entity_id_key]))
        if address:
            resolved.append(address)
    if entity_ids_key:
        for entity_id in data.get(entity_ids_key, []) or []:
            address = _resolve_device_address_from_entity_id(hass, str(entity_id))
            if address:
                resolved.append(address)
    if device_name_key and data.get(device_name_key):
        address = _resolve_device_address_from_name(coordinator, str(data[device_name_key]))
        if address:
            resolved.append(address)
    if device_names_key:
        for device_name in data.get(device_names_key, []) or []:
            address = _resolve_device_address_from_name(coordinator, str(device_name))
            if address:
                resolved.append(address)

    return list(dict.fromkeys(resolved))


def _parse_until_value(hass: HomeAssistant, raw: str) -> datetime:
    """Parse a user-supplied until value into a timezone-aware local datetime."""
    text = raw.strip()
    if not text:
        raise ValueError("Leerer until-Wert.")

    parsed = dt_util.parse_datetime(text)
    if parsed is None:
        for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(
            "Until muss als ISO-Zeit oder im Format TT.MM.JJJJ HH:MM angegeben werden."
        )

    if parsed.tzinfo is None:
        timezone = dt_util.get_time_zone(hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
        parsed = parsed.replace(tzinfo=timezone)
    else:
        parsed = dt_util.as_local(parsed)

    if parsed.minute not in (0, 30):
        raise ValueError("Until-Zeiten muessen bei MAX! auf :00 oder :30 liegen.")
    if parsed <= dt_util.now():
        raise ValueError("Until-Zeitpunkt muss in der Zukunft liegen.")
    return parsed


async def async_setup_entry(hass: HomeAssistant, entry: CulMaxConfigEntry) -> bool:
    """Set up MAX! via CUL from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    own_address_str = entry.data.get(CONF_OWN_ADDRESS, f"{DEFAULT_OWN_ADDRESS:06X}")

    try:
        own_address = int(own_address_str, 16)
    except ValueError:
        own_address = DEFAULT_OWN_ADDRESS

    coordinator = CulMaxCoordinator(
        hass=hass,
        host=host,
        port=port,
        own_address=own_address,
    )

    if not await coordinator.async_setup():
        raise ConfigEntryNotReady(f"Cannot connect to CULFW at {host}:{port}")

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, coordinator)
    return True


def _register_services(hass: HomeAssistant, coordinator: CulMaxCoordinator) -> None:
    """Register integration-level services."""

    def _register(
        service_name: str,
        handler,
        *,
        schema: vol.Schema | None = None,
        supports_response: SupportsResponse = SupportsResponse.NONE,
    ) -> None:
        """Register a service under the integration domain."""
        hass.services.async_register(
            DOMAIN,
            service_name,
            handler,
            schema=schema,
            supports_response=supports_response,
        )

    def _device_payload(address: str | None) -> dict[str, object] | None:
        """Return one compact, user-facing device descriptor."""
        if not address:
            return None
        normalized = address.upper()
        device = coordinator.get_device(normalized)
        payload: dict[str, object] = {
            "address": normalized,
            "label": coordinator.format_device_label(normalized),
        }
        if device is not None:
            payload["name"] = device.name
            payload["serial_number"] = device.serial_number or ""
            payload["paired"] = device.paired
            payload["is_virtual"] = device.is_virtual
            payload["group_id"] = device.group_id
        return payload

    def _devices_payload(addresses: list[str]) -> list[dict[str, object]]:
        """Return multiple compact device descriptors."""
        return [
            payload
            for payload in (_device_payload(address) for address in addresses)
            if payload is not None
        ]

    async def handle_start_pairing(call: ServiceCall) -> dict[str, object]:
        duration = int(call.data.get("duration", 60))
        await coordinator.async_start_pairing(duration)
        pairing_until = coordinator.pairing_until
        return {
            "duration": duration,
            "pairing_mode": coordinator.is_pairing_mode,
            "pairing_until": pairing_until.isoformat() if pairing_until else None,
            "remaining_seconds": coordinator.get_pairing_remaining_seconds(),
        }

    async def handle_set_device_name(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("set_device_name: missing address, entity_id or device_name")
            return
        name = call.data["name"]
        device = coordinator.get_device(address)
        if device is None:
            _LOGGER.error("set_device_name: unknown device address %s", address)
            return
        device.name = name
        await coordinator._save_devices()
        _LOGGER.info("Renamed device %s to '%s'", address, name)
        return {
            "device": _device_payload(address),
            "name": name,
        }

    async def handle_wake_thermostats(call: ServiceCall) -> dict[str, object]:
        addresses = [
            device.address
            for device in coordinator.get_all_devices()
            if device.device_type in CLIMATE_DEVICE_TYPES
        ]
        await coordinator.async_wake_all_thermostats()
        return {
            "devices": _devices_payload(addresses),
            "count": len(addresses),
        }

    async def handle_sync_time(call: ServiceCall) -> dict[str, object]:
        addresses = _resolve_device_addresses(hass, coordinator, call)
        synced = await coordinator.async_sync_time(addresses or None)
        _LOGGER.info("Synchronized time to MAX! devices: %s", synced)
        return {
            "requested_devices": _devices_payload(addresses),
            "synced_devices": _devices_payload(synced),
            "count": len(synced),
        }

    async def handle_set_week_profile(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("set_week_profile: missing address, entity_id or device_name")
            return
        profile = call.data["profile"]
        summary = await coordinator.async_set_week_profile(address, profile)
        _LOGGER.info("Set week profile for %s:\n%s", address, summary)
        return {
            "device": _device_payload(address),
            "summary": summary,
            "lines": summary.splitlines(),
        }

    async def handle_set_week_profile_days(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("set_week_profile_days: missing address, entity_id or device_name")
            return
        lines: list[str] = []
        for field, day_label in DAY_FIELD_TO_LABEL.items():
            day_profile = call.data.get(field)
            if day_profile:
                lines.append(f"{day_label} {day_profile.strip()}")

        if not lines:
            _LOGGER.error("set_week_profile_days: no day profiles supplied for %s", address)
            return

        summary = await coordinator.async_set_week_profile(address, "\n".join(lines))
        _LOGGER.info("Set week profile by day fields for %s:\n%s", address, summary)
        return {
            "device": _device_payload(address),
            "updated_days": [line.split(" ", 1)[0] for line in lines],
            "summary": summary,
            "lines": summary.splitlines(),
        }

    async def handle_set_group_id(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("set_group_id: missing address, entity_id or device_name")
            return
        group_id = int(call.data["group_id"])
        await coordinator.async_set_group_id(address, group_id)
        return {"device": _device_payload(address), "group_id": group_id}

    async def handle_set_temperature_config(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("set_temperature_config: missing address, entity_id or device_name")
            return
        updates = {
            "comfort_temperature": call.data.get("comfort_temperature"),
            "eco_temperature": call.data.get("eco_temperature"),
            "window_open_temperature": call.data.get("window_open_temperature"),
            "window_open_duration": call.data.get("window_open_duration"),
            "measurement_offset": call.data.get("measurement_offset"),
        }
        await coordinator._async_send_temperature_config(
            address,
            comfort_temperature=updates["comfort_temperature"],
            eco_temperature=updates["eco_temperature"],
            window_open_temperature=updates["window_open_temperature"],
            window_open_duration=updates["window_open_duration"],
            measurement_offset=updates["measurement_offset"],
        )
        device = coordinator.get_device(address)
        return {
            "device": _device_payload(address),
            "requested_updates": {key: value for key, value in updates.items() if value is not None},
            "comfort_temperature": device.comfort_temperature if device else None,
            "eco_temperature": device.eco_temperature if device else None,
            "window_open_temperature": device.window_open_temperature if device else None,
            "window_open_duration": device.window_open_duration if device else None,
            "measurement_offset": device.measurement_offset if device else None,
        }

    async def handle_set_desired_temperature(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("set_desired_temperature: missing address, entity_id or device_name")
            return

        mode_name = str(call.data.get("mode", "")).strip().lower()
        keep_auto = bool(call.data.get("keep_auto", False))
        until_text = str(call.data.get("until", "")).strip()
        temperature = call.data.get("temperature")

        if mode_name == "boost":
            await coordinator.async_set_temperature(address, 0.0, mode=MODE_BOOST)
            return {
                "device": _device_payload(address),
                "mode": "boost",
                "temperature": 0.0,
            }

        if until_text:
            if temperature is None:
                raise ValueError("set_desired_temperature mit until braucht eine Temperatur.")
            until = _parse_until_value(hass, until_text)
            await coordinator.async_set_temperature(
                address,
                float(temperature),
                mode=MODE_MANUAL,
                until=until,
            )
            return {
                "device": _device_payload(address),
                "mode": "until",
                "temperature": float(temperature),
                "until": until.isoformat(),
            }

        if mode_name == "auto":
            await coordinator.async_set_temperature(
                address,
                float(temperature) if temperature is not None else 0.0,
                mode=MODE_AUTO,
            )
            return {
                "device": _device_payload(address),
                "mode": "auto",
                "temperature": float(temperature) if temperature is not None else 0.0,
            }

        if mode_name == "manual":
            if temperature is None:
                raise ValueError("set_desired_temperature im manual-Modus braucht eine Temperatur.")
            await coordinator.async_set_temperature(address, float(temperature), mode=MODE_MANUAL)
            return {
                "device": _device_payload(address),
                "mode": "manual",
                "temperature": float(temperature),
            }

        if temperature is None:
            raise ValueError("set_desired_temperature braucht eine Temperatur oder einen expliziten Modus.")

        current_mode = coordinator.get_raw_mode(address)
        if keep_auto and current_mode in (MODE_AUTO, MODE_VACATION):
            await coordinator.async_set_temperature(address, float(temperature), mode=MODE_AUTO)
            effective_mode = "auto"
        else:
            await coordinator.async_set_temperature(address, float(temperature), mode=MODE_MANUAL)
            effective_mode = "manual"
        return {
            "device": _device_payload(address),
            "mode": effective_mode,
            "temperature": float(temperature),
            "keep_auto": keep_auto,
            "raw_mode_before": current_mode,
        }

    async def handle_remove_group_id(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("remove_group_id: missing address, entity_id or device_name")
            return
        await coordinator.async_remove_group_id(address)
        return {"device": _device_payload(address), "group_id": 0}

    async def handle_add_link_partner(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("add_link_partner: missing source address, entity_id or device_name")
            return

        partner_address = call.data.get("partner_address")
        if partner_address:
            resolved_partner = str(partner_address).upper()
        elif call.data.get("partner_entity_id"):
            partner_entity = call.data.get("partner_entity_id")
            resolved_partner = _resolve_device_address_from_entity_id(hass, partner_entity)
            if resolved_partner is None:
                _LOGGER.error("add_link_partner: could not resolve partner entity %s", partner_entity)
                return
        elif call.data.get("partner_name"):
            partner_name = str(call.data["partner_name"])
            resolved_partner = _resolve_device_address_from_name(coordinator, partner_name)
            if resolved_partner is None:
                _LOGGER.error("add_link_partner: could not resolve partner name %s", partner_name)
                return
        else:
            _LOGGER.error("add_link_partner: missing partner_address, partner_entity_id or partner_name")
            return

        await coordinator.async_add_link_partner(address, resolved_partner)
        return {
            "device": _device_payload(address),
            "partner": _device_payload(resolved_partner),
        }

    async def handle_remove_link_partner(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("remove_link_partner: missing source address, entity_id or device_name")
            return

        partner_address = call.data.get("partner_address")
        if partner_address:
            resolved_partner = str(partner_address).upper()
        elif call.data.get("partner_entity_id"):
            partner_entity = call.data.get("partner_entity_id")
            resolved_partner = _resolve_device_address_from_entity_id(hass, partner_entity)
            if resolved_partner is None:
                _LOGGER.error(
                    "remove_link_partner: could not resolve partner entity %s",
                    partner_entity,
                )
                return
        elif call.data.get("partner_name"):
            partner_name = str(call.data["partner_name"])
            resolved_partner = _resolve_device_address_from_name(coordinator, partner_name)
            if resolved_partner is None:
                _LOGGER.error("remove_link_partner: could not resolve partner name %s", partner_name)
                return
        else:
            _LOGGER.error(
                "remove_link_partner: missing partner_address, partner_entity_id or partner_name"
            )
            return

        await coordinator.async_remove_link_partner(address, resolved_partner)
        return {
            "device": _device_payload(address),
            "partner": _device_payload(resolved_partner),
        }

    async def handle_associate_devices(call: ServiceCall) -> dict[str, object] | None:
        addresses = _resolve_device_addresses(hass, coordinator, call)
        if len(addresses) < 2:
            _LOGGER.error("associate_devices: need at least two addresses, entity_ids or device_names")
            return
        group_id = int(call.data["group_id"])
        bidirectional = bool(call.data.get("bidirectional", True))
        await coordinator.async_associate_devices(
            addresses,
            group_id,
            bidirectional,
        )
        return {
            "devices": _devices_payload(addresses),
            "group_id": group_id,
            "bidirectional": bidirectional,
        }

    async def handle_deassociate_devices(call: ServiceCall) -> dict[str, object] | None:
        addresses = _resolve_device_addresses(hass, coordinator, call)
        if len(addresses) < 2:
            _LOGGER.error("deassociate_devices: need at least two addresses, entity_ids or device_names")
            return
        clear_group_id = bool(call.data.get("clear_group_id", False))
        bidirectional = bool(call.data.get("bidirectional", True))
        await coordinator.async_deassociate_devices(
            addresses,
            clear_group_id,
            bidirectional,
        )
        return {
            "devices": _devices_payload(addresses),
            "clear_group_id": clear_group_id,
            "bidirectional": bidirectional,
        }

    async def handle_create_virtual_shutter_contact(call: ServiceCall) -> dict[str, object]:
        address = str(call.data["address"]).upper()
        name = str(call.data["name"])
        group_id = int(call.data.get("group_id", 0))
        await coordinator.async_create_virtual_shutter_contact(address, name, group_id)
        return {"device": _device_payload(address), "name": name, "group_id": group_id}

    async def handle_delete_virtual_device(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("delete_virtual_device: missing address, entity_id or device_name")
            return
        device_info = _device_payload(address)
        await coordinator.async_delete_virtual_device(address)
        return {"device": device_info}

    async def handle_send_virtual_shutter_contact_state(call: ServiceCall) -> dict[str, object] | None:
        address = _resolve_device_address(hass, call)
        if address is None and call.data.get("device_name"):
            address = _resolve_device_address_from_name(coordinator, str(call.data["device_name"]))
        if address is None:
            _LOGGER.error("send_virtual_shutter_contact_state: missing address, entity_id or device_name")
            return
        is_open = _coerce_bool_value(call.data["is_open"])
        await coordinator.async_send_virtual_shutter_contact_state(
            address,
            is_open,
        )
        return {"device": _device_payload(address), "is_open": is_open}

    async def handle_create_room_association(call: ServiceCall) -> dict[str, object]:
        climate_addresses = _resolve_addresses_from_data(
            hass,
            coordinator,
            call.data,
            address_key="climate_address",
            addresses_key="climate_addresses",
            entity_id_key="climate_entity_id",
            entity_ids_key="climate_entity_ids",
            device_name_key="climate_device_name",
            device_names_key="climate_device_names",
        )
        window_addresses = _resolve_addresses_from_data(
            hass,
            coordinator,
            call.data,
            address_key="window_address",
            addresses_key="window_addresses",
            entity_id_key="window_entity_id",
            entity_ids_key="window_entity_ids",
            device_name_key="window_device_name",
            device_names_key="window_device_names",
        )
        _LOGGER.info(
            "create_room_association resolve: climates=%s -> %s windows=%s -> %s",
            call.data.get("climate_device_names") or call.data.get("climate_addresses") or call.data.get("climate_entity_ids") or call.data.get("climate_entity_id") or call.data.get("climate_device_name") or call.data.get("climate_address"),
            climate_addresses,
            call.data.get("window_device_names") or call.data.get("window_addresses") or call.data.get("window_entity_ids") or call.data.get("window_entity_id") or call.data.get("window_device_name") or call.data.get("window_address"),
            window_addresses,
        )

        result = await coordinator.async_create_room_association(
            room_name=str(call.data["room_name"]),
            climate_addresses=climate_addresses,
            window_addresses=window_addresses,
            group_id=call.data.get("group_id"),
            create_virtual_shutter_contact=bool(
                call.data.get("create_virtual_shutter_contact", False)
            ),
            virtual_shutter_contact_address=call.data.get("virtual_shutter_contact_address"),
            virtual_shutter_contact_name=call.data.get("virtual_shutter_contact_name"),
            bidirectional=bool(call.data.get("bidirectional", True)),
        )
        _LOGGER.info(
            "Created room association '%s' with group_id=%s climate=%s windows=%s virtual=%s",
            result["room_name"],
            result["group_id"],
            result["climate_addresses"],
            result["window_addresses"],
            result["virtual_shutter_contact_address"],
        )
        compact_response = {
            "room_name": result["room_name"],
            "status": result["status"],
            "summary": result.get("summary"),
            "group_id": result["group_id"],
            "virtual_device": _device_payload(result["virtual_shutter_contact_address"]),
            "counts": {
                "climates": len(result["climate_addresses"]),
                "windows": len(result["window_addresses"]),
                "completed_links": len(result.get("completed_links", [])),
                "missing_links": len(result.get("missing_links", [])),
                "pending_links": len(result.get("pending_links", [])),
                "missing_group_ids": len(result.get("missing_group_ids", [])),
                "pending_group_ids": len(result.get("pending_group_ids", [])),
                "errors": len(result.get("errors", [])),
            },
            "climate_devices": _devices_payload(result["climate_addresses"]),
            "window_devices": _devices_payload(result["window_addresses"]),
            "missing_group_ids": result.get("missing_group_ids", []),
            "pending_group_ids": result.get("pending_group_ids", []),
            "missing_links": result.get("missing_links", []),
            "pending_links": result.get("pending_links", []),
            "activity_required_devices": result.get("activity_required_devices", []),
            "pending_devices": result.get("pending_devices", []),
            "errors": result.get("errors", []),
            "retry_plan": result.get("retry_plan", {}),
        }
        return compact_response

    async def handle_delete_room_association(call: ServiceCall) -> dict[str, object]:
        climate_addresses = _resolve_addresses_from_data(
            hass,
            coordinator,
            call.data,
            address_key="climate_address",
            addresses_key="climate_addresses",
            entity_id_key="climate_entity_id",
            entity_ids_key="climate_entity_ids",
            device_name_key="climate_device_name",
            device_names_key="climate_device_names",
        )
        window_addresses = _resolve_addresses_from_data(
            hass,
            coordinator,
            call.data,
            address_key="window_address",
            addresses_key="window_addresses",
            entity_id_key="window_entity_id",
            entity_ids_key="window_entity_ids",
            device_name_key="window_device_name",
            device_names_key="window_device_names",
        )

        result = await coordinator.async_delete_room_association(
            room_name=str(call.data["room_name"]),
            climate_addresses=climate_addresses,
            window_addresses=window_addresses,
            clear_group_id=bool(call.data.get("clear_group_id", True)),
            delete_virtual_shutter_contacts=bool(
                call.data.get("delete_virtual_shutter_contacts", False)
            ),
            bidirectional=bool(call.data.get("bidirectional", True)),
        )
        _LOGGER.info(
            "Deleted room association '%s' climate=%s windows=%s deleted_virtual=%s",
            result["room_name"],
            result["climate_addresses"],
            result["window_addresses"],
            result["deleted_virtual_addresses"],
        )
        return {
            **result,
            "climate_devices": _devices_payload(result["climate_addresses"]),
            "window_devices": _devices_payload(result["window_addresses"]),
            "deleted_virtual_devices": _devices_payload(result["deleted_virtual_addresses"]),
        }

    async def handle_rebuild_room_association(call: ServiceCall) -> dict[str, object]:
        climate_addresses = _resolve_addresses_from_data(
            hass,
            coordinator,
            call.data,
            address_key="climate_address",
            addresses_key="climate_addresses",
            entity_id_key="climate_entity_id",
            entity_ids_key="climate_entity_ids",
            device_name_key="climate_device_name",
            device_names_key="climate_device_names",
        )
        window_addresses = _resolve_addresses_from_data(
            hass,
            coordinator,
            call.data,
            address_key="window_address",
            addresses_key="window_addresses",
            entity_id_key="window_entity_id",
            entity_ids_key="window_entity_ids",
            device_name_key="window_device_name",
            device_names_key="window_device_names",
        )

        result = await coordinator.async_rebuild_room_association(
            room_name=str(call.data["room_name"]),
            climate_addresses=climate_addresses,
            window_addresses=window_addresses,
            group_id=call.data.get("group_id"),
            create_virtual_shutter_contact=bool(
                call.data.get("create_virtual_shutter_contact", False)
            ),
            virtual_shutter_contact_address=call.data.get("virtual_shutter_contact_address"),
            virtual_shutter_contact_name=call.data.get("virtual_shutter_contact_name"),
            clear_group_id=bool(call.data.get("clear_group_id", True)),
            delete_virtual_shutter_contacts=bool(
                call.data.get("delete_virtual_shutter_contacts", False)
            ),
            bidirectional=bool(call.data.get("bidirectional", True)),
        )
        _LOGGER.info(
            "Rebuilt room association '%s' with group_id=%s climate=%s windows=%s virtual=%s",
            result["room_name"],
            result["group_id"],
            result["climate_addresses"],
            result["window_addresses"],
            result["virtual_shutter_contact_address"],
        )
        return {
            **result,
            "climate_devices": _devices_payload(result["climate_addresses"]),
            "window_devices": _devices_payload(result["window_addresses"]),
            "virtual_device": _device_payload(result["virtual_shutter_contact_address"]),
        }

    async def handle_export_topology(call: ServiceCall) -> dict[str, object]:
        path = call.data.get("path")
        written_path = await coordinator.async_export_topology_to_file(path)
        snapshot = coordinator.export_topology()
        _LOGGER.info(
            "Exported MAX! topology with %d devices to %s",
            snapshot["device_count"],
            written_path,
        )
        return {
            "path": written_path,
            "device_count": snapshot["device_count"],
            "schema_version": snapshot.get("schema_version"),
            "exported_at": snapshot.get("exported_at"),
        }

    async def handle_import_topology(call: ServiceCall) -> dict[str, object] | None:
        topology_json = call.data.get("topology_json")
        path = call.data.get("path")
        try:
            if topology_json:
                topology = json.loads(str(topology_json))
            elif path:
                topology = await coordinator.async_load_topology_from_file(str(path))
            else:
                _LOGGER.error("import_topology: missing path or topology_json")
                return
        except (OSError, json.JSONDecodeError, ValueError) as err:
            _LOGGER.error("import_topology: could not load topology snapshot: %s", err)
            return

        try:
            result = await coordinator.async_import_topology(
                topology,
                create_virtual_devices=bool(call.data.get("create_virtual_devices", True)),
                update_names=bool(call.data.get("update_names", True)),
                apply_group_ids=bool(call.data.get("apply_group_ids", True)),
                apply_links=bool(call.data.get("apply_links", True)),
                apply_week_profiles=bool(call.data.get("apply_week_profiles", True)),
            )
        except ValueError as err:
            _LOGGER.error("import_topology: import failed: %s", err)
            return
        _LOGGER.info(
            "Imported MAX! topology: devices=%s virtual=%s groups=%d week_profiles=%d links=%d skipped=%s",
            result["imported_devices"],
            result["created_virtual_addresses"],
            result["group_updates"],
            result["week_profile_updates"],
            result["link_updates"],
            result["skipped_devices"],
        )
        return {
            **result,
            "imported_device_details": _devices_payload(result["imported_devices"]),
            "created_virtual_devices": _devices_payload(result["created_virtual_addresses"]),
            "skipped_device_details": _devices_payload(result["skipped_devices"]),
        }

    async def handle_cleanup_superseded_devices(call: ServiceCall) -> dict[str, object]:
        dry_run = bool(call.data.get("dry_run", True))
        remove_registry_entries = bool(call.data.get("remove_registry_entries", True))
        remove_discovered_devices = bool(call.data.get("remove_discovered_devices", False))
        superseded_devices = coordinator.get_superseded_devices()
        superseded_addresses = [device.address for device in superseded_devices]
        discovered_devices = [
            device
            for device in coordinator.get_all_devices()
            if not device.paired and not device.is_virtual and not device.superseded_by
        ]
        discovered_addresses = [device.address for device in discovered_devices]
        known_addresses = {device.address for device in coordinator.get_all_devices()}
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        orphaned_addresses: list[str] = []
        for device_entry in list(device_registry.devices.values()):
            cul_max_addresses = [
                identifier[1]
                for identifier in device_entry.identifiers
                if len(identifier) == 2 and identifier[0] == DOMAIN
            ]
            for address in cul_max_addresses:
                normalized = str(address).upper()
                if normalized.startswith("CONTROLLER_"):
                    continue
                if normalized not in known_addresses:
                    orphaned_addresses.append(normalized)
        _LOGGER.info(
            "cleanup_superseded_devices: found %d superseded devices, %d discovered devices and %d orphaned registry devices",
            len(superseded_devices),
            len(discovered_devices),
            len(orphaned_addresses),
        )
        if superseded_devices:
            _LOGGER.info(
                "cleanup_superseded_devices: superseded=%s",
                [
                    f"{device.name} [{device.serial_number or 'n/a'}] {device.address} -> {device.superseded_by}"
                    for device in superseded_devices
                ],
            )
        if orphaned_addresses:
            _LOGGER.info(
                "cleanup_superseded_devices: orphaned registry addresses=%s",
                sorted(dict.fromkeys(orphaned_addresses)),
            )
        if discovered_devices:
            _LOGGER.info(
                "cleanup_superseded_devices: discovered=%s",
                [
                    f"{device.name} [{device.serial_number or 'n/a'}] {device.address}"
                    for device in discovered_devices
                ],
            )
        removable_addresses = sorted(
            dict.fromkeys(
                superseded_addresses
                + orphaned_addresses
                + (discovered_addresses if remove_discovered_devices else [])
            )
        )
        response: dict[str, object] = {
            "dry_run": dry_run,
            "remove_registry_entries": remove_registry_entries,
            "remove_discovered_devices": remove_discovered_devices,
            "superseded_addresses": sorted(dict.fromkeys(superseded_addresses)),
            "superseded_devices": [
                {
                    "address": device.address,
                    "name": device.name,
                    "serial_number": device.serial_number or "",
                    "superseded_by": device.superseded_by or "",
                }
                for device in superseded_devices
            ],
            "discovered_addresses": sorted(dict.fromkeys(discovered_addresses)),
            "discovered_devices": [
                {
                    "address": device.address,
                    "name": device.name,
                    "serial_number": device.serial_number or "",
                    "last_seen": device.last_seen,
                }
                for device in discovered_devices
            ],
            "orphaned_addresses": sorted(dict.fromkeys(orphaned_addresses)),
            "removable_addresses": removable_addresses,
            "removed_entity_ids": [],
            "removed_device_addresses": [],
            "removed_store_addresses": [],
        }
        if dry_run or not removable_addresses:
            return response

        if remove_registry_entries:
            to_remove = [
                entry.entity_id
                for entry in list(entity_registry.entities.values())
                if entry.platform == DOMAIN
                and any(
                    entry.unique_id.startswith(f"{DOMAIN}_{address}_")
                    or entry.unique_id == f"{DOMAIN}_{address}"
                    for address in removable_addresses
                )
            ]
            for entity_id in to_remove:
                entity_registry.async_remove(entity_id)
            response["removed_entity_ids"] = to_remove
            _LOGGER.info(
                "cleanup_superseded_devices: removed entity registry entries: %s",
                to_remove,
            )

            removed_device_addresses: list[str] = []
            for address in removable_addresses:
                device_entry = device_registry.async_get_device(identifiers={(DOMAIN, address)})
                if device_entry is not None:
                    device_registry.async_remove_device(device_entry.id)
                    removed_device_addresses.append(address)
            response["removed_device_addresses"] = removed_device_addresses
            _LOGGER.info(
                "cleanup_superseded_devices: removed device registry entries for %s",
                removable_addresses,
            )

        removed = await coordinator.async_remove_known_devices(superseded_addresses)
        response["removed_store_addresses"] = removed
        _LOGGER.info(
            "cleanup_superseded_devices: removed superseded devices from cul_max store: %s",
            removed,
        )
        return response

    _register(
        "start_pairing",
        handle_start_pairing,
        schema=vol.Schema({
            vol.Optional("duration", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "set_device_name",
        handle_set_device_name,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
            vol.Required("name"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register("wake_thermostats", handle_wake_thermostats, supports_response=SupportsResponse.OPTIONAL)
    _register(
        "sync_time",
        handle_sync_time,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("addresses"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("device_name"): cv.string,
            vol.Optional("device_names"): vol.All(cv.ensure_list, [cv.string]),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "set_week_profile",
        handle_set_week_profile,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
            vol.Required("profile"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "set_week_profile_days",
        handle_set_week_profile_days,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
            vol.Optional("monday"): cv.string,
            vol.Optional("tuesday"): cv.string,
            vol.Optional("wednesday"): cv.string,
            vol.Optional("thursday"): cv.string,
            vol.Optional("friday"): cv.string,
            vol.Optional("saturday"): cv.string,
            vol.Optional("sunday"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "set_group_id",
        handle_set_group_id,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
            vol.Required("group_id"): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "set_temperature_config",
        handle_set_temperature_config,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
            vol.Optional("comfort_temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
            vol.Optional("eco_temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
            vol.Optional("window_open_temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
            vol.Optional("window_open_duration"): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
            vol.Optional("measurement_offset"): vol.All(vol.Coerce(float), vol.Range(min=-3.5, max=3.5)),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "set_desired_temperature",
        handle_set_desired_temperature,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
            vol.Optional("temperature"): vol.All(vol.Coerce(float), vol.Range(min=4.5, max=30.5)),
            vol.Optional("mode"): vol.In(["auto", "manual", "boost"]),
            vol.Optional("keep_auto", default=False): cv.boolean,
            vol.Optional("until"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "remove_group_id",
        handle_remove_group_id,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "add_link_partner",
        handle_add_link_partner,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
            vol.Optional("partner_address"): cv.string,
            vol.Optional("partner_entity_id"): cv.entity_id,
            vol.Optional("partner_name"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "remove_link_partner",
        handle_remove_link_partner,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
            vol.Optional("partner_address"): cv.string,
            vol.Optional("partner_entity_id"): cv.entity_id,
            vol.Optional("partner_name"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "associate_devices",
        handle_associate_devices,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("addresses"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("device_name"): cv.string,
            vol.Optional("device_names"): vol.All(cv.ensure_list, [cv.string]),
            vol.Required("group_id"): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
            vol.Optional("bidirectional", default=True): cv.boolean,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "deassociate_devices",
        handle_deassociate_devices,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("addresses"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("device_name"): cv.string,
            vol.Optional("device_names"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("clear_group_id", default=False): cv.boolean,
            vol.Optional("bidirectional", default=True): cv.boolean,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "create_virtual_shutter_contact",
        handle_create_virtual_shutter_contact,
        schema=vol.Schema({
            vol.Required("address"): cv.string,
            vol.Required("name"): cv.string,
            vol.Optional("group_id", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "delete_virtual_device",
        handle_delete_virtual_device,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "send_virtual_shutter_contact_state",
        handle_send_virtual_shutter_contact_state,
        schema=vol.Schema({
            vol.Optional("address"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("device_name"): cv.string,
            vol.Required("is_open"): cv.boolean,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "create_room_association",
        handle_create_room_association,
        schema=vol.Schema({
            vol.Required("room_name"): cv.string,
            vol.Optional("group_id"): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
            vol.Optional("climate_address"): cv.string,
            vol.Optional("climate_addresses"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("climate_entity_id"): cv.entity_id,
            vol.Optional("climate_entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("climate_device_name"): cv.string,
            vol.Optional("climate_device_names"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("window_address"): cv.string,
            vol.Optional("window_addresses"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("window_entity_id"): cv.entity_id,
            vol.Optional("window_entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("window_device_name"): cv.string,
            vol.Optional("window_device_names"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("create_virtual_shutter_contact", default=False): cv.boolean,
            vol.Optional("virtual_shutter_contact_address"): cv.string,
            vol.Optional("virtual_shutter_contact_name"): cv.string,
            vol.Optional("bidirectional", default=True): cv.boolean,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "delete_room_association",
        handle_delete_room_association,
        schema=vol.Schema({
            vol.Required("room_name"): cv.string,
            vol.Optional("climate_address"): cv.string,
            vol.Optional("climate_addresses"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("climate_entity_id"): cv.entity_id,
            vol.Optional("climate_entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("climate_device_name"): cv.string,
            vol.Optional("climate_device_names"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("window_address"): cv.string,
            vol.Optional("window_addresses"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("window_entity_id"): cv.entity_id,
            vol.Optional("window_entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("window_device_name"): cv.string,
            vol.Optional("window_device_names"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("clear_group_id", default=True): cv.boolean,
            vol.Optional("delete_virtual_shutter_contacts", default=False): cv.boolean,
            vol.Optional("bidirectional", default=True): cv.boolean,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "rebuild_room_association",
        handle_rebuild_room_association,
        schema=vol.Schema({
            vol.Required("room_name"): cv.string,
            vol.Optional("group_id"): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
            vol.Optional("climate_address"): cv.string,
            vol.Optional("climate_addresses"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("climate_entity_id"): cv.entity_id,
            vol.Optional("climate_entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("climate_device_name"): cv.string,
            vol.Optional("climate_device_names"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("window_address"): cv.string,
            vol.Optional("window_addresses"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("window_entity_id"): cv.entity_id,
            vol.Optional("window_entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
            vol.Optional("window_device_name"): cv.string,
            vol.Optional("window_device_names"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("create_virtual_shutter_contact", default=False): cv.boolean,
            vol.Optional("virtual_shutter_contact_address"): cv.string,
            vol.Optional("virtual_shutter_contact_name"): cv.string,
            vol.Optional("clear_group_id", default=True): cv.boolean,
            vol.Optional("delete_virtual_shutter_contacts", default=False): cv.boolean,
            vol.Optional("bidirectional", default=True): cv.boolean,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "export_topology",
        handle_export_topology,
        schema=vol.Schema({
            vol.Optional("path"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "import_topology",
        handle_import_topology,
        schema=vol.Schema({
            vol.Optional("path"): cv.string,
            vol.Optional("topology_json"): cv.string,
            vol.Optional("create_virtual_devices", default=True): cv.boolean,
            vol.Optional("update_names", default=True): cv.boolean,
            vol.Optional("apply_group_ids", default=True): cv.boolean,
            vol.Optional("apply_links", default=True): cv.boolean,
            vol.Optional("apply_week_profiles", default=True): cv.boolean,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        "cleanup_superseded_devices",
        handle_cleanup_superseded_devices,
        schema=vol.Schema({
            vol.Optional("dry_run", default=True): cv.boolean,
            vol.Optional("remove_registry_entries", default=True): cv.boolean,
            vol.Optional("remove_discovered_devices", default=False): cv.boolean,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )


async def async_unload_entry(hass: HomeAssistant, entry: CulMaxConfigEntry) -> bool:
    """Unload the config entry and close serial connection."""
    coordinator: CulMaxCoordinator = entry.runtime_data
    await coordinator.async_shutdown()
    # Only remove services if no other entries are still loaded
    if not hass.config_entries.async_entries(DOMAIN):
        for service_name in SERVICE_NAMES:
            hass.services.async_remove(DOMAIN, service_name)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
