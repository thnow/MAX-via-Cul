"""Summer mode: park all thermostats (off or valve open) and restore them."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.cul_max.const import (
    MODE_AUTO,
    MODE_MANUAL,
    MSG_SET_TEMPERATURE,
    MSG_WALL_THERMOSTAT_CONTROL,
)

from .conftest import BATH, KIDS, KITCHEN, THERMOSTATS, wait_for


def set_temperatures(fake_cul, address: str) -> list[tuple[int, float]]:
    """(mode, temperature) of every SetTemperature sent to a thermostat."""
    out = []
    for packet in fake_cul.on_air_to(address):
        if packet.msg_type == MSG_SET_TEMPERATURE:
            value = int(packet.raw[22:24], 16)
            out.append((value >> 6, (value & 0x3F) / 2))
    return out


@pytest.fixture
def heating_season(coordinator):
    """Kitchen and bath on their program, kids' room manual at 19 °C."""
    coordinator.get_device(KITCHEN).last_state = {"mode": MODE_AUTO, "desired_temperature": 21.0}
    coordinator.get_device(BATH).last_state = {"mode": MODE_AUTO, "desired_temperature": 22.0}
    coordinator.get_device(KIDS).last_state = {"mode": MODE_MANUAL, "desired_temperature": 19.0}


async def wait_summer(coordinator, status: str) -> None:
    await wait_for(
        lambda: all(
            r.get("status") == status for r in coordinator._summer["devices"].values()
        ),
        timeout=5,
    )


async def test_summer_off_closes_all_valves(coordinator, fake_cul, heating_season) -> None:
    status = await coordinator.async_start_summer(valve="closed")
    assert status["active"] and status["temperature"] == 4.5
    await wait_summer(coordinator, "confirmed")

    for address in THERMOSTATS:
        assert set_temperatures(fake_cul, address) == [(MODE_MANUAL, 4.5)]
    records = coordinator._summer["devices"]
    assert records[KIDS]["prev_mode"] == MODE_MANUAL and records[KIDS]["prev_temperature"] == 19.0
    assert records[KITCHEN]["prev_mode"] == MODE_AUTO


async def test_summer_open_valves(coordinator, fake_cul, heating_season) -> None:
    await coordinator.async_start_summer(valve="open")
    await wait_summer(coordinator, "confirmed")
    assert set_temperatures(fake_cul, KITCHEN) == [(MODE_MANUAL, 30.5)]


async def test_changing_valve_while_active_resends(coordinator, fake_cul, heating_season) -> None:
    await coordinator.async_start_summer(valve="closed")
    await wait_summer(coordinator, "confirmed")

    await coordinator.async_set_summer_valve("open")
    await wait_for(lambda: set_temperatures(fake_cul, KITCHEN)[-1] == (MODE_MANUAL, 30.5), timeout=5)
    # the state from before the summer is still the one that gets restored
    assert coordinator._summer["devices"][KIDS]["prev_temperature"] == 19.0


async def test_end_restores_program_and_manual(coordinator, fake_cul, heating_season) -> None:
    await coordinator.async_start_summer(valve="closed")
    await wait_summer(coordinator, "confirmed")
    for address in THERMOSTATS:  # what the ACKs would report
        coordinator.get_device(address).last_state.update(mode=MODE_MANUAL, desired_temperature=4.5)

    await coordinator.async_end_summer()
    await wait_summer(coordinator, "restored")

    assert set_temperatures(fake_cul, KITCHEN)[-1] == (MODE_AUTO, 0.0)
    assert set_temperatures(fake_cul, BATH)[-1] == (MODE_AUTO, 0.0)
    assert set_temperatures(fake_cul, KIDS)[-1] == (MODE_MANUAL, 19.0)


async def test_end_keeps_thermostat_changed_by_hand(coordinator, fake_cul, heating_season) -> None:
    """Someone heated the bathroom on a cold summer day: leave it alone."""
    await coordinator.async_start_summer(valve="closed")
    await wait_summer(coordinator, "confirmed")
    coordinator.get_device(KITCHEN).last_state.update(mode=MODE_MANUAL, desired_temperature=4.5)
    coordinator.get_device(BATH).last_state.update(mode=MODE_MANUAL, desired_temperature=23.0)
    sent_before = len(set_temperatures(fake_cul, BATH))

    await coordinator.async_end_summer()
    await wait_for(lambda: coordinator._summer["devices"][BATH]["status"] == "restored", timeout=5)

    assert len(set_temperatures(fake_cul, BATH)) == sent_before
    await wait_for(lambda: set_temperatures(fake_cul, KITCHEN)[-1] == (MODE_AUTO, 0.0), timeout=5)


