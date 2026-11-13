"""MAX! PushButton (Eco Taster) and contact status bits.

The telegrams are the ones captured from a real button in issue #5.
"""

from __future__ import annotations

import asyncio

from custom_components.cul_max.const import DEVICE_PUSH_BUTTON, EVENT_PUSH_BUTTON
from custom_components.cul_max.coordinator import KnownDevice
from custom_components.cul_max.protocol import (
    decode_push_button_state,
    decode_shutter_contact_state,
    parse_message,
)

from .conftest import wait_for

BUTTON = "05E2E2"
AUTO = "Z0C65025005E2E2123456009001"
ECO = "Z0C66025005E2E2123456009000"


def test_decode_auto_and_eco() -> None:
    auto = decode_push_button_state(parse_message(AUTO))
    eco = decode_push_button_state(parse_message(ECO))
    assert auto.button == "auto" and auto.address == BUTTON
    assert eco.button == "eco"
    # status byte 0x90: bit 7 set = battery low (0x10 is the normal value)
    assert auto.battery_low and not auto.rf_error


def test_decode_ignores_other_types_and_short_payload() -> None:
    assert decode_push_button_state(parse_message("Z0B2406300F14171234560010")) is None
    assert decode_push_button_state(parse_message("Z0B65025005E2E212345600")) is None


def test_contact_battery_and_rf_error_come_from_payload() -> None:
    """Header flags (0x06) carry no battery bit; the payload byte does."""
    closed = decode_shutter_contact_state(parse_message("Z0B2406300F14171234560010"))
    assert not closed.is_open and not closed.battery_low and not closed.rf_error
    opened = decode_shutter_contact_state(parse_message("Z0B2406300F14171234560012"))
    assert opened.is_open
    weak = decode_shutter_contact_state(parse_message("Z0B2406300F14171234560090"))
    assert weak.battery_low and not weak.is_open
    lost = decode_shutter_contact_state(parse_message("Z0B2406300F14171234560052"))
    assert lost.rf_error and lost.is_open


async def test_press_fires_one_event_and_updates_battery(hass, coordinator, fake_cul) -> None:
    coordinator._devices[BUTTON] = KnownDevice(
        address=BUTTON, device_type=DEVICE_PUSH_BUTTON, name="Eco-Taster Flur", paired=True
    )
    events = []
    hass.bus.async_listen(EVENT_PUSH_BUTTON, lambda e: events.append(e.data))
    dispatched = []
    coordinator.add_listener(BUTTON, lambda msg, decoded: dispatched.append(decoded))

    fake_cul.send_line(AUTO)
    await wait_for(lambda: len(events) == 1)

    assert events[0] == {
        "address": BUTTON,
        "name": "Eco-Taster Flur",
        "button": "auto",
        "battery_low": True,
    }
    state = coordinator.get_device(BUTTON).last_state
    assert state["battery_low"] is True and state["last_button"] == "auto"
    # entities (event, battery) get the decoded press via the listener
    # (compared by name: test_protocol.py loads protocol.py a second time)
    await wait_for(lambda: any(type(d).__name__ == "PushButtonState" for d in dispatched))


async def test_repeated_telegram_is_one_press(hass, coordinator, fake_cul) -> None:
    """Lost ACK or several link partners: same counter, still one press."""
    coordinator._devices[BUTTON] = KnownDevice(
        address=BUTTON, device_type=DEVICE_PUSH_BUTTON, name="Taster", paired=True
    )
    events = []
    hass.bus.async_listen(EVENT_PUSH_BUTTON, lambda e: events.append(e.data["button"]))

    fake_cul.send_line(AUTO)
    fake_cul.send_line(AUTO)  # repeat, same counter 0x65
    fake_cul.send_line(AUTO.replace("123456", "0A0001"))  # copy to a link partner
    await wait_for(lambda: len(events) >= 1)
    await asyncio.sleep(0.1)
    assert events == ["auto"]

    fake_cul.send_line(ECO)  # next press, counter 0x66
    fake_cul.send_line(AUTO)  # pressing Auto again later: counter differs from last
    await wait_for(lambda: len(events) == 3)
    assert events == ["auto", "eco", "auto"]
