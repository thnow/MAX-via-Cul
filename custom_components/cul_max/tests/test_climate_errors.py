"""Feedback of climate changes: confirmed on ACK, readable error without."""

from __future__ import annotations

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.cul_max.climate import CulMaxClimate

from .conftest import KITCHEN


async def test_silent_thermostat_gives_readable_error(hass, coordinator, fake_cul) -> None:
    fake_cul.devices[KITCHEN].silent = True
    entity = CulMaxClimate(coordinator, coordinator.get_device(KITCHEN))
    entity.hass = hass
    entity.entity_id = "climate.kitchen"
    entity.async_write_ha_state = lambda: None

    with pytest.raises(HomeAssistantError) as failed:
        await entity.async_set_temperature(temperature=22.0)

    assert failed.value.translation_key == "command_no_answer"
    assert failed.value.translation_placeholders == {"device": coordinator.get_device(KITCHEN).name}
    # the entity shows the last confirmed state again
    assert entity.extra_state_attributes["command_status"] == "failed"


async def test_confirmed_change_leaves_sending_state(hass, coordinator) -> None:
    """After the ACK the card must not keep showing 'sending …' (0.6.8 bug)."""
    entity = CulMaxClimate(coordinator, coordinator.get_device(KITCHEN))
    entity.hass = hass
    entity.entity_id = "climate.kitchen"
    entity.async_write_ha_state = lambda: None

    await entity.async_set_temperature(temperature=21.0)

    assert entity.extra_state_attributes["command_status"] == "confirmed"
