"""Room sensors via virtual wall thermostats: one per room, relinking, fallback."""

from __future__ import annotations

import pytest

from custom_components.cul_max.const import (
    MODE_MANUAL,
    MSG_ADD_LINK_PARTNER,
    MSG_REMOVE_LINK_PARTNER,
    MSG_WALL_THERMOSTAT_CONTROL,
)

from .conftest import BATH, KIDS, KITCHEN, OWN
from .fake_cul import DEVICE_TYPE_WALL_THERMOSTAT

FIRST_WT = f"{OWN + 1:06X}"


@pytest.fixture
def sensors(hass):
    for entity_id, value in (
        ("sensor.kueche", "19.4"),
        ("sensor.bad", "22.1"),
        ("sensor.kinderzimmer", "20.3"),
    ):
        hass.states.async_set(entity_id, value, {"unit_of_measurement": "°C"})


@pytest.fixture
def targets(coordinator):
    """Thermostats in manual mode with known targets (sent along by the WT)."""
    for address, target in ((KITCHEN, 19.0), (BATH, 22.0), (KIDS, 20.0)):
        coordinator.get_device(address).last_state = {
            "mode": MODE_MANUAL,
            "desired_temperature": target,
        }


def wt_of(coordinator, address: str) -> str:
    return coordinator.get_device(address).wall_thermostat_address


def wall_thermostat_controls(fake_cul, address: str) -> list:
    return [p for p in fake_cul.on_air_to(address) if p.msg_type == MSG_WALL_THERMOSTAT_CONTROL]


async def test_each_room_gets_its_own_wall_thermostat(coordinator, fake_cul, sensors, targets) -> None:
    """The kitchen bug of 0.6.2: a shared WT made rooms take over targets."""
    await coordinator.async_set_external_temperature_sensor(KITCHEN, "sensor.kueche")
    await coordinator.async_set_external_temperature_sensor(BATH, "sensor.bad")

    assert wt_of(coordinator, KITCHEN) == FIRST_WT
    assert wt_of(coordinator, BATH) not in ("", FIRST_WT)
    assert fake_cul.devices[KITCHEN].wall_thermostats == [FIRST_WT]
    assert fake_cul.devices[BATH].wall_thermostats == [wt_of(coordinator, BATH)]

    # Each room's temperature goes out from its own WT, with its own target.
    kitchen = wall_thermostat_controls(fake_cul, KITCHEN)
    bath = wall_thermostat_controls(fake_cul, BATH)
    assert kitchen and bath
    assert {p.src for p in kitchen} == {FIRST_WT}
    assert {p.src for p in bath} == {wt_of(coordinator, BATH)}


async def test_same_sensor_shares_one_wall_thermostat(coordinator, fake_cul, sensors, targets) -> None:
    """Two radiators in one room with one thermometer: one WT for both."""
    await coordinator.async_set_external_temperature_sensor(KITCHEN, "sensor.kueche")
    await coordinator.async_set_external_temperature_sensor(KIDS, "sensor.kueche")

    assert wt_of(coordinator, KIDS) == wt_of(coordinator, KITCHEN) == FIRST_WT
    assert fake_cul.devices[KIDS].wall_thermostats == [FIRST_WT]


async def test_new_wall_thermostats_are_unique(coordinator, sensors, targets) -> None:
    for address, sensor in ((KITCHEN, "sensor.kueche"), (BATH, "sensor.bad"), (KIDS, "sensor.kinderzimmer")):
        await coordinator.async_set_external_temperature_sensor(address, sensor)

    addresses = {wt_of(coordinator, a) for a in (KITCHEN, BATH, KIDS)}
    assert len(addresses) == 3
    assert coordinator._wall_thermostat_addresses() == {int(a, 16) for a in addresses}
    assert coordinator.get_next_virtual_address() not in addresses


async def test_switching_sensor_relinks_remove_first(coordinator, fake_cul, sensors, targets) -> None:
    """A thermostat takes only one WT: the old link must go before the new one."""
    await coordinator.async_set_external_temperature_sensor(KITCHEN, "sensor.kueche")
    await coordinator.async_set_external_temperature_sensor(BATH, "sensor.bad")
    old = wt_of(coordinator, BATH)
    sent_before = len(fake_cul.on_air_to(BATH))

    await coordinator.async_set_external_temperature_sensor(BATH, "sensor.kueche")

    assert wt_of(coordinator, BATH) == FIRST_WT
    assert fake_cul.devices[BATH].wall_thermostats == [FIRST_WT]
    link_packets = [
        p.msg_type
        for p in fake_cul.on_air_to(BATH)[sent_before:]
        if p.msg_type in (MSG_ADD_LINK_PARTNER, MSG_REMOVE_LINK_PARTNER)
    ]
    assert link_packets == [MSG_REMOVE_LINK_PARTNER, MSG_ADD_LINK_PARTNER]
    assert old != FIRST_WT


