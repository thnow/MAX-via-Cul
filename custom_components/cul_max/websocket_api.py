"""Websocket API for the queue and pairing cards."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, PAIRING_DURATION

_REGISTERED = f"{DOMAIN}_websocket_registered"


def _coordinators(hass: HomeAssistant) -> dict[str, Any]:
    return {
        entry.entry_id: entry.runtime_data
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    }


def _coordinator(hass: HomeAssistant, connection, msg: dict) -> Any | None:
    coordinators = _coordinators(hass)
    entry_id = msg.get("entry_id")
    if entry_id is None and len(coordinators) == 1:
        return next(iter(coordinators.values()))
    coordinator = coordinators.get(entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unbekanntes MAX!-Gateway")
    return coordinator


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register the commands once per Home Assistant run."""
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True
    for command in (
        ws_queue_subscribe,
        ws_queue_cancel,
        ws_queue_clear_device,
        ws_pairing_subscribe,
        ws_pairing_start,
        ws_pairing_stop,
        ws_pairing_save,
    ):
        websocket_api.async_register_command(hass, command)


def _subscribe(hass, connection, msg, snapshot, add_listener, interval: float) -> None:
    """Send snapshots of all gateways now, on every change and periodically."""

    @callback
    def send(*_args) -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"], {"gateways": [snapshot(c) for c in _coordinators(hass).values()]}
            )
        )

    unsubs = [add_listener(c, send) for c in _coordinators(hass).values()]
    unsubs.append(async_track_time_interval(hass, send, timedelta(seconds=interval)))

    @callback
    def unsubscribe() -> None:
        for unsub in unsubs:
            unsub()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    send()


# ---------------------------------------------------------------- queue


@websocket_api.websocket_command({vol.Required("type"): "cul_max/queue/subscribe"})
@callback
def ws_queue_subscribe(hass: HomeAssistant, connection, msg: dict) -> None:
    def add_listener(coordinator, cb):
        remove_queue = coordinator.add_queue_listener(cb)
        remove_status = coordinator.add_cul_status_listener(cb)

        def remove() -> None:
            remove_queue()
            remove_status()

        return remove

    _subscribe(hass, connection, msg, lambda c: c.get_queue_snapshot(), add_listener, 5.0)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "cul_max/queue/cancel",
        vol.Optional("entry_id"): str,
        vol.Required("command_id"): int,
    }
)
@websocket_api.async_response
async def ws_queue_cancel(hass: HomeAssistant, connection, msg: dict) -> None:
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    removed = await coordinator.async_cancel_queued_command(msg["command_id"])
    connection.send_result(msg["id"], {"removed": removed})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "cul_max/queue/clear_device",
        vol.Optional("entry_id"): str,
        vol.Required("address"): str,
    }
)
@websocket_api.async_response
async def ws_queue_clear_device(hass: HomeAssistant, connection, msg: dict) -> None:
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    removed = await coordinator.async_clear_device_queue(msg["address"])
    connection.send_result(msg["id"], {"removed": removed})


# -------------------------------------------------------------- pairing


@websocket_api.websocket_command({vol.Required("type"): "cul_max/pairing/subscribe"})
@callback
def ws_pairing_subscribe(hass: HomeAssistant, connection, msg: dict) -> None:
    _subscribe(
        hass,
        connection,
        msg,
        lambda c: c.get_pairing_session(),
        lambda c, cb: c.add_pairing_state_listener(cb),
        10.0,
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "cul_max/pairing/start",
        vol.Optional("entry_id"): str,
        vol.Optional("duration", default=PAIRING_DURATION): vol.All(int, vol.Range(min=10, max=600)),
    }
)
@websocket_api.async_response
async def ws_pairing_start(hass: HomeAssistant, connection, msg: dict) -> None:
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    await coordinator.async_start_pairing(msg["duration"])
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {vol.Required("type"): "cul_max/pairing/stop", vol.Optional("entry_id"): str}
)
@websocket_api.async_response
async def ws_pairing_stop(hass: HomeAssistant, connection, msg: dict) -> None:
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    await coordinator.async_stop_pairing()
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "cul_max/pairing/save",
        vol.Optional("entry_id"): str,
        vol.Required("address"): str,
        vol.Optional("name"): str,
        vol.Optional("area_id"): vol.Any(str, None),
        vol.Optional("link_room", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_pairing_save(hass: HomeAssistant, connection, msg: dict) -> None:
    """Name a freshly paired device, put it into an area, optionally link it."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    address = msg["address"].upper()
    registry = dr.async_get(hass)
    device_entry = coordinator.get_registry_device(registry, address)
    if device_entry is None:
        connection.send_error(msg["id"], "not_found", "Gerät ist (noch) nicht registriert")
        return
    changes: dict[str, Any] = {}
    if (name := (msg.get("name") or "").strip()):
        changes["name_by_user"] = name
    if "area_id" in msg:
        area_id = msg["area_id"] or None
        if area_id is not None and ar.async_get(hass).async_get_area(area_id) is None:
            connection.send_error(msg["id"], "not_found", "Unbekannter Bereich")
            return
        changes["area_id"] = area_id
    if changes:
        registry.async_update_device(device_entry.id, **changes)
    result: dict[str, Any] = {"device_id": device_entry.id}
    area_id = changes.get("area_id", device_entry.area_id)
    if msg["link_room"] and area_id:
        room = [
            identifier.upper()
            for device in dr.async_entries_for_area(registry, area_id)
            for domain, identifier in device.identifiers
            if domain == DOMAIN and identifier.upper() != address and len(identifier) == 6
        ]
        if not room:
            result["room_error"] = "Im gewählten Bereich gibt es keine weiteren MAX!-Geräte."
        else:
            # radio work: runs through the queue (visible in the queue card)
            coordinator._background(
                coordinator.async_add_device_to_room(address, room), f"link {address} into room"
            )
            result["room"] = "started"
    connection.send_result(msg["id"], result)
