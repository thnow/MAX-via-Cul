"""Frontend resource registration for embedded Lovelace assets."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN, FRONTEND_MODULES, FRONTEND_URL_BASE

_LOGGER = logging.getLogger(__name__)
_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"
_FRONTEND_RETRY_HANDLE = f"{DOMAIN}_frontend_retry_handle"
_FRONTEND_LOVELACE_UNSUB = f"{DOMAIN}_frontend_lovelace_unsub"


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

        if await self._async_sync_resources():
            self.hass.data[_FRONTEND_REGISTERED] = True
            return

        self._schedule_retry()

    async def _async_retry_register(self, _now: Any) -> None:
        """Retry frontend registration after HA startup settles."""
        self.hass.data.pop(_FRONTEND_RETRY_HANDLE, None)
        await self.async_register()

    def _schedule_retry(self) -> None:
        """Retry once Lovelace is ready without marking registration complete early."""
        if not self.hass.data.get(_FRONTEND_RETRY_HANDLE):
            self.hass.data[_FRONTEND_RETRY_HANDLE] = async_call_later(
                self.hass, 5, self._async_retry_register
            )

        if not self.hass.data.get(_FRONTEND_LOVELACE_UNSUB):
            self.hass.data[_FRONTEND_LOVELACE_UNSUB] = self.hass.bus.async_listen(
                EVENT_COMPONENT_LOADED, self._async_lovelace_loaded
            )

    async def _async_lovelace_loaded(self, event: Event) -> None:
        """Retry immediately when the Lovelace component is loaded."""
        if event.data.get("component") != "lovelace":
            return

        await self.async_register()

    async def _async_register_static_path(self) -> None:
        """Expose the embedded frontend files under a stable HTTP path."""
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(FRONTEND_URL_BASE, str(Path(__file__).parent), True)]
            )
        except RuntimeError:
            _LOGGER.debug("Static frontend path %s already registered", FRONTEND_URL_BASE)
        except ValueError:
            _LOGGER.debug("Static frontend path %s already registered", FRONTEND_URL_BASE)

    async def _async_sync_resources(self) -> bool:
        """Create or update Lovelace resources for the bundled cards."""
        lovelace = self.hass.data.get("lovelace")
        if lovelace is None:
            _LOGGER.debug("Lovelace is not available yet; retrying frontend resource registration")
            return False

        resources = getattr(lovelace, "resources", None)
        if resources is None:
            return self._add_extra_js_modules()

        required_methods = ("async_items", "async_create_item", "async_update_item")
        if not all(hasattr(resources, attr) for attr in required_methods):
            return self._add_extra_js_modules()

        if hasattr(resources, "async_get_info"):
            await resources.async_get_info()
        elif hasattr(resources, "loaded") and not resources.loaded:
            return False

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
                    self._get_resource_type(primary) != "module"
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

        self._cancel_retry()
        return True

    def _add_extra_js_modules(self) -> bool:
        """Fallback for Home Assistant versions without editable Lovelace resources."""
        try:
            from homeassistant.components.frontend import add_extra_js_url
        except ImportError:
            _LOGGER.debug("Frontend extra JS registration helper is unavailable")
            return False

        for module in FRONTEND_MODULES:
            managed_path = f"{FRONTEND_URL_BASE}/{module['filename']}"
            add_extra_js_url(self.hass, f"{managed_path}?v={module['version']}")
        self._cancel_retry()
        return True

    def _cancel_retry(self) -> None:
        """Cancel deferred registration callbacks after a successful sync."""
        retry_handle = self.hass.data.pop(_FRONTEND_RETRY_HANDLE, None)
        if retry_handle:
            retry_handle()

        unsubscribe = self.hass.data.pop(_FRONTEND_LOVELACE_UNSUB, None)
        if unsubscribe:
            unsubscribe()

    @staticmethod
    def _get_resource_type(resource: dict[str, Any]) -> str | None:
        """Return the resource type across Home Assistant storage/API variants."""
        return resource.get("res_type") or resource.get("type")

    @staticmethod
    def _get_path(url: str) -> str:
        """Extract the path portion from a resource URL."""
        return url.split("?", 1)[0]


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the embedded CUL MAX frontend resources."""
    await CulMaxFrontendRegistration(hass).async_register()
