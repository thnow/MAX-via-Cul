"""Frontend resource registration for embedded Lovelace assets."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN, FRONTEND_MODULES, FRONTEND_URL_BASE

_LOGGER = logging.getLogger(__name__)
_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"


class CulMaxFrontendRegistration:
    """Register embedded Lovelace resources for the integration."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the frontend registrar."""
        self.hass = hass

    async def async_register(self) -> None:
        """Register static paths and Lovelace resources."""
        if self.hass.data.get(_FRONTEND_REGISTERED):
            return

        await self._async_register_static_path()
        lovelace = self.hass.data.get("lovelace")
        if lovelace is None:
            _LOGGER.debug("Lovelace is not available yet; retrying frontend resource registration")
            async_call_later(self.hass, 5, self._async_retry_register)
            return

        resources = getattr(lovelace, "resources", None)
        if resources is None or not all(
            hasattr(resources, attr)
            for attr in ("async_items", "async_create_item", "async_update_item")
        ):
            _LOGGER.debug(
                "Skipping automatic CUL MAX card resource registration because Lovelace resource management is unavailable"
            )
            self.hass.data[_FRONTEND_REGISTERED] = True
            return

        await self._async_wait_for_lovelace_resources()
        self.hass.data[_FRONTEND_REGISTERED] = True

    async def _async_retry_register(self, _now: Any) -> None:
        """Retry frontend registration after HA startup settles."""
        await self.async_register()

    async def _async_register_static_path(self) -> None:
        """Expose the embedded frontend files under a stable HTTP path."""
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(FRONTEND_URL_BASE, Path(__file__).parent, False)]
            )
        except RuntimeError:
            _LOGGER.debug("Static frontend path %s already registered", FRONTEND_URL_BASE)

    async def _async_wait_for_lovelace_resources(self) -> None:
        """Wait until Lovelace resources are loaded before mutating them."""

        async def _check_loaded(_now: Any) -> None:
            lovelace = self.hass.data.get("lovelace")
            if lovelace is None:
                return

            resources = getattr(lovelace, "resources", None)
            if resources is None:
                return

            if not hasattr(resources, "loaded") or resources.loaded:
                await self._async_sync_resources()
                return

            async_call_later(self.hass, 5, _check_loaded)

        await _check_loaded(None)

    async def _async_sync_resources(self) -> None:
        """Create or update Lovelace resources for the bundled cards."""
        lovelace = self.hass.data.get("lovelace")
        if lovelace is None:
            return

        resources = list(lovelace.resources.async_items())
        for module in FRONTEND_MODULES:
            managed_path = f"{FRONTEND_URL_BASE}/{module['filename']}"
            known_paths = {managed_path, *module.get("legacy_paths", [])}
            desired_url = f"{managed_path}?v={module['version']}"

            matches = [
                resource
                for resource in resources
                if self._get_path(resource["url"]) in known_paths
            ]

            if matches:
                primary = matches[0]
                if (
                    primary.get("res_type") != "module"
                    or primary.get("url") != desired_url
                ):
                    await lovelace.resources.async_update_item(
                        primary["id"],
                        {
                            "res_type": "module",
                            "url": desired_url,
                        },
                    )
                for duplicate in matches[1:]:
                    await lovelace.resources.async_delete_item(duplicate["id"])
                continue

            await lovelace.resources.async_create_item(
                {
                    "res_type": "module",
                    "url": desired_url,
                }
            )

    @staticmethod
    def _get_path(url: str) -> str:
        """Extract the path portion from a resource URL."""
        return url.split("?", 1)[0]


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the embedded CUL MAX frontend resources."""
    await CulMaxFrontendRegistration(hass).async_register()
