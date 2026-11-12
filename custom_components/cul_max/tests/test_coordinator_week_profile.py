"""Week profile uploads against a simulated CUL and thermostat."""

from __future__ import annotations

import asyncio

from homeassistant.util import dt as dt_util

from custom_components.cul_max.const import MSG_CONFIG_WEEK_PROFILE
from custom_components.cul_max.coordinator import CulMaxCoordinator
from custom_components.cul_max.protocol import (
    order_week_profile_days,
    split_week_profile_for_send,
)

from .conftest import KITCHEN, OWN, wait_for

DAYS = ("Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri")
WEEK = "\n".join(
    f"{day} 17,05:30,19,06:00,21,08:00,18,12:00,20,13:00,18,16:00,21,19:00,20,22:30,17"
    for day in DAYS
)
OTHER_WEEK = "\n".join(f"{day} 16,07:00,20,21:00,16" for day in DAYS)
MONDAY = 2


def expected_chunks(profile_hex: str, days) -> dict[tuple[int, int], str]:
    return {
        (day, part): chunk.upper()
        for day in days
        for part, chunk in split_week_profile_for_send(profile_hex, day)
    }


def week_packets(fake_cul, address: str = KITCHEN) -> list:
    return [p for p in fake_cul.on_air_to(address) if p.msg_type == MSG_CONFIG_WEEK_PROFILE]


def plenty_of_credit(coordinator, fake_cul) -> None:
    """A full week is ~14 packets: more than one standard 1 % budget."""
    fake_cul.credit = 5000
    coordinator._handle_credit_report(5000)


async def test_full_week_reaches_the_thermostat(coordinator, fake_cul) -> None:
    plenty_of_credit(coordinator, fake_cul)

    await coordinator.async_set_week_profile(KITCHEN, WEEK)

    device = coordinator.get_device(KITCHEN)
    assert fake_cul.devices[KITCHEN].week_profile == expected_chunks(device.week_profile, range(7))
    assert not coordinator._pending_climate_config.get(KITCHEN)
    assert device.pending_config == []
    # today first, so the new program applies right away
    sent_days = []
    for packet in week_packets(fake_cul):
        day = int(packet.raw[22:24], 16) & 0x07
        if day not in sent_days:
            sent_days.append(day)
    assert sent_days == order_week_profile_days(range(7), dt_util.now())


async def test_lost_packets_are_repeated_without_gaps(coordinator, fake_cul) -> None:
    """Packets 3 and 4 get lost on air: repeated, nothing skipped."""
    plenty_of_credit(coordinator, fake_cul)
    fake_cul.devices[KITCHEN].drop = {3, 4}

    await coordinator.async_set_week_profile(KITCHEN, WEEK)

    device = coordinator.get_device(KITCHEN)
    expected = expected_chunks(device.week_profile, range(7))
    assert fake_cul.devices[KITCHEN].week_profile == expected
    assert len(week_packets(fake_cul)) == len(expected) + 2
    assert not coordinator._pending_climate_config.get(KITCHEN)


async def test_unreachable_thermostat_gets_the_rest_later(coordinator, fake_cul) -> None:
    """The thermostat stops answering mid-upload; the rest follows later."""
    plenty_of_credit(coordinator, fake_cul)
    thermostat = fake_cul.devices[KITCHEN]
    thermostat.lose_from = 4

    await coordinator.async_set_week_profile(KITCHEN, WEEK)

    device = coordinator.get_device(KITCHEN)
    expected = expected_chunks(device.week_profile, range(7))
    assert len(thermostat.week_profile) == 4
    assert len(coordinator._pending_climate_config[KITCHEN]) == len(expected) - 4
    assert device.pending_config  # shown as pending in the UI

    thermostat.lose_from = None  # back in range
    for _ in range(50):
        if not coordinator._pending_climate_config.get(KITCHEN):
            break
        await asyncio.sleep(0.1)  # retry backoff
        await coordinator._run_pending_queue_maintenance()
        await coordinator.hass.async_block_till_done()
        await wait_for(lambda: not coordinator._pending_climate_tasks.get(KITCHEN))
    assert not coordinator._pending_climate_config.get(KITCHEN)
    assert thermostat.week_profile == expected


async def test_single_day_change_sends_only_that_day(coordinator, fake_cul) -> None:
    plenty_of_credit(coordinator, fake_cul)
    await coordinator.async_set_week_profile(KITCHEN, WEEK)
    before = len(week_packets(fake_cul))

    await coordinator.async_set_week_profile(KITCHEN, "Mon 18,06:30,22,21:00,18")

    new = week_packets(fake_cul)[before:]
    assert new
    assert {int(p.raw[22:24], 16) & 0x07 for p in new} == {MONDAY}
    device = coordinator.get_device(KITCHEN)
    # The short Monday fits into the first packet; the thermostat ignores
    # whatever follows the 24:00 point, so its old second part may stay.
    received = fake_cul.devices[KITCHEN].week_profile
    expected = expected_chunks(device.week_profile, range(7))
    assert received[(MONDAY, 0)] == expected[(MONDAY, 0)]
    assert {k: v for k, v in received.items() if k[0] != MONDAY} == {
        k: v for k, v in expected.items() if k[0] != MONDAY
    }


async def test_newer_profile_replaces_pending_upload(coordinator, fake_cul) -> None:
    """Saving again while an upload is pending: only the new program arrives."""
    plenty_of_credit(coordinator, fake_cul)
    thermostat = fake_cul.devices[KITCHEN]
    thermostat.lose_from = 0  # out of range
    await coordinator.async_set_week_profile(KITCHEN, WEEK)
    assert coordinator._pending_climate_config.get(KITCHEN)

    thermostat.lose_from = None
    coordinator._pending_climate_config[KITCHEN][0].next_attempt_at = ""
    await coordinator.async_set_week_profile(KITCHEN, OTHER_WEEK)

    device = coordinator.get_device(KITCHEN)
    assert not coordinator._pending_climate_config.get(KITCHEN)
    assert thermostat.week_profile == expected_chunks(device.week_profile, range(7))


async def test_pending_upload_survives_restart(hass, coordinator, fake_cul) -> None:
    """HA restarts with an unfinished upload: the new start finishes it."""
    plenty_of_credit(coordinator, fake_cul)
    thermostat = fake_cul.devices[KITCHEN]
    thermostat.lose_from = 2
    await coordinator.async_set_week_profile(KITCHEN, WEEK)
    remaining = len(coordinator._pending_climate_config[KITCHEN])
    assert remaining > 0
    profile_hex = coordinator.get_device(KITCHEN).week_profile
    await coordinator.async_shutdown()

    thermostat.lose_from = None
    restarted = CulMaxCoordinator(hass, "fake-cul", 2323, own_address=OWN)
    await restarted._load_devices()
    assert len(restarted._pending_climate_config[KITCHEN]) == remaining
    for command in restarted._pending_climate_config[KITCHEN]:
        command.next_attempt_at = ""
    restarted._command_worker_task = hass.loop.create_task(restarted._command_worker())
    try:
        assert await restarted._connect()
        fake_cul.credit = 5000
        await wait_for(lambda: restarted._cul_credit_known)
        restarted._resume_pending_config_processing()
        await wait_for(lambda: not restarted._pending_climate_config.get(KITCHEN), timeout=5)
        assert thermostat.week_profile == expected_chunks(profile_hex, range(7))
    finally:
        await restarted.async_shutdown()
