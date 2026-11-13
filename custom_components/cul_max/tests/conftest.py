"""Shared fixtures: a coordinator connected to a simulated CUL."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from custom_components.cul_max import coordinator as coord_mod
from custom_components.cul_max.const import DEVICE_HEATING_THERMOSTAT
from custom_components.cul_max.coordinator import CulMaxCoordinator, KnownDevice

from .fake_cul import FakeCul

OWN = 0x123456
KITCHEN = "0A0001"
BATH = "0A0002"
KIDS = "0A0003"
THERMOSTATS = {KITCHEN: "Küche", BATH: "Bad", KIDS: "Kinderzimmer"}


async def wait_for(predicate, timeout: float = 3.0) -> None:
    """Poll until predicate() is true (the coordinator works in tasks)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


@pytest.fixture
def fake_cul(monkeypatch) -> FakeCul:
    cul = FakeCul()
    for address in THERMOSTATS:
        cul.add_device(address)
    monkeypatch.setattr(coord_mod, "open_cul_connection", cul.open)
    # Shrink timeouts and pauses so every test runs in about a second.
    fast = {
        "set_temperature_timeout": 0.2,
        "pending_retry_base_delay": 0.05,
        "pending_retry_max_delay": 0.2,
    }
    monkeypatch.setattr(coord_mod, "SEND_PROFILE_STANDARD", replace(coord_mod.SEND_PROFILE_STANDARD, **fast))
    monkeypatch.setattr(coord_mod, "SEND_PROFILE_EXTENDED", replace(coord_mod.SEND_PROFILE_EXTENDED, **fast))
    for name, value in {
        "CUL_CREDIT_MAX_WAIT_SLICE": 0.05,
        "CUL_CREDIT_UNKNOWN_WAIT": 0.05,
        "CUL_CREDIT_QUERY_MIN_INTERVAL": 0.0,
        "CUL_CREDIT_QUERY_TIMEOUT": 0.2,
        "RECONNECT_DELAY_MIN": 0.05,
        "RECONNECT_WAIT_TIMEOUT": 2.0,
        "CONFIG_ACK_TIMEOUT": 0.2,
        "WEEK_PROFILE_ACK_TIMEOUT": 0.2,
        "WEEK_PROFILE_PART_DELAY": 0.0,
        "WEEK_PROFILE_DAY_DELAY": 0.0,
        "CONFIG_WAKE_SETTLE_DELAY": 0.0,
        "AUTO_MODE_TIME_SYNC_FOLLOWUP_DELAY": 0.0,
    }.items():
        monkeypatch.setattr(coord_mod, name, value)
    return cul


@pytest.fixture
async def coordinator(hass, fake_cul):
    """A connected coordinator with three paired thermostats.

    Only the connection and the command worker run; startup jobs (time sync,
    wall-thermostat separation, vacation) stay off so each test controls
    exactly which packets go on air.
    """
    coord = CulMaxCoordinator(hass, "fake-cul", 2323, own_address=OWN)
    coord._send_profile = coord_mod.SEND_PROFILE_STANDARD
    for address, name in THERMOSTATS.items():
        coord._devices[address] = KnownDevice(
            address=address, device_type=DEVICE_HEATING_THERMOSTAT, name=name, paired=True
        )
    coord._command_worker_task = hass.loop.create_task(coord._command_worker())
    assert await coord._connect()
    await wait_for(lambda: coord._cul_credit_known)
    yield coord
    await coord.async_shutdown()
    fake_cul.close()
    await hass.async_block_till_done()