async def test_rejected_relink_restores_old_link(coordinator, fake_cul, sensors, targets) -> None:
    """If the thermostat refuses the new WT (0x81) it keeps the old one."""
    await coordinator.async_set_external_temperature_sensor(KITCHEN, "sensor.kueche")
    await coordinator.async_set_external_temperature_sensor(BATH, "sensor.bad")
    old = wt_of(coordinator, BATH)
    thermostat = fake_cul.devices[BATH]
    # A WT link the integration does not know about (e.g. from an old Cube)
    # blocks any further wall thermostat.
    real_apply = thermostat._apply

    def refuse_new_link(packet):
        if packet.msg_type == MSG_ADD_LINK_PARTNER and packet.raw[22:28].upper() != old:
            return False
        return real_apply(packet)

    thermostat._apply = refuse_new_link

    with pytest.raises(ValueError) as rejected:
        await coordinator.async_set_external_temperature_sensor(BATH, "sensor.kueche")
    assert rejected.value.key == "wall_thermostat_link_rejected"

    assert wt_of(coordinator, BATH) == old
    assert coordinator.get_device(BATH).external_sensor == "sensor.bad"
    assert thermostat.wall_thermostats == [old]


async def test_removing_sensor_unlinks(coordinator, fake_cul, sensors, targets) -> None:
    await coordinator.async_set_external_temperature_sensor(BATH, "sensor.bad")

    await coordinator.async_set_external_temperature_sensor(BATH, None)

    assert fake_cul.devices[BATH].wall_thermostats == []
    assert wt_of(coordinator, BATH) == ""
    assert coordinator.get_device(BATH).external_sensor == ""


async def test_shared_legacy_setup_is_separated(coordinator, fake_cul, sensors, targets) -> None:
    """Setups from 0.6.2: all rooms on one WT. The biggest group keeps it."""
    legacy = {KITCHEN: "sensor.kueche", KIDS: "sensor.kueche", BATH: "sensor.bad"}
    for address, sensor in legacy.items():
        device = coordinator.get_device(address)
        device.external_sensor = sensor
        device.wall_thermostat_address = ""  # 0.6.2 stored none: own address + 1
        fake_cul.devices[address].links[FIRST_WT] = DEVICE_TYPE_WALL_THERMOSTAT

    await coordinator._separate_wall_thermostats()

    assert wt_of(coordinator, KITCHEN) in ("", FIRST_WT)
    assert wt_of(coordinator, KIDS) in ("", FIRST_WT)
    bath_wt = wt_of(coordinator, BATH)
    assert bath_wt not in ("", FIRST_WT)
    assert fake_cul.devices[KITCHEN].wall_thermostats == [FIRST_WT]
    assert fake_cul.devices[KIDS].wall_thermostats == [FIRST_WT]
    assert fake_cul.devices[BATH].wall_thermostats == [bath_wt]
    # the bathroom's temperature now comes from its own WT
    assert wall_thermostat_controls(fake_cul, BATH)[-1].src == bath_wt


async def test_separation_is_idempotent(coordinator, fake_cul, sensors, targets) -> None:
    """Already separated rooms cause no radio traffic on the next start."""
    await coordinator.async_set_external_temperature_sensor(KITCHEN, "sensor.kueche")
    await coordinator.async_set_external_temperature_sensor(BATH, "sensor.bad")
    sent = len(fake_cul.on_air)

    await coordinator._separate_wall_thermostats()

    assert len(fake_cul.on_air) == sent


async def test_unreachable_thermostat_keeps_shared_link(coordinator, fake_cul, sensors, targets) -> None:
    """Separation fails for an unreachable radiator: nothing is lost, retried next start."""
    for address, sensor in ((KITCHEN, "sensor.kueche"), (BATH, "sensor.bad")):
        device = coordinator.get_device(address)
        device.external_sensor = sensor
        fake_cul.devices[address].links[FIRST_WT] = DEVICE_TYPE_WALL_THERMOSTAT
    fake_cul.devices[BATH].silent = True

    await coordinator._separate_wall_thermostats()

    assert wt_of(coordinator, BATH) in ("", FIRST_WT)
    assert fake_cul.devices[BATH].wall_thermostats == [FIRST_WT]
