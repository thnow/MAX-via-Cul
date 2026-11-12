"""Coordinator tests against a simulated CUL: queue, ACKs, retries, send budget."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.cul_max import coordinator as coord_mod
from custom_components.cul_max.const import MSG_SET_TEMPERATURE
from custom_components.cul_max.coordinator import (
    COMMAND_PRIORITY_LOW,
    CommandSupersededError,
    DeviceNackError,
)
from custom_components.cul_max.protocol import build_time_information

from .conftest import BATH, KITCHEN, OWN, wait_for
from .fake_cul import FakeCul, packet_cost


def set_temperatures(fake_cul: FakeCul, address: str) -> list:
    return [p for p in fake_cul.on_air_to(address) if p.msg_type == MSG_SET_TEMPERATURE]


async def test_connect_initialises_culfw(coordinator, fake_cul) -> None:
    """Moritz RX, auto-ACK for the central and the virtual wall thermostat."""
    assert fake_cul.control[0] == "Zr"
    assert f"Za{OWN:06X}" in fake_cul.control
    assert any(cmd.startswith("Zw") for cmd in fake_cul.control)
    assert coordinator.get_cul_credit_status()["credit_10ms"] == 900


async def test_set_temperature_acked(coordinator, fake_cul) -> None:
    await coordinator.async_set_temperature(KITCHEN, 21.5)

    sent = set_temperatures(fake_cul, KITCHEN)
    assert len(sent) == 1
    assert sent[0].src == f"{OWN:06X}"
    device = coordinator.get_device(KITCHEN)
    assert device.last_command_retries == 0
    assert device.last_ack_at
    assert not device.last_send_error


async def test_lost_packet_is_retried(coordinator, fake_cul) -> None:
    """The first SetTemperature gets lost on air; the retry gets the ACK."""
    fake_cul.devices[KITCHEN].ignore_next = 1

    await coordinator.async_set_temperature(KITCHEN, 19.0)

    sent = set_temperatures(fake_cul, KITCHEN)
    assert len(sent) == 2
    assert sent[0].counter == sent[1].counter  # same telegram repeated
    assert coordinator.get_device(KITCHEN).last_command_retries == 1


async def test_no_ack_gives_up_and_records_error(coordinator, fake_cul) -> None:
    fake_cul.devices[KITCHEN].silent = True
    retries = coord_mod.SEND_PROFILE_STANDARD.set_temperature_retries

    with pytest.raises(ConnectionError, match="No ACK"):
        await coordinator.async_set_temperature(KITCHEN, 19.0)

    assert len(set_temperatures(fake_cul, KITCHEN)) == retries + 1
    assert "No ACK" in coordinator.get_device(KITCHEN).last_send_error


async def test_nack_is_not_retried(coordinator, fake_cul) -> None:
    """A device that rejects the command will not accept a repetition either."""
    fake_cul.devices[KITCHEN].nack = True

    with pytest.raises(DeviceNackError):
        await coordinator.async_set_temperature(KITCHEN, 19.0)

    assert len(set_temperatures(fake_cul, KITCHEN)) == 1


async def test_lovf_resend_does_not_count_as_attempt(coordinator, fake_cul) -> None:
    """LOVF means the packet never went on air: resend, no retry used up."""
    fake_cul.lovf_next = 1

    await coordinator.async_set_temperature(KITCHEN, 22.0)

    assert len(set_temperatures(fake_cul, KITCHEN)) == 1
    assert coordinator.get_device(KITCHEN).last_command_retries == 0


async def test_waits_for_send_budget(coordinator, fake_cul) -> None:
    """With the budget used up nothing is sent until the CUL has credit again."""
    fake_cul.credit = 20
    coordinator._handle_credit_report(20)

    task = asyncio.create_task(coordinator.async_set_temperature(KITCHEN, 20.0))
    await asyncio.sleep(0.3)
    assert not set_temperatures(fake_cul, KITCHEN)
    assert not task.done()

    fake_cul.credit = 900  # the CUL regained credit
    await asyncio.wait_for(task, timeout=3)
    assert len(set_temperatures(fake_cul, KITCHEN)) == 1


async def test_interactive_command_overtakes_background_traffic(coordinator, fake_cul) -> None:
    """A background packet waiting for budget must not delay SetTemperature.

    With 150 credit a SetTemperature (no reserve) fits, a low-priority
    TimeInformation (which has to leave the interactive reserve) does not.
    """
    fake_cul.credit = 150
    coordinator._handle_credit_report(150)

    background = asyncio.create_task(
        coordinator._send_command(
            build_time_information(coordinator._next_counter(), OWN, int(BATH, 16)),
            expected_src=BATH,
            device_address=BATH,
            counter=coordinator._counter,
            description="background time sync",
            priority=COMMAND_PRIORITY_LOW,
        )
    )
    await asyncio.sleep(0.1)
    assert not fake_cul.on_air_to(BATH)

    await asyncio.wait_for(coordinator.async_set_temperature(KITCHEN, 21.0), timeout=3)
    assert len(set_temperatures(fake_cul, KITCHEN)) == 1
    assert not fake_cul.on_air_to(BATH)

    fake_cul.credit = 900
    await asyncio.wait_for(background, timeout=3)
    assert fake_cul.on_air[-1].dst == BATH


async def test_newer_set_temperature_supersedes_queued_one(coordinator, fake_cul) -> None:
    """Turning the knob quickly: only the last value is sent."""
    fake_cul.credit = 20
    coordinator._handle_credit_report(20)

    first = asyncio.create_task(coordinator.async_set_temperature(KITCHEN, 19.0))
    await asyncio.sleep(0.05)
    second = asyncio.create_task(coordinator.async_set_temperature(KITCHEN, 23.0))
    await asyncio.sleep(0.05)
    fake_cul.credit = 900

    with pytest.raises(CommandSupersededError):
        await asyncio.wait_for(first, timeout=3)
    await asyncio.wait_for(second, timeout=3)

    sent = set_temperatures(fake_cul, KITCHEN)
    assert len(sent) == 1
    # 23.0 °C manual: temperature * 2 in the low 6 bits, mode in the top 2
    assert int(sent[0].raw[22:24], 16) & 0x3F == 46


async def test_credit_estimate_books_each_send(coordinator, fake_cul) -> None:
    """The local estimate follows the CUL between two "X" queries."""
    before = coordinator.get_cul_credit_status()["credit_10ms"]
    await coordinator.async_set_temperature(KITCHEN, 21.0)
    cost = packet_cost("Zs" + set_temperatures(fake_cul, KITCHEN)[0].raw)
    after = coordinator.get_cul_credit_status()["credit_10ms"]
    assert before - after == pytest.approx(cost, abs=2)


async def test_reconnects_after_connection_loss(coordinator, fake_cul) -> None:
    """Cube reboot: the coordinator reconnects and later commands go through."""
    fake_cul.disconnect()
    await wait_for(lambda: fake_cul.connections == 2)
    await wait_for(lambda: coordinator._writer is not None and not coordinator._reconnecting)

    await asyncio.wait_for(coordinator.async_set_temperature(KITCHEN, 20.5), timeout=3)
    assert len(set_temperatures(fake_cul, KITCHEN)) == 1
    # the init sequence ran again on the new connection
    assert fake_cul.control.count("Zr") == 2


async def test_command_waits_for_reconnect(coordinator, fake_cul) -> None:
    """A command issued while the CUL is gone is sent once it is back."""
    fake_cul.refuse_connections = True
    fake_cul.disconnect()
    await wait_for(lambda: coordinator._writer is None)

    task = asyncio.create_task(coordinator.async_set_temperature(KITCHEN, 18.5))
    await asyncio.sleep(0.2)
    assert not task.done()

    fake_cul.refuse_connections = False
    await asyncio.wait_for(task, timeout=4)
    assert len(set_temperatures(fake_cul, KITCHEN)) == 1
