"""Topology picture: texts follow the server language."""

from __future__ import annotations

from .conftest import KITCHEN


async def test_topology_texts_follow_server_language(hass, coordinator) -> None:
    coordinator.get_device(KITCHEN).last_state = {
        "mode": 0,
        "desired_temperature": 20.5,
        "measured_temperature": 19.5,
        "battery_low": True,
    }

    hass.config.language = "en"
    svg = coordinator.render_topology()
    assert "MAX! topology" in svg
    assert "Battery low" in svg
    assert "is 19.5°" in svg and "20.5°" in svg
    assert KITCHEN in svg

    hass.config.language = "de"
    svg = coordinator.render_topology()
    assert "MAX! Topologie" in svg
    assert "Batterie schwach" in svg
    assert "ist 19,5°" in svg and "20,5°" in svg
