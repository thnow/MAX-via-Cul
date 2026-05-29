"""Config flow for MAX! via CUL (TCP connection to CULFW device)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HOST,
    CONF_OWN_ADDRESS,
    CONF_PORT,
    DEFAULT_OWN_ADDRESS,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _test_connection(host: str, port: int) -> bool:
    """Try to open a TCP connection to verify the CULFW device is reachable."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=5.0,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


class CulMaxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of MAX! via CUL."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show setup form and validate host/port."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            # Prevent duplicate entries for the same host:port
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            if not await _test_connection(host, port):
                errors[CONF_HOST] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"MAX! CUL ({host}:{port})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
                vol.Optional(
                    CONF_OWN_ADDRESS,
                    default=f"{DEFAULT_OWN_ADDRESS:06X}",
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
