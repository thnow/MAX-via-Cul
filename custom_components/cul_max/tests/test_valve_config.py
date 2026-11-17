"""ConfigValve (0x12): boost duration/valve position, decalcification, valve limits."""

from __future__ import annotations

import pytest

from custom_components.cul_max.const import DEVICE_WALL_THERMOSTAT, MSG_CONFIG_VALVE
from custom_components.cul_max.coordinator import KnownDevice
from custom_components.cul_max.errors import CulMaxError
from custom_components.cul_max.protocol import build_config_valve

from .conftest import KIDS

WALL = "0B0001"


def test_build_matches_fhem_layout() -> None:
    cmd = build_config_valve(
        0x01, 0x123456, 0x0E8703,
        boost_duration=5, boost_valve_position=80,
        decalcification_day=0, decalcification_hour=12,
        max_valve_setting=100, valve_offset=0,
    )
    # length, counter, flags, type 0x12, src, dst, group, payload
    assert cmd == "Zs0E0100121234560E870300300CFF00\r\n"


@pytest.mark.parametrize(
    ("minutes", "byte0"),
    [(0, 0x10), (15, 0x70), (30, 0xD0), (60, 0xF0)],
)
def test_boost_duration_index(minutes: int, byte0: int) -> None:
    cmd = build_config_valve(
        0, 1, 2,
        boost_duration=minutes, boost_valve_position=80,
        decalcification_day=0, decalcification_hour=12,
        max_valve_setting=100, valve_offset=0,
    )
    assert int(cmd[24:26], 16) == byte0


def test_build_rejects_impossible_duration() -> None:
    with pytest.raises(ValueError):
        build_config_valve(
            0, 1, 2,
            boost_duration=3, boost_valve_position=80,
            decalcification_day=0, decalcification_hour=12,
            max_valve_setting=100, valve_offset=0,
        )


def valve_payloads(fake_cul) -> list[str]:
    return [p.raw[22:] for p in fake_cul.on_air_to(KIDS) if p.msg_type == MSG_CONFIG_VALVE]


async def test_unknown_values_use_factory_settings_then_stick(coordinator, fake_cul) -> None:
    device = coordinator.get_device(KIDS)
    assert device.boost_duration is None  # the device cannot report it

    await coordinator.async_set_valve_config(KIDS, boost_duration=15)
    assert valve_payloads(fake_cul) == ["700CFF00"]  # 15 min, 80 %, Sat 12:00, 100 %, 0 %
    assert device.boost_duration == 15
    assert device.boost_valve_position == 80

    # Changing only the valve position keeps the 15 minutes.
    await coordinator.async_set_valve_config(KIDS, boost_valve_position=100, decalcification_day=2)
    assert valve_payloads(fake_cul)[-1] == "744CFF00"
    assert (device.boost_duration, device.decalcification_day) == (15, 2)


async def test_values_are_stored_only_after_ack(coordinator, fake_cul) -> None:
    fake_cul.devices[KIDS].silent = True
    with pytest.raises(Exception):  # noqa: B017 - no ACK
        await coordinator.async_set_valve_config(KIDS, boost_duration=30)
    assert coordinator.get_device(KIDS).boost_duration is None


async def test_rejects_wall_thermostat_and_bad_values(coordinator) -> None:
    coordinator._devices[WALL] = KnownDevice(
        address=WALL, device_type=DEVICE_WALL_THERMOSTAT, name="Wand", paired=True
    )
    with pytest.raises(CulMaxError) as err:
        await coordinator.async_set_valve_config(WALL, boost_duration=15)
    assert err.value.key == "no_valve_config"
    with pytest.raises(CulMaxError) as err:
        await coordinator.async_set_valve_config(KIDS, boost_duration=3)
    assert err.value.key == "boost_duration_invalid"
    with pytest.raises(CulMaxError) as err:
        await coordinator.async_set_valve_config(KIDS, boost_valve_position=82)
    assert err.value.key == "valve_percent_invalid"


async def test_draft_from_entities_goes_out_as_one_telegram(coordinator, fake_cul, monkeypatch) -> None:
    """Select and number changed in a row: one ConfigValve with both values."""
    import custom_components.cul_max.coordinator as coord_mod

    monkeypatch.setattr(coord_mod, "TEMPERATURE_CONFIG_APPLY_DELAY", 0.05)
    await coordinator.async_set_temperature_config_draft(KIDS, "boost_duration", 10)
    await coordinator.async_set_temperature_config_draft(KIDS, "boost_valve_position", 60)
    assert coordinator.get_temperature_config_value(KIDS, "boost_duration") == 10
    await coordinator._temp_apply_tasks[KIDS]
    assert valve_payloads(fake_cul) == ["4C0CFF00"]