async def test_vacation_and_summer_exclude_each_other(coordinator, fake_cul, heating_season) -> None:
    await coordinator.async_start_summer()
    with pytest.raises(ValueError, match="Sommermodus"):
        await coordinator.async_start_vacation(end=dt_util.now() + timedelta(days=3))
    await coordinator.async_end_summer()
    await wait_summer(coordinator, "restored")

    await coordinator.async_start_vacation(end=dt_util.now() + timedelta(days=3))
    with pytest.raises(ValueError, match="Urlaubsmodus"):
        await coordinator.async_start_summer()
    await coordinator.async_end_vacation()


async def test_no_room_sensor_traffic_in_summer(hass, coordinator, fake_cul, heating_season) -> None:
    hass.states.async_set("sensor.kueche", "19.5", {"unit_of_measurement": "°C"})
    await coordinator.async_set_external_temperature_sensor(KITCHEN, "sensor.kueche")
    await coordinator.async_start_summer()
    await wait_summer(coordinator, "confirmed")
    before = len(fake_cul.on_air)

    coordinator._ext_last.pop(KITCHEN, None)
    await coordinator._external_temperature_tick(KITCHEN, reason="test")

    assert not [p for p in fake_cul.on_air[before:] if p.msg_type == MSG_WALL_THERMOSTAT_CONTROL]

    # summer over: the paused room value goes out right away
    coordinator._ext_last[KITCHEN] = {"at": hass.loop.time(), "measured": 19.5, "desired": 21.0, "confirmed": True}
    coordinator.get_device(KITCHEN).last_state.update(mode=MODE_MANUAL, desired_temperature=4.5)
    await coordinator.async_end_summer()
    await wait_for(
        lambda: any(
            p.msg_type == MSG_WALL_THERMOSTAT_CONTROL for p in fake_cul.on_air_to(KITCHEN)[-3:]
        ),
        timeout=5,
    )


async def test_summer_survives_restart(hass, coordinator, fake_cul, heating_season) -> None:
    """Persisted with the device store; unconfirmed thermostats are resent."""
    fake_cul.devices[BATH].silent = True
    await coordinator.async_start_summer()
    await wait_for(lambda: coordinator._summer["devices"][BATH]["status"] == "failed", timeout=5)
    await coordinator.async_shutdown()

    from custom_components.cul_max.coordinator import CulMaxCoordinator

    from .conftest import OWN

    fake_cul.devices[BATH].silent = False
    restarted = CulMaxCoordinator(hass, "fake-cul", 2323, own_address=OWN)
    await restarted._load_devices()
    assert restarted.get_summer_status()["active"]
    restarted._command_worker_task = hass.loop.create_task(restarted._command_worker())
    try:
        assert await restarted._connect()
        restarted._resume_summer()
        await wait_for(lambda: restarted._summer["devices"][BATH]["status"] == "confirmed", timeout=5)
    finally:
        await restarted.async_shutdown()


async def test_week_card_knows_which_thermostats_are_parked(coordinator, fake_cul, heating_season) -> None:
    """Drives the 'Sommermodus' notice in the week profile card."""
    assert coordinator.summer_valve_for(KITCHEN) is None
    await coordinator.async_start_summer(valve="open")
    await wait_summer(coordinator, "confirmed")
    for address in THERMOSTATS:
        coordinator.get_device(address).last_state.update(mode=MODE_MANUAL, desired_temperature=30.5)
    assert coordinator.summer_valve_for(KITCHEN) == "open"

    # heated by hand on a cold summer day: show its real state instead
    coordinator.get_device(BATH).last_state.update(desired_temperature=22.0)
    assert coordinator.summer_valve_for(BATH) is None

    await coordinator.async_end_summer()
    assert coordinator.summer_valve_for(KITCHEN) is None
    await wait_summer(coordinator, "restored")
