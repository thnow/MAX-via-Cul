"""Config flow for MAX! via CUL (CULFW device via TCP or USB/serial)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_BAUDRATE,
    CONF_CONNECTION,
    CONF_DEVICE,
    CONF_HOST,
    CONF_OWN_ADDRESS,
    CONF_PORT,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    DEFAULT_BAUDRATE,
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


async def _test_serial(device: str, baudrate: int) -> bool:
    """Open the serial port and check that a CULFW answers the version command."""
    try:
        from serialx import open_serial_connection  # noqa: PLC0415

        reader, writer = await asyncio.wait_for(
            open_serial_connection(url=device, baudrate=baudrate), timeout=5.0
        )
    except (OSError, asyncio.TimeoutError, ImportError) as err:
        _LOGGER.debug("Cannot open %s: %s", device, err)
        return False
    try:
        writer.write(b"V\n")
        await writer.drain()
        deadline = asyncio.get_running_loop().time() + 4.0
        while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
            line = await asyncio.wait_for(reader.readline(), timeout=remaining)
            if line.decode("ascii", "ignore").strip().startswith("V "):
                return True
        return False
    except (OSError, asyncio.TimeoutError):
        return False
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, RuntimeError):
            pass


async def _serial_port_options() -> list[SelectOptionDict]:
    """Serial ports found on the system (stable /dev/serial/by-id names first)."""
    try:
        from serialx import async_list_serial_ports  # noqa: PLC0415

        ports = await async_list_serial_ports()
    except Exception:  # noqa: BLE001 - listing is only a convenience
        return []
    options: list[SelectOptionDict] = []
    for port in ports:
        label = " – ".join(
            part for part in (port.device, port.manufacturer, port.product) if part
        )
        options.append(SelectOptionDict(value=port.device, label=label))
    return options


class CulMaxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of MAX! via CUL."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose how the CUL is connected."""
        return self.async_show_menu(step_id="user", menu_options=["network", "serial"])

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """CUL reachable via TCP (MAX! Cube with a-culfw, CUNO, ser2net …)."""
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
                    data={**user_input, CONF_CONNECTION: CONNECTION_TCP},
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
            step_id="network",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """CUL stick on USB (or another serial port)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device = user_input[CONF_DEVICE].strip()
            baudrate = int(user_input[CONF_BAUDRATE])

            await self.async_set_unique_id(f"serial:{device}")
            self._abort_if_unique_id_configured()

            if not await _test_serial(device, baudrate):
                errors[CONF_DEVICE] = "cannot_connect_serial"
            else:
                return self.async_create_entry(
                    title=f"MAX! CUL ({device.rsplit('/', 1)[-1]})",
                    data={
                        CONF_CONNECTION: CONNECTION_SERIAL,
                        CONF_DEVICE: device,
                        CONF_BAUDRATE: baudrate,
                        CONF_OWN_ADDRESS: user_input.get(
                            CONF_OWN_ADDRESS, f"{DEFAULT_OWN_ADDRESS:06X}"
                        ),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE): SelectSelector(
                    SelectSelectorConfig(
                        options=await _serial_port_options(),
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.Coerce(int),
                vol.Optional(
                    CONF_OWN_ADDRESS,
                    default=f"{DEFAULT_OWN_ADDRESS:06X}",
                ): str,
            }
        )

        return self.async_show_form(
            step_id="serial",
            data_schema=schema,
            errors=errors,
        )
