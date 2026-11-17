"""Virtual window contacts following a Home Assistant entity."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.cul_max.const import DEVICE_SHUTTER_CONTACT
from custom_components.cul_max.errors import CulMaxError

from .conftest import KIDS, wait_for

CONTACT = "A00001"
SOURCE = "binary_sensor.fenster_kinderzimmer"
MSG_SHUTTER_CONTACT_STATE = 0x30


def contact_states(fake_cul) -> list[bool]:
    """Open (True) / closed (False) as sent to the thermostat, in order."""
    return [
        int(p.raw[22:24], 16) & 0x02 == 0x02
        for p in fake_cul.on_air_to(KIDS)
        if p.msg_type == MSG_SHUTTER_CONTACT_STATE and p.src == CONTACT
    ]


@pytest.fixture
async def contact(hass, coordinator):
    hass.states.async_set(SOURCE, "off")
    await coordinator.async_create_virtual_shutter_contact(CONTACT, "Fenster Kinderzimmer", 1)
    device = coordinator.get_device(CONTACT)
    device.linked_partners = [KIDS]
    coordinator.get_device(KIDS).linked_partners = [CONTACT]
    return device


async def test_follows_source_and_sends_current_state(hass, coordinator, fake_cul, contact) -> None:
    status = await coordinator.async_set_virtual_contact_source(CONTACT, SOURCE)
    assert status["source_entity"] == SOURCE
    assert status["confirmed"] is True
    assert contact_states(fake_cul) == [False]

    hass.states.async_set(SOURCE, "on")
    await wait_for(lambda: contact_states(fake_cul) == [False, True])
    assert contact.last_state["is_open"] is True


async def test_quick_open_close_ends_closed(hass, coordinator, fake_cul, contact) -> None:
    """The Kinderzimmer bug: 'closed' arrived while 'open' was still on air."""
    await coordinator.async_set_virtual_contact_source(CONTACT, SOURCE)
    hass.states.async_set(SOURCE, "on")
    await hass.async_block_till_done(wait_background_tasks=False)
    hass.states.async_set(SOURCE, "off")
    await wait_for(lambda: not coordinator._source_sync_locks[CONTACT].locked() and contact_states(fake_cul)[-1] is False)
    await hass.async_block_till_done()
    assert contact_states(fake_cul)[-1] is False
    assert contact.last_state["is_open"] is False


async def test_unavailable_source_keeps_state(hass, coordinator, fake_cul, contact) -> None:
    await coordinator.async_set_virtual_contact_source(CONTACT, SOURCE)
    hass.states.async_set(SOURCE, "unavailable")
    await hass.async_block_till_done()
    assert contact_states(fake_cul) == [False]
    assert contact.last_state["is_open"] is False


async def test_heartbeat_catches_up_missed_change(hass, coordinator, fake_cul, contact) -> None:
    await coordinator.async_set_virtual_contact_source(CONTACT, SOURCE)
    # Change while the listener is gone (e.g. HA restart).
    coordinator._source_unsubs.pop(CONTACT)()
    hass.states.async_set(SOURCE, "on")
    await hass.async_block_till_done()
    assert contact_states(fake_cul) == [False]

    await coordinator._refresh_virtual_contacts()
    assert contact_states(fake_cul) == [False, True]


async def test_clear_source_stops_following(hass, coordinator, fake_cul, contact) -> None:
    await coordinator.async_set_virtual_contact_source(CONTACT, SOURCE)
    status = await coordinator.async_set_virtual_contact_source(CONTACT, None)
    assert status["source_entity"] is None
    assert contact.source_entity == ""
    hass.states.async_set(SOURCE, "on")
    await hass.async_block_till_done()
    assert contact_states(fake_cul) == [False]


async def test_rejects_invalid_source(hass, coordinator, contact) -> None:
    hass.states.async_set("sensor.temperatur", "20.1")
    with pytest.raises(CulMaxError) as err:
        await coordinator.async_set_virtual_contact_source(CONTACT, "sensor.temperatur")
    assert err.value.key == "source_not_contact"
    with pytest.raises(CulMaxError) as err:
        await coordinator.async_set_virtual_contact_source(CONTACT, "binary_sensor.gibt_es_nicht")
    assert err.value.key == "source_not_found"
    with pytest.raises(CulMaxError) as err:
        await coordinator.async_set_virtual_contact_source(KIDS, SOURCE)
    assert err.value.key == "not_virtual_contact"
    assert coordinator.get_device(CONTACT).device_type == DEVICE_SHUTTER_CONTACT


# --- send budget: heartbeats and retries are background traffic -----------


async def test_heartbeat_to_silent_thermostat_sends_few_packets(hass, coordinator, fake_cul, contact) -> None:
    """A thermostat that stopped answering must not drain the send budget."""
    fake_cul.devices[KIDS].silent = True
    contact.last_state = {"is_open": False}
    await coordinator.async_send_virtual_shutter_contact_state(CONTACT, False, reason="refresh")
    # one transmission plus at most two repeats, not 1 + 6
    assert len(contact_states(fake_cul)) == 3


async def test_real_change_overtakes_waiting_heartbeat(hass, coordinator, fake_cul, contact) -> None:
    """With little budget a heartbeat waits; a real change goes at once and replaces it."""
    contact.last_state = {"is_open": False}
    fake_cul.credit = 150
    coordinator._handle_credit_report(150)

    heartbeat = asyncio.create_task(
        coordinator.async_send_virtual_shutter_contact_state(CONTACT, False, reason="refresh")
    )
    await asyncio.sleep(0.1)
    assert contact_states(fake_cul) == []  # waits for budget, keeps the reserve

    confirmed = await asyncio.wait_for(
        coordinator.async_send_virtual_shutter_contact_state(CONTACT, True, reason="source change"),
        timeout=3,
    )
    assert confirmed is True
    assert contact_states(fake_cul) == [True]

    fake_cul.credit = 900
    await asyncio.wait_for(heartbeat, timeout=3)
    assert contact_states(fake_cul) == [True]  # the stale 'closed' never went out


async def test_thermostat_ack_clears_its_own_error(hass, coordinator, fake_cul, contact) -> None:
    """Büro 14.11.: one failed time sync left the thermostat 'error' for 31 h."""
    thermostat = coordinator.get_device(KIDS)
    thermostat.last_send_error = "No ACK for TimeInformation"
    thermostat.last_send_error_at = "2026-11-14T13:47:55+00:00"
    await coordinator.async_send_virtual_shutter_contact_state(CONTACT, True)
    assert thermostat.last_send_error == ""
    assert thermostat.last_ack_at
