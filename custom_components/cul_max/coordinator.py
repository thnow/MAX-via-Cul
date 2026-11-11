"""
Coordinator for MAX! via CUL (TCP connection to CULFW-flashed MAX! Cube or CUNO).

Connects via TCP (default port 2323), dispatches incoming MAX! messages to
registered listeners, and provides a command interface for device control.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.const import UnitOfTemperature
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import (
    CULFW_CMD_MORITZ_RX,
    CULFW_CMD_VERSION,
    DEFAULT_OWN_ADDRESS,
    DEFAULT_PORT,
    DOMAIN,
    DEVICE_HEATING_THERMOSTAT,
    DEVICE_HEATING_THERMOSTAT_PLUS,
    DEVICE_SHUTTER_CONTACT,
    DEVICE_TYPE_NAMES,
    DEVICE_WALL_THERMOSTAT,
    MODE_NAMES,
    MODE_AUTO,
    MODE_MANUAL,
    MODE_VACATION,
    MODE_BOOST,
    MSG_PAIR_PING,
    MSG_ACK,
    MSG_SET_TEMPERATURE,
    MSG_TIME_INFORMATION,
    PAIRING_DURATION,
    STORAGE_KEY,
    STORAGE_SCHEMA_VERSION,
    STORAGE_VERSION,
    CLIMATE_DEVICE_TYPES,
    STALE_TIMEOUT_CLIMATE,
    STALE_TIMEOUT_SHUTTER_CONTACT,
    TEMP_MAX,
    TEMP_MIN,
    )
from .topology import (
    KIND_CONTACT,
    KIND_THERMOSTAT,
    KIND_WALL,
    TopologyEdge,
    TopologyNode,
    render_topology_svg,
)
from .protocol import (
    MaxMessage,
    ThermostatState,
    ShutterContactState,
    build_add_link_partner,
    build_config_temperatures,
    build_config_week_profile,
    build_pair_pong,
    build_time_information,
    build_remove_group_id,
    build_remove_link_partner,
    build_set_group_id,
    build_set_temperature,
    build_shutter_contact_state,
    build_wake_up,
    build_wall_thermostat_control,
    decode_ack_state,
    decode_set_temperature,
    decode_wall_thermostat_control,
    is_ack_nack,
    parse_credit_report,
    thermostat_state_from_dict,
    WALL_CONTROL_STATE_FIELDS,
    decode_shutter_contact_state,
    decode_thermostat_state,
    encode_week_profile,
    encode_max_until_datetime,
    format_week_profile_by_day,
    format_week_profile_lines,
    get_expected_week_profile_temperature,
    local_datetime_to_max_day,
    get_week_profile_segment_start,
    normalize_week_profile_hex,
    parse_time_information_payload,
    parse_week_profile_text,
    parse_message,
    split_week_profile_for_send,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY_MIN = 5   # seconds before first reconnect attempt
RECONNECT_DELAY_MAX = 60  # upper bound for exponential backoff
ACK_TIMEOUT = 3.0
ACK_RETRIES = 2
SET_TEMPERATURE_ACK_TIMEOUT = 5.0
SET_TEMPERATURE_ACK_RETRIES = 4
CONFIG_ACK_TIMEOUT = 8.0
CONFIG_ACK_RETRIES = 4
CONFIG_WAKE_SETTLE_DELAY = 0.5
WEEK_PROFILE_ACK_TIMEOUT = 12.0
WEEK_PROFILE_ACK_RETRIES = 5
WEEK_PROFILE_PART_DELAY = 0.35
WEEK_PROFILE_DAY_DELAY = 0.75
RECONNECT_WAIT_TIMEOUT = 12.0
# a-culfw keeps a 1% duty-cycle budget in credit_10ms (rf_send.h: MAX_CREDIT
# 900, +1 per second in clock.c). A "Zs" send with its 1 s wake-up preamble
# costs 100 + bits/10. Packets sent without enough credit are dropped with
# "LOVF". The real value is queried with "X"; the estimate only bridges the
# time between queries. Custom firmware may allow more, so the cap is learned
# from the reported values.
CUL_CREDIT_DEFAULT_MAX = 900.0
CUL_CREDIT_RECOVERY_PER_SECOND = 1.0
CUL_CREDIT_PREAMBLE_COST = 100.0
CUL_CREDIT_QUERY_TIMEOUT = 2.0
CUL_CREDIT_QUERY_MIN_INTERVAL = 3.0
CUL_CREDIT_MAX_WAIT_SLICE = 5.0
CUL_CREDIT_UNKNOWN_WAIT = 5.0
# Background and bulk traffic leaves this much credit untouched so that an
# interactive SetTemperature can always be sent immediately.
CUL_CREDIT_INTERACTIVE_RESERVE = 115.0
CUL_LOVF_MAX_RESENDS = 3
CUL_CREDIT_STANDARD_MAX = CUL_CREDIT_DEFAULT_MAX
# Switch to the extended profile only with a clearly larger budget or a
# clearly faster recovery than standard a-culfw.
CUL_CREDIT_EXTENDED_MAX_FACTOR = 1.5
CUL_CREDIT_EXTENDED_RATE = 1.5
CUL_CREDIT_POLL_INTERVAL = 300.0
CUL_CREDIT_RATE_MIN_INTERVAL = 20.0
COMMAND_PRIORITY_HIGH = 0     # interactive: SetTemperature
COMMAND_PRIORITY_NORMAL = 1   # user-initiated config writes
COMMAND_PRIORITY_LOW = 2      # background: time sync, retries
STORAGE_SAVE_DELAY = 10.0
PERIODIC_TIME_SYNC_INTERVAL = 3600.0
PERIODIC_TIME_SYNC_MIN_AGE = timedelta(minutes=55)
STARTUP_TIME_SYNC_INITIAL_DELAY = 90.0
STARTUP_TIME_SYNC_DEVICE_DELAY = 1.5
PENDING_QUEUE_MAINTENANCE_INTERVAL = 60.0
PENDING_QUEUE_RETRY_BASE_DELAY = 30.0
PENDING_QUEUE_RETRY_MAX_DELAY = 300.0
AUTO_MODE_TIME_SYNC_FOLLOWUP_DELAY = 12.0
# Virtual window contacts behave like real ones: the state goes directly to
# each linked thermostat, which ACKs it; it is repeated periodically
# (real contacts report hourly) so a lost telegram cannot leave a thermostat
# stuck at its window-open temperature.
VIRTUAL_CONTACT_REFRESH_INTERVAL = 50 * 60.0
VIRTUAL_CONTACT_RETRY_DELAY = 60.0
VIRTUAL_CONTACT_STARTUP_DELAY = 120.0
# External room temperature ("virtual wall thermostat"): a thermostat linked
# to the virtual wall thermostat regulates on the value sent in
# WallThermostatControl (0x42) instead of its own sensor at the radiator.
EXTERNAL_TEMP_MIN_CHANGE = 0.2
# Vacation mode
VACATION_DEFAULT_TEMPERATURE = 16.0
VACATION_SEND_ROUNDS = 4
VACATION_RETRY_DELAY = 120.0
# Many sensors (e.g. ZHA/Zigbee thermometers) only report on change, so a
# steady room can stay silent for hours. Rely on the sensor's integration to
# mark it unavailable (ZHA: 6 h for battery devices) and only treat values
# older than this as stale.
EXTERNAL_TEMP_SENSOR_MAX_AGE = timedelta(hours=8)
EXTERNAL_TEMP_RETRY_DELAY = 60.0
EXTERNAL_TEMP_HEARTBEAT = {"standard": 20 * 60.0, "extended": 8 * 60.0}
EXTERNAL_TEMP_MIN_INTERVAL = {"standard": 5 * 60.0, "extended": 90.0}
EXTERNAL_TEMP_TARGET_MIN_INTERVAL = 10.0

TEMPERATURE_CONFIG_KEYS = (
    "comfort_temperature",
    "eco_temperature",
    "window_open_temperature",
    "window_open_duration",
    "measurement_offset",
)
TEMPERATURE_CONFIG_APPLY_DELAY = 5.0

# Telegram types a device sends to its central (not to link partners).
FOREIGN_CENTRAL_MSG_TYPES = {0x00, 0x02, 0x03, 0x30, 0x50, 0x60, 0x70}
FOREIGN_CENTRAL_GRACE = timedelta(days=2)
TIME_INFORMATION_ACK_TIMEOUT = 3.0
TIME_INFORMATION_ACK_RETRIES = 2


def _sanitize_serial_number(raw: str) -> str:
    """Return a cleaned-up printable serial number."""
    cleaned = "".join(ch for ch in raw if ch.isprintable() and ch.isascii())
    return cleaned.strip().strip("\x00")


def _default_device_name(device_type: int, address: str, serial_number: str = "") -> str:
    """Return one stable default name for a MAX! device."""
    device_type_name = DEVICE_TYPE_NAMES.get(device_type, "Unbekannt")
    serial = _sanitize_serial_number(serial_number)
    if serial:
        return f"{device_type_name} {serial} ({address.upper()})"
    return f"{device_type_name} {address.upper()}"


def _is_legacy_auto_name(name: str, device_type: int, address: str) -> bool:
    """Return whether a stored name looks like an old auto-generated fallback."""
    normalized = name.strip()
    candidates = {
        f"{DEVICE_TYPE_NAMES.get(device_type, 'Unbekannt')} {address.upper()}",
        f"Unbekannt {address.upper()}",
    }
    return normalized in candidates


@dataclass
class KnownDevice:
    """Persistent record of a known MAX! device."""
    address: str           # 6-char hex string, e.g. "1A2B3C"
    device_type: int       # DEVICE_* constant
    name: str              # user-facing name
    serial_number: str = ""
    firmware_version: str = ""
    paired: bool = False
    last_seen: str = ""
    last_ack_at: str = ""
    last_command_success_at: str = ""
    last_send_error: str = ""
    last_send_error_at: str = ""
    last_command_retries: int = 0
    total_retry_count: int = 0
    is_virtual: bool = False
    group_id: int = 0
    linked_partners: list[str] = field(default_factory=list)
    superseded_by: str = ""
    duplicate_reason: str = ""
    pending_config: list[str] = field(default_factory=list)
    last_command: str = ""
    last_time_sync_at: str = ""
    last_reported_time: str = ""
    last_time_offset_seconds: int | None = None
    time_slot: int = -1
    week_profile: str = ""
    comfort_temperature: float = 21.0
    eco_temperature: float = 17.0
    maximum_temperature: float = 30.5
    minimum_temperature: float = 4.5
    measurement_offset: float = 0.0
    window_open_temperature: float = 12.0
    window_open_duration: int = 15
    last_state: dict[str, Any] = field(default_factory=dict)
    # Set when the device reports to an unknown address instead of this
    # central, i.e. it is still paired with another controller (old Cube).
    foreign_central: str = ""
    foreign_central_seen_at: str = ""
    last_central_contact_at: str = ""
    # External room temperature sensor (HA entity) used via the virtual wall
    # thermostat; empty = thermostat regulates on its own sensor.
    external_sensor: str = ""
    last_target_change_at: str = ""
    # MAX! days (0=Sat … 6=Fri) of week_profile that were really written to
    # the device. Empty = all seven (profiles from before this field or
    # complete uploads). Devices cannot report their program, so days that
    # were programmed elsewhere (old Cube) stay unknown.
    week_profile_days: list[int] = field(default_factory=list)


@dataclass
class PendingAck:
    """Tracks one in-flight MAX! command awaiting ACK."""
    counter: int
    expected_src: str | None
    future: asyncio.Future[MaxMessage]
    description: str


@dataclass
class CommandRequest:
    """One queued MAX! write operation."""
    cmd: str
    expected_src: str | None
    device_address: str | None
    counter: int | None
    description: str
    retries: int
    timeout: float
    future: asyncio.Future[MaxMessage | None]
    priority: int = COMMAND_PRIORITY_NORMAL


@dataclass(frozen=True)
class SendProfile:
    """Retry/pacing tunables that depend on the CUL's send budget."""

    name: str
    set_temperature_timeout: float
    set_temperature_retries: int
    config_retries: int
    week_profile_retries: int
    pending_retry_base_delay: float
    pending_retry_max_delay: float
    startup_time_sync_device_delay: float
    interactive_reserve_packets: int


# Standard a-culfw (MAX_CREDIT 900, 1 % duty cycle): conservative.
SEND_PROFILE_STANDARD = SendProfile(
    name="standard",
    set_temperature_timeout=SET_TEMPERATURE_ACK_TIMEOUT,
    set_temperature_retries=SET_TEMPERATURE_ACK_RETRIES,
    config_retries=CONFIG_ACK_RETRIES,
    week_profile_retries=WEEK_PROFILE_ACK_RETRIES,
    pending_retry_base_delay=PENDING_QUEUE_RETRY_BASE_DELAY,
    pending_retry_max_delay=PENDING_QUEUE_RETRY_MAX_DELAY,
    startup_time_sync_device_delay=STARTUP_TIME_SYNC_DEVICE_DELAY,
    interactive_reserve_packets=1,
)
# Firmware reporting a clearly larger budget: recover from lost packets
# faster. Thermostats ACK about 1.1-1.3 s after the start of a Zs send.
SEND_PROFILE_EXTENDED = SendProfile(
    name="extended",
    set_temperature_timeout=3.0,
    set_temperature_retries=6,
    config_retries=CONFIG_ACK_RETRIES + 2,
    week_profile_retries=WEEK_PROFILE_ACK_RETRIES + 2,
    pending_retry_base_delay=10.0,
    pending_retry_max_delay=120.0,
    startup_time_sync_device_delay=0.5,
    interactive_reserve_packets=7,
)


class CulCreditError(ConnectionError):
    """The CUL rejected a send because its duty-cycle credit ran out (LOVF)."""


class DeviceNackError(ConnectionError):
    """The device answered with 'invalid command/argument' (NACK)."""


@dataclass
class PendingShutterCommand:
    """One deferred config command for a sleepy shutter contact."""
    op: str
    description: str
    group_id: int | None = None
    partner_address: str | None = None
    partner_type: int | None = None
    queued_at: str = ""
    last_attempt_at: str = ""
    next_attempt_at: str = ""
    last_error: str = ""
    last_error_at: str = ""
    attempts: int = 0


@dataclass
class PendingClimateCommand:
    """One deferred config command for a climate device."""
    op: str
    description: str
    day: int | None = None
    part: int | None = None
    chunk_hex: str = ""
    profile_hex: str = ""
    queued_at: str = ""
    last_attempt_at: str = ""
    next_attempt_at: str = ""
    last_error: str = ""
    last_error_at: str = ""
    attempts: int = 0


def _serialize_pending_shutter_command(command: PendingShutterCommand) -> dict[str, Any]:
    """Serialize one pending shutter-contact command for storage."""
    return {
        "op": command.op,
        "description": command.description,
        "group_id": command.group_id,
        "partner_address": command.partner_address,
        "partner_type": command.partner_type,
        "queued_at": command.queued_at,
        "last_attempt_at": command.last_attempt_at,
        "next_attempt_at": command.next_attempt_at,
        "last_error": command.last_error,
        "last_error_at": command.last_error_at,
        "attempts": command.attempts,
    }


def _deserialize_pending_shutter_command(data: dict[str, Any]) -> PendingShutterCommand:
    """Deserialize one pending shutter-contact command from storage."""
    return PendingShutterCommand(
        op=str(data.get("op", "")),
        description=str(data.get("description", "")),
        group_id=data.get("group_id"),
        partner_address=(
            str(data["partner_address"]).upper()
            if data.get("partner_address")
            else None
        ),
        partner_type=(
            int(data["partner_type"]) if data.get("partner_type") is not None else None
        ),
        queued_at=str(data.get("queued_at", "")),
        last_attempt_at=str(data.get("last_attempt_at", "")),
        next_attempt_at=str(data.get("next_attempt_at", "")),
        last_error=str(data.get("last_error", "")),
        last_error_at=str(data.get("last_error_at", "")),
        attempts=int(data.get("attempts", 0)),
    )


def _serialize_pending_climate_command(command: PendingClimateCommand) -> dict[str, Any]:
    """Serialize one pending climate command for storage."""
    return {
        "op": command.op,
        "description": command.description,
        "day": command.day,
        "part": command.part,
        "chunk_hex": command.chunk_hex,
        "profile_hex": command.profile_hex,
        "queued_at": command.queued_at,
        "last_attempt_at": command.last_attempt_at,
        "next_attempt_at": command.next_attempt_at,
        "last_error": command.last_error,
        "last_error_at": command.last_error_at,
        "attempts": command.attempts,
    }


def _deserialize_pending_climate_command(data: dict[str, Any]) -> PendingClimateCommand:
    """Deserialize one pending climate command from storage."""
    return PendingClimateCommand(
        op=str(data.get("op", "")),
        description=str(data.get("description", "")),
        day=int(data["day"]) if data.get("day") is not None else None,
        part=int(data["part"]) if data.get("part") is not None else None,
        chunk_hex=str(data.get("chunk_hex", "")),
        profile_hex=str(data.get("profile_hex", "")),
        queued_at=str(data.get("queued_at", "")),
        last_attempt_at=str(data.get("last_attempt_at", "")),
        next_attempt_at=str(data.get("next_attempt_at", "")),
        last_error=str(data.get("last_error", "")),
        last_error_at=str(data.get("last_error_at", "")),
        attempts=int(data.get("attempts", 0)),
    )


async def open_cul_connection(
    host: str, port: int, *, serial: bool = False
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open the CUL either via TCP (host, port) or USB/serial (device, baud rate)."""
    if serial:
        # Same library Home Assistant's own serial integrations use.
        from serialx import open_serial_connection  # noqa: PLC0415

        return await open_serial_connection(url=host, baudrate=port)
    return await asyncio.open_connection(host, port)


def _default_vacation_state() -> dict[str, Any]:
    """Persisted vacation settings and run state."""
    return {
        "active": False,
        "temperature": VACATION_DEFAULT_TEMPERATURE,
        "end": None,            # planned return (ISO, local tz)
        "preheat_hours": 0.0,   # thermostats return to their program this much earlier
        "device_end": None,     # end sent to the thermostats (ISO, :00/:30)
        "started_at": None,
        "devices": {},          # address -> {prev_mode, prev_temperature, status, error, updated_at}
    }


def _floor_half_hour(when: datetime) -> datetime:
    """Round down to the MAX! until resolution (:00 / :30)."""
    return when.replace(minute=0 if when.minute < 30 else 30, second=0, microsecond=0)


def _vacation_until_passed(until: Any) -> bool:
    """True if a decoded 'YYYY-MM-DD HH:MM' until (local time) lies in the past."""
    if not until:
        return False
    try:
        parsed = datetime.strptime(str(until), "%Y-%m-%d %H:%M")
    except ValueError:
        return False
    return parsed.replace(tzinfo=dt_util.get_default_time_zone()) <= dt_util.now()


class CulMaxCoordinator:
    _SUPPORTED_LINK_TYPES: dict[int, set[int]] = {
        DEVICE_SHUTTER_CONTACT: {
            DEVICE_HEATING_THERMOSTAT,
            DEVICE_HEATING_THERMOSTAT_PLUS,
            DEVICE_WALL_THERMOSTAT,
        },
        DEVICE_HEATING_THERMOSTAT: {
            DEVICE_SHUTTER_CONTACT,
            DEVICE_WALL_THERMOSTAT,
        },
        DEVICE_HEATING_THERMOSTAT_PLUS: {
            DEVICE_SHUTTER_CONTACT,
            DEVICE_WALL_THERMOSTAT,
        },
        DEVICE_WALL_THERMOSTAT: {
            DEVICE_SHUTTER_CONTACT,
            DEVICE_HEATING_THERMOSTAT,
            DEVICE_HEATING_THERMOSTAT_PLUS,
        },
    }

    async def async_wake_device(self, address: str) -> None:
        """Send WakeUp (0xF1) — keeps device RF receiver open briefly."""
        dst = int(address, 16)
        self._counter = (self._counter + 1) % 256
        cmd = build_wake_up(self._counter, self.own_address, dst)
        await self._send_raw(cmd)
    """
    Manages the TCP connection to a CULFW device and dispatches MAX! messages.

    Listeners register via add_listener() / add_global_listener() and are called
    with (MaxMessage, decoded_state) whenever a relevant message arrives.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int = DEFAULT_PORT,
        own_address: int = DEFAULT_OWN_ADDRESS,
        config_entry_id: str | None = None,
        serial: bool = False,
    ) -> None:
        self.hass = hass
        self.config_entry_id = config_entry_id
        # TCP: host/port. USB/serial: host = device path, port = baud rate
        # (kept in the same fields so identifiers stay stable and simple).
        self.host = host
        self.port = port
        self.serial = serial
        self.own_address = own_address

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._counter: int = 0
        self._pairing_mode: bool = False
        self._pairing_task: asyncio.Task | None = None
        self._pairing_until: datetime | None = None
        self._reconnecting: bool = False
        self._shutting_down: bool = False
        self._reconnect_delay: int = RECONNECT_DELAY_MIN
        self._polling_task: asyncio.Task | None = None
        self._startup_time_sync_task: asyncio.Task | None = None
        self._pending_queue_task: asyncio.Task | None = None
        self._auto_mode_time_sync_tasks: dict[str, asyncio.Task] = {}
        self._command_queue: asyncio.PriorityQueue[tuple[int, int, CommandRequest]] = (
            asyncio.PriorityQueue()
        )
        self._command_seq: int = 0
        self._queued_priority_counts: dict[int, int] = {}
        self._command_enqueued = asyncio.Event()
        self._command_worker_task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._cul_credit_lock = asyncio.Lock()
        self._pending_ack: PendingAck | None = None
        self._pending_shutter_config: dict[str, list[PendingShutterCommand]] = {}
        self._pending_shutter_tasks: dict[str, asyncio.Task] = {}
        self._pending_climate_config: dict[str, list[PendingClimateCommand]] = {}
        self._pending_climate_tasks: dict[str, asyncio.Task] = {}
        self._config_drafts: dict[str, dict[str, Any]] = {}
        self._cul_credit_estimate: float = CUL_CREDIT_DEFAULT_MAX / 2
        self._cul_credit_updated_at: float = 0.0
        self._cul_credit_max: float = CUL_CREDIT_DEFAULT_MAX
        self._cul_credit_known: bool = False
        self._cul_credit_queried_at: float = 0.0
        self._cul_credit_future: asyncio.Future[int] | None = None
        self._last_tx_at: float = 0.0
        self._cul_credit_rate: float = CUL_CREDIT_RECOVERY_PER_SECOND
        self._cul_credit_rate_samples: int = 0
        self._cul_credit_consumed_total: float = 0.0
        self._cul_credit_last_report: tuple[float, float, float] | None = None
        self._cul_credit_reported_at: float = 0.0
        self._send_profile: SendProfile = SEND_PROFILE_STANDARD
        # Virtual contacts: per-contact send lock, last delivery attempt
        # (loop time) and whether every linked thermostat confirmed it.
        self._virtual_contact_locks: dict[str, asyncio.Lock] = {}
        self._virtual_contact_sent_at: dict[str, float] = {}
        self._virtual_contact_confirmed: dict[str, bool] = {}
        self._virtual_contact_failures: dict[str, int] = {}
        # External temperature: per thermostat last delivery and listeners
        self._ext_last: dict[str, dict[str, Any]] = {}
        self._ext_intended: dict[str, float] = {}
        self._ext_unsubs: dict[str, Callable[[], None]] = {}
        self._ext_locks: dict[str, asyncio.Lock] = {}
        self._temp_apply_tasks: dict[str, asyncio.Task] = {}
        self._virtual_contact_refresh_after: float = 0.0
        self._cul_status_listeners: list[Callable[[], None]] = []
        # Vacation mode (whole flat or selected thermostats), persisted
        self._vacation: dict[str, Any] = _default_vacation_state()
        self._vacation_task: asyncio.Task | None = None
        self._vacation_timer_unsub: Callable[[], None] | None = None
        self._vacation_listeners: list[Callable[[], None]] = []

        self._devices: dict[str, KnownDevice] = {}
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Per-device listeners: address -> [callback(MaxMessage, decoded)]
        self._listeners: dict[str, list[Callable]] = {}
        # Global listeners receive every message
        self._global_listeners: list[Callable] = []
        # Week profile listeners: address -> [callback()]
        self._week_profile_listeners: dict[str, list[Callable[[], None]]] = {}
        # Diagnostic listeners: address -> [callback()]
        self._diagnostic_listeners: dict[str, list[Callable[[], None]]] = {}
        # Integration-wide pairing listeners: [callback()]
        self._pairing_state_listeners: list[Callable[[], None]] = []

    def _migrate_storage_data(self, data: Any) -> tuple[dict[str, Any], bool]:
        """Migrate stored integration data to the current explicit schema."""
        if not isinstance(data, dict):
            return {"schema_version": STORAGE_SCHEMA_VERSION, "devices": {}}, True

        schema_version = int(data.get("schema_version", 1) or 1)
        migrated = dict(data)
        changed = False

        if schema_version < 2:
            devices = migrated.get("devices")
            if not isinstance(devices, dict):
                devices = {}
                migrated["devices"] = devices
                changed = True

            normalized_devices: dict[str, dict[str, Any]] = {}
            for raw_addr, raw_device in devices.items():
                if not isinstance(raw_device, dict):
                    changed = True
                    continue

                normalized_addr = str(raw_addr).upper()
                entry = dict(raw_device)
                entry["address"] = str(entry.get("address", normalized_addr)).upper()

                linked = entry.get("linked_partners", [])
                normalized_linked = (
                    list(dict.fromkeys(str(addr).upper() for addr in linked if addr))
                    if isinstance(linked, list)
                    else []
                )
                if linked != normalized_linked:
                    changed = True
                entry["linked_partners"] = normalized_linked

                profile = str(entry.get("week_profile", "") or "").strip()
                normalized_profile = normalize_week_profile_hex(profile) if profile else ""
                if normalized_profile != profile:
                    changed = True
                entry["week_profile"] = normalized_profile

                if "pending_config" in entry:
                    entry.pop("pending_config", None)
                    changed = True

                normalized_devices[normalized_addr] = entry
                if normalized_addr != raw_addr or entry["address"] != raw_device.get("address", normalized_addr):
                    changed = True

            migrated["devices"] = normalized_devices

            for queue_key in ("pending_shutter_config", "pending_climate_config"):
                queue_map = migrated.get(queue_key)
                if not isinstance(queue_map, dict):
                    migrated[queue_key] = {}
                    changed = True
                    continue
                normalized_queue_map: dict[str, Any] = {}
                for raw_addr, commands in queue_map.items():
                    normalized_addr = str(raw_addr).upper()
                    normalized_queue_map[normalized_addr] = commands
                    if normalized_addr != raw_addr:
                        changed = True
                migrated[queue_key] = normalized_queue_map

            migrated["schema_version"] = 2
            schema_version = 2
            changed = True

        if schema_version != STORAGE_SCHEMA_VERSION:
            migrated["schema_version"] = STORAGE_SCHEMA_VERSION
            changed = True

        return migrated, changed

    def _supported_partner_types(self, device_type: int) -> set[int]:
        """Return supported partner device types for on-device MAX! links."""
        return self._SUPPORTED_LINK_TYPES.get(device_type, set())

    def get_supported_partner_type_names(self, device_type: int) -> list[str]:
        """Return supported partner type names for diagnostics/UI."""
        return sorted(
            DEVICE_TYPE_NAMES.get(partner_type, f"type_{partner_type}")
            for partner_type in self._supported_partner_types(device_type)
        )

    def get_device_registry_model(self, device: KnownDevice) -> str:
        """Return a compact device model label for the HA device registry."""
        base = f"MAX! {DEVICE_TYPE_NAMES.get(device.device_type, device.device_type)}"
        flags: list[str] = []
        pairing_state = self.get_pairing_state(device.address)
        if pairing_state != "paired":
            flags.append(pairing_state)
        if device.pending_config:
            flags.append("pending config")
        if flags:
            return f"{base} · " + ", ".join(flags)
        return base

    def get_registry_device(
        self, registry: dr.DeviceRegistry, address: str
    ) -> dr.DeviceEntry | None:
        """Look up the HA device of one MAX! address owned by this config entry."""
        if self.config_entry_id is None:
            return None
        return registry.async_get_device_by_identifier(
            (DOMAIN, address.upper()), self.config_entry_id
        )

    async def _sync_device_registry_entry(self, address: str) -> None:
        """Update the HA device-registry model text for one MAX! device."""
        normalized = address.upper()
        device = self.get_device(normalized)
        if device is None:
            return
        registry = dr.async_get(self.hass)
        entry = self.get_registry_device(registry, normalized)
        if entry is None:
            return
        desired_model = self.get_device_registry_model(device)
        if entry.model == desired_model and entry.name == device.name:
            return
        registry.async_update_device(
            entry.id,
            model=desired_model,
            name=device.name,
        )

    def _validate_link_supported(self, address: str, partner_address: str) -> None:
        """Validate whether two MAX! devices support an on-device peer link."""
        device = self.get_device(address)
        partner = self.get_device(partner_address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if partner is None:
            raise ValueError(f"Unbekannte Partneradresse {partner_address}")
        supported = self._supported_partner_types(device.device_type)
        if supported and partner.device_type in supported:
            return
        raise ValueError(
            "Diese MAX!-Assoziation wird nicht unterstuetzt: "
            f"{self._format_device_identity(address)} -> {self._format_device_identity(partner_address)}. "
            f"Erlaubte Partner fuer {DEVICE_TYPE_NAMES.get(device.device_type, device.device_type)} sind: "
            f"{', '.join(self.get_supported_partner_type_names(device.device_type)) or 'keine'}."
        )

    def get_peer_names(self, address: str) -> list[str]:
        """Return linked partner names for one device."""
        device = self.get_device(address)
        if device is None:
            return []
        names: list[str] = []
        for peer_address in device.linked_partners:
            peer = self.get_device(peer_address)
            names.append(peer.name if peer else peer_address)
        return names

    def get_peer_labels(self, address: str) -> list[str]:
        """Return linked partner labels including address/serial if available."""
        device = self.get_device(address)
        if device is None:
            return []
        return [self._format_device_identity(peer_address) for peer_address in device.linked_partners]

    def get_peer_summary(self, address: str) -> str:
        """Return a compact readable peer summary for one device."""
        names = self.get_peer_names(address)
        return ", ".join(names) if names else "none"

    def is_device_paired(self, address: str) -> bool:
        """Return whether one device is known to be properly paired."""
        device = self.get_device(address)
        if device is None:
            return False
        if device.is_virtual:
            return True
        return bool(device.paired)

    def get_pairing_state(self, address: str) -> str:
        """Return one readable pairing-state label."""
        device = self.get_device(address)
        if device is None:
            return "unknown"
        if device.is_virtual:
            return "virtual"
        if device.foreign_central:
            return "paired_elsewhere"
        return "paired" if device.paired else "discovered"

    def _require_paired_for_write(self, address: str) -> None:
        """Raise if a physical device is only discovered but not properly paired."""
        device = self.get_device(address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if device.is_virtual or device.paired:
            return
        raise ValueError(
            f"Geraet {self._format_device_identity(address)} ist nur discovered und noch nicht gepaired. "
            "Bitte das Geraet erst sauber anlernen, bevor Konfigurationen oder Raum-Assoziationen geschrieben werden."
        )

    def get_config_draft(self, address: str) -> dict[str, Any]:
        """Return the current unsaved config draft for one device."""
        return dict(self._config_drafts.get(address.upper(), {}))

    def has_config_draft(self, address: str) -> bool:
        """Return whether one device has unsaved config values."""
        return bool(self._config_drafts.get(address.upper()))

    def get_week_profile_day_value(self, address: str, day_key: str) -> str:
        """Return the visible week-profile day value, preferring unsaved drafts."""
        draft = self._config_drafts.get(address.upper(), {})
        draft_week = draft.get("week_profile_by_day")
        if isinstance(draft_week, dict) and day_key in draft_week:
            return str(draft_week[day_key])
        profile_hex = self.get_effective_week_profile(address)
        if not profile_hex:
            return ""
        return format_week_profile_by_day(profile_hex).get(day_key, "")

    def get_temperature_config_value(self, address: str, key: str) -> float | int | None:
        """Return one visible config value, preferring unsaved drafts."""
        draft = self._config_drafts.get(address.upper(), {})
        if key in draft:
            return draft[key]
        device = self.get_device(address)
        if device is None:
            return None
        return getattr(device, key, None)

    def get_raw_mode(self, address: str) -> int:
        """Return the last raw MAX! control mode of one climate device."""
        device = self.get_device(address)
        if device is None:
            return MODE_MANUAL
        last_state = device.last_state or {}
        mode = last_state.get("mode")
        try:
            return int(mode) if mode is not None else MODE_MANUAL
        except (TypeError, ValueError):
            return MODE_MANUAL

    def get_expected_week_profile_temperature(self, address: str) -> float | None:
        """Return the currently expected week-profile setpoint for one device."""
        profile_hex = self.get_effective_week_profile(address)
        if not profile_hex:
            return None
        now = dt_util.now()
        if local_datetime_to_max_day(now) not in self.get_week_profile_known_days(address):
            return None  # today's program was never written from here
        return get_expected_week_profile_temperature(profile_hex, now)

    def get_open_window_partner_addresses(self, address: str) -> list[str]:
        """Return linked shutter contacts that currently report open."""
        device = self.get_device(address)
        if device is None:
            return []
        open_partners: list[str] = []
        for partner_address in device.linked_partners:
            partner = self.get_device(partner_address)
            if partner is None or partner.device_type != DEVICE_SHUTTER_CONTACT:
                continue
            if bool((partner.last_state or {}).get("is_open")):
                open_partners.append(partner_address)
        return open_partners

    def get_week_profile_validation(self, address: str) -> dict[str, Any]:
        """Estimate whether the stored week profile is currently active on the device."""
        normalized = address.upper()
        device = self.get_device(normalized)
        if device is None:
            return {
                "state": "unknown",
                "reason": "device_not_found",
                "expected_temperature_now": None,
                "actual_target_temperature": None,
                "temperature_delta": None,
                "mode_detail": None,
                "mode_is_temporary": False,
                "config_pending": False,
                "window_open_active": False,
                "open_window_partners": [],
                "week_profile_available": False,
                "week_profile_source": None,
                "last_time_sync_at": None,
                "last_reported_time": None,
                "last_time_offset_seconds": None,
            }

        profile_hex = self.get_effective_week_profile(normalized)
        expected_temperature = self.get_expected_week_profile_temperature(normalized)
        last_state = device.last_state or {}
        actual_target = last_state.get("desired_temperature")
        try:
            actual_target = float(actual_target) if actual_target is not None else None
        except (TypeError, ValueError):
            actual_target = None
        raw_mode = self.get_raw_mode(normalized)
        mode_detail = MODE_NAMES.get(raw_mode, raw_mode)
        open_window_partners = self.get_open_window_partner_addresses(normalized)
        temperature_delta = (
            round(abs(actual_target - expected_temperature), 1)
            if actual_target is not None and expected_temperature is not None
            else None
        )
        week_profile_source = None
        if profile_hex:
            week_profile_source = "linked_partner" if profile_hex != device.week_profile else "device"

        state = "unknown"
        reason = "no_week_profile"
        if not profile_hex:
            state = "unknown"
            reason = "no_week_profile"
        elif expected_temperature is None:
            state = "unknown"
            reason = "no_expected_temperature"
        elif actual_target is None:
            state = "unknown"
            reason = "no_current_target"
        elif device.pending_config:
            state = "pending"
            reason = "config_pending"
        elif open_window_partners:
            state = "window_open"
            reason = "linked_window_open"
        elif raw_mode == MODE_BOOST:
            state = "boost"
            reason = "boost_active"
        elif raw_mode == MODE_VACATION:
            state = "temporary_override"
            reason = "temporary_mode"
        elif raw_mode != MODE_AUTO:
            state = "manual_override"
            reason = "non_auto_mode"
        elif abs(actual_target - expected_temperature) <= 0.1:
            state = "likely_applied"
            reason = "target_matches_expected"
        else:
            state = "mismatch"
            reason = "target_differs_from_expected"

        return {
            "state": state,
            "reason": reason,
            "expected_temperature_now": expected_temperature,
            "actual_target_temperature": actual_target,
            "temperature_delta": temperature_delta,
            "mode_detail": mode_detail,
            "mode_is_temporary": raw_mode == MODE_VACATION,
            "config_pending": bool(device.pending_config),
            "window_open_active": bool(open_window_partners),
            "open_window_partners": open_window_partners,
            "open_window_partner_names": [
                self.get_device(peer_address).name if self.get_device(peer_address) else peer_address
                for peer_address in open_window_partners
            ],
            "week_profile_available": bool(profile_hex),
            "week_profile_source": week_profile_source,
            "last_time_sync_at": device.last_time_sync_at or None,
            "last_reported_time": device.last_reported_time or None,
            "last_time_offset_seconds": device.last_time_offset_seconds,
        }

    def get_effective_week_profile(self, address: str) -> str:
        """Return the best available week profile for one device.

        Wall thermostats do not always carry a locally stored profile in our
        store, even when the linked room thermostats already have the effective
        schedule. In that case, fall back to the first linked climate peer with
        a stored profile so UI and diagnostics still reflect the active room
        schedule.
        """
        source = self._effective_week_profile_source(address)
        return source.week_profile if source is not None else ""

    def _effective_week_profile_source(self, address: str) -> KnownDevice | None:
        """The device whose stored profile is shown for ``address``."""
        device = self.get_device(address)
        if device is None:
            return None
        if device.week_profile:
            return device
        if device.device_type != DEVICE_WALL_THERMOSTAT:
            return None
        for partner_address in device.linked_partners:
            partner = self.get_device(partner_address)
            if (
                partner
                and partner.device_type in (DEVICE_HEATING_THERMOSTAT, DEVICE_HEATING_THERMOSTAT_PLUS)
                and partner.week_profile
            ):
                return partner
        for partner in self._devices.values():
            if (
                partner.device_type in (DEVICE_HEATING_THERMOSTAT, DEVICE_HEATING_THERMOSTAT_PLUS)
                and address.upper() in partner.linked_partners
                and partner.week_profile
            ):
                return partner
        return None

    def get_week_profile_known_days(self, address: str) -> set[int]:
        """MAX! days (0=Sat … 6=Fri) of the effective profile that are known."""
        source = self._effective_week_profile_source(address)
        if source is None or not source.week_profile:
            return set()
        return set(source.week_profile_days) if source.week_profile_days else set(range(7))

    def get_local_week_profile(self, address: str) -> str:
        """Return the device's own stored week profile without peer fallback.

        This is intentionally stricter than ``get_effective_week_profile()`` and
        mirrors FHEM's behavior for edit/upload operations: when a thermostat
        week profile is modified, the merge base must come from the device's own
        stored profile (or the MAX! default profile), not from a linked peer's
        profile.
        """
        device = self.get_device(address)
        if device is None:
            return ""
        return device.week_profile or ""

    async def async_set_week_profile_day_draft(self, address: str, day_key: str, value: str) -> None:
        """Stage one week-profile day change without sending it immediately."""
        normalized = address.upper()
        device = self.get_device(normalized)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        by_day = format_week_profile_by_day(self.get_local_week_profile(normalized))
        draft = self._config_drafts.setdefault(normalized, {})
        draft_by_day = dict(draft.get("week_profile_by_day") or by_day)
        cleaned_value = value.strip()
        draft_by_day[day_key] = cleaned_value
        draft["week_profile_by_day"] = draft_by_day
        dirty_days = set(draft.get("week_profile_dirty_days") or [])
        if cleaned_value != str(by_day.get(day_key, "")).strip():
            dirty_days.add(day_key)
        else:
            dirty_days.discard(day_key)
        if dirty_days:
            draft["week_profile_dirty_days"] = sorted(dirty_days)
        else:
            draft.pop("week_profile_dirty_days", None)
        self._notify_week_profile_updated(normalized)
        self._notify_diagnostics_updated(normalized)

    async def async_set_temperature_config_draft(self, address: str, key: str, value: float | int) -> None:
        """Stage one thermostat config change without sending it immediately."""
        normalized = address.upper()
        if self.get_device(normalized) is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        self._config_drafts.setdefault(normalized, {})[key] = value
        self._notify_diagnostics_updated(normalized)
        if key in TEMPERATURE_CONFIG_KEYS:
            self._schedule_temperature_config_apply(normalized)

    def _schedule_temperature_config_apply(self, address: str) -> None:
        """Send staged comfort/eco/window values after a short quiet period.

        Several values changed in a row go out as one ConfigTemperatures
        telegram; no separate "save" step is needed any more.
        """
        task = self._temp_apply_tasks.pop(address, None)
        if task is not None and not task.done():
            task.cancel()
        self._temp_apply_tasks[address] = self.hass.async_create_task(
            self._apply_temperature_config_later(address)
        )

    async def _apply_temperature_config_later(self, address: str) -> None:
        try:
            await asyncio.sleep(TEMPERATURE_CONFIG_APPLY_DELAY)
        except asyncio.CancelledError:
            return
        draft = self._config_drafts.get(address) or {}
        fields = {key: draft.pop(key) for key in list(draft) if key in TEMPERATURE_CONFIG_KEYS}
        if not draft:
            self._config_drafts.pop(address, None)
        if not fields:
            return
        try:
            await self._async_send_temperature_config(address, **fields)
        except Exception as err:  # noqa: BLE001 - reported via diagnostics
            _LOGGER.warning(
                "Applying %s to %s failed: %s",
                ", ".join(sorted(fields)),
                self._format_device_identity(address),
                err,
            )
        finally:
            self._temp_apply_tasks.pop(address, None)
            self._notify_diagnostics_updated(address)

    async def async_discard_config_draft(self, address: str) -> None:
        """Discard all unsaved config values for one device."""
        normalized = address.upper()
        if normalized in self._config_drafts:
            del self._config_drafts[normalized]
            self._notify_week_profile_updated(normalized)
            self._notify_diagnostics_updated(normalized)

    async def async_apply_config_draft(self, address: str) -> None:
        """Apply all staged config values for one device."""
        normalized = address.upper()
        draft = self._config_drafts.get(normalized)
        if not draft:
            return

        if "week_profile_by_day" in draft:
            week_by_day = draft["week_profile_by_day"]
            if isinstance(week_by_day, dict):
                dirty_days = set(draft.get("week_profile_dirty_days") or [])
                ordered_lines: list[str] = []
                for day_key, label in (
                    ("monday", "Mon"),
                    ("tuesday", "Tue"),
                    ("wednesday", "Wed"),
                    ("thursday", "Thu"),
                    ("friday", "Fri"),
                    ("saturday", "Sat"),
                    ("sunday", "Sun"),
                ):
                    if dirty_days and day_key not in dirty_days:
                        continue
                    day_value = str(week_by_day.get(day_key, "")).strip()
                    if day_value:
                        ordered_lines.append(f"{label} {day_value}")
                if ordered_lines:
                    await self.async_set_week_profile(normalized, "\n".join(ordered_lines))

        temp_fields = {
            key: draft[key]
            for key in (
                "comfort_temperature",
                "eco_temperature",
                "window_open_temperature",
                "window_open_duration",
                "measurement_offset",
            )
            if key in draft
        }
        if temp_fields:
            await self._async_send_temperature_config(
                normalized,
                comfort_temperature=temp_fields.get("comfort_temperature"),
                eco_temperature=temp_fields.get("eco_temperature"),
                window_open_temperature=temp_fields.get("window_open_temperature"),
                window_open_duration=temp_fields.get("window_open_duration"),
                measurement_offset=temp_fields.get("measurement_offset"),
            )

        if normalized in self._config_drafts:
            del self._config_drafts[normalized]
        self._notify_week_profile_updated(normalized)
        self._notify_diagnostics_updated(normalized)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> bool:
        """Load persisted devices and open TCP connection."""
        self._shutting_down = False
        if self._command_worker_task is None or self._command_worker_task.done():
            self._command_worker_task = self.hass.loop.create_task(self._command_worker())
        if self._polling_task is None or self._polling_task.done():
            self._polling_task = self.hass.loop.create_task(self._periodic_time_sync_loop())
        if self._pending_queue_task is None or self._pending_queue_task.done():
            self._pending_queue_task = self.hass.loop.create_task(self._pending_queue_maintenance_loop())
        await self._load_devices()
        for device in self._devices.values():
            if device.foreign_central:
                self._sync_foreign_central_issue(device)
            if device.external_sensor:
                self._subscribe_external_sensor(device.address)
        await self._ensure_time_slots_assigned()
        connected = await self._connect()
        self._resume_vacation()
        if connected:
            self._virtual_contact_refresh_after = (
                self.hass.loop.time() + VIRTUAL_CONTACT_STARTUP_DELAY
            )
            self._schedule_startup_time_sync()
            self._resume_pending_config_processing()
            return True
        return False

    async def async_shutdown(self) -> None:
        """Close the TCP connection cleanly."""
        self._shutting_down = True
        self._reconnecting = False
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        if self._startup_time_sync_task:
            self._startup_time_sync_task.cancel()
            try:
                await self._startup_time_sync_task
            except asyncio.CancelledError:
                pass
        if self._pending_queue_task:
            self._pending_queue_task.cancel()
            try:
                await self._pending_queue_task
            except asyncio.CancelledError:
                pass
        for task in self._auto_mode_time_sync_tasks.values():
            task.cancel()
        for task in self._auto_mode_time_sync_tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._auto_mode_time_sync_tasks.clear()
        if self._pending_ack and not self._pending_ack.future.done():
            self._pending_ack.future.cancel()
        self._pending_ack = None
        if self._command_worker_task:
            self._command_worker_task.cancel()
            try:
                await self._command_worker_task
            except asyncio.CancelledError:
                pass
            self._command_worker_task = None
        for task in self._pending_shutter_tasks.values():
            task.cancel()
        for task in self._pending_shutter_tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._pending_shutter_tasks.clear()
        for task in self._pending_climate_tasks.values():
            task.cancel()
        for task in self._pending_climate_tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._pending_climate_tasks.clear()
        while not self._command_queue.empty():
            _prio, _seq, request = self._command_queue.get_nowait()
            if not request.future.done():
                request.future.cancel()
            self._command_queue.task_done()
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        for unsub in self._ext_unsubs.values():
            unsub()
        self._ext_unsubs.clear()
        if self._vacation_timer_unsub is not None:
            self._vacation_timer_unsub()
            self._vacation_timer_unsub = None
        if self._vacation_task is not None and not self._vacation_task.done():
            self._vacation_task.cancel()
            try:
                await self._vacation_task
            except asyncio.CancelledError:
                pass
        await self._close_connection()
        await self._save_devices_now()
        _LOGGER.info("CUL TCP connection to %s:%d closed", self.host, self.port)

    # ------------------------------------------------------------------
    # TCP connection
    # ------------------------------------------------------------------

    async def _connect(self) -> bool:
        """Open TCP connection to CULFW device and start read loop."""
        await self._close_connection()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                open_cul_connection(self.host, self.port, serial=self.serial),
                timeout=10.0,
            )
            self._reconnect_delay = RECONNECT_DELAY_MIN
            # Unknown until the first "X" answer; a-culfw boots with MAX/2.
            self._cul_credit_estimate = self._cul_credit_max / 2
            self._cul_credit_updated_at = self.hass.loop.time()
            self._cul_credit_known = False
            self._cul_credit_queried_at = 0.0
            _LOGGER.info("Connected to CULFW at %s:%d", self.host, self.port)
        except (OSError, asyncio.TimeoutError, ImportError) as e:
            _LOGGER.error("Cannot connect to CULFW at %s:%d — %s", self.host, self.port, e)
            return False

        # Init sequence mirrors the effective MAX!/Moritz setup used here: Zr
        # Brief delay needed — a-culfw ignores Zr if sent too fast after connect
        try:
            await asyncio.sleep(0.2)
            _LOGGER.info("CUL TX: %s", CULFW_CMD_MORITZ_RX.strip())
            await self._send_raw(CULFW_CMD_MORITZ_RX)
            await asyncio.sleep(0.1)
            # Let culfw ACK ShutterContactState / SetTemperature / PushButton
            # telegrams addressed to us right in firmware (20 ms, no preamble),
            # like FHEM does. Without it wall thermostats repeat each
            # SetTemperature to the central three times and contacts never get
            # their ACK.
            auto_ack = f"Za{self.own_address:06X}\n"
            _LOGGER.info("CUL TX: %s", auto_ack.strip())
            await self._send_raw(auto_ack)
            await asyncio.sleep(0.1)
            # Virtual wall thermostat: culfw ACKs SetTemperature telegrams that
            # linked thermostats send to it (knob turned on the thermostat).
            fake_wt = f"Zw{self.virtual_wall_thermostat_address:06X}\n"
            _LOGGER.info("CUL TX: %s", fake_wt.strip())
            await self._send_raw(fake_wt)
            await asyncio.sleep(0.1)
        except (ConnectionError, OSError) as e:
            _LOGGER.warning("CULFW init sequence failed at %s:%d: %s", self.host, self.port, e)
            await self._close_connection()
            return False

        self._read_task = self.hass.loop.create_task(self._read_loop())
        self.hass.loop.create_task(self._query_cul_credit(force=True))
        return True

    async def _close_connection(self) -> None:
        """Close the current TCP connection if one exists."""
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError, RuntimeError) as err:
                _LOGGER.debug("Ignoring socket-close error for %s:%d: %s", self.host, self.port, err)

    def _schedule_reconnect(self) -> None:
        """Schedule reconnect loop once, unless shutdown is in progress."""
        if self._shutting_down or self._reconnecting:
            return
        self._reconnecting = True
        self.hass.loop.create_task(self._reconnect_loop())

    async def _read_loop(self) -> None:
        """Continuously read lines from CULFW and dispatch MAX! messages."""
        assert self._reader is not None
        _LOGGER.debug("CUL read loop started")
        try:
            while True:
                line_bytes = await self._reader.readline()
                if not line_bytes:
                    _LOGGER.warning("CULFW connection closed by remote host")
                    break
                line = line_bytes.decode("ascii", errors="ignore").strip()
                if not line:
                    continue
                _LOGGER.debug("CUL RX: %s", line)
                await self._handle_line(line)
        except asyncio.CancelledError:
            return
        except ConnectionResetError as e:
            _LOGGER.warning("CULFW connection reset by peer: %s", e)
        except OSError as e:
            _LOGGER.warning("CULFW socket error: %s", e)
        except Exception:
            _LOGGER.exception("CUL read loop error")

        # Connection lost — try to reconnect
        await self._close_connection()
        self._schedule_reconnect()

    async def _reconnect_loop(self) -> None:
        """Keep attempting reconnection until successful."""
        while self._reconnecting:
            delay = self._reconnect_delay
            _LOGGER.info(
                "Reconnecting to CULFW at %s:%d in %ds...",
                self.host, self.port, delay,
            )
            await asyncio.sleep(delay)
            if await self._connect():
                self._reconnecting = False
                _LOGGER.info("Reconnected to CULFW at %s:%d", self.host, self.port)
                self._resume_pending_config_processing()
            else:
                self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_DELAY_MAX)

    async def _ensure_connected(self, timeout: float = RECONNECT_WAIT_TIMEOUT) -> None:
        """Ensure a live TCP connection exists, waiting briefly for reconnect if needed."""
        if self._writer is not None:
            return
        self._schedule_reconnect()
        deadline = self.hass.loop.time() + timeout
        while self._writer is None and self.hass.loop.time() < deadline:
            await asyncio.sleep(0.2)
        if self._writer is None:
            raise ConnectionError(
                f"not connected to CULFW at {self.host}:{self.port}"
            )

    def _has_more_urgent_command(self, priority: int) -> bool:
        """Return whether a command with higher priority is waiting."""
        return any(
            count > 0
            for queued_priority, count in self._queued_priority_counts.items()
            if queued_priority < priority
        )

    def _enqueue_command_request(self, request: CommandRequest) -> None:
        """Put one request into the priority queue (FIFO within a priority)."""
        self._command_seq += 1
        self._queued_priority_counts[request.priority] = (
            self._queued_priority_counts.get(request.priority, 0) + 1
        )
        self._command_queue.put_nowait((request.priority, self._command_seq, request))
        self._command_enqueued.set()

    def _credit_reserve_for(self, priority: int) -> float:
        """Credit that lower-priority traffic must leave for interactive commands."""
        if priority <= COMMAND_PRIORITY_HIGH:
            return 0.0
        if priority == COMMAND_PRIORITY_NORMAL:
            # User-initiated writes (week profile, config) are awaited by the
            # user: they may use the stored budget and only keep room for one
            # SetTemperature. The larger profile reserve is for background
            # traffic only – with a big bucket but slow recovery it otherwise
            # throttled a week-profile upload to one packet per ~2 minutes.
            return CUL_CREDIT_INTERACTIVE_RESERVE
        return CUL_CREDIT_INTERACTIVE_RESERVE * self._send_profile.interactive_reserve_packets

    async def _command_worker(self) -> None:
        """Process queued MAX! write operations strictly sequentially.

        Commands are taken by priority. While a command waits for CUL credit,
        a newly queued more urgent command (e.g. SetTemperature) preempts it,
        so interactive changes never sit behind background time syncs.
        """
        try:
            while True:
                priority, seq, request = await self._command_queue.get()
                self._queued_priority_counts[priority] = max(
                    0, self._queued_priority_counts.get(priority, 0) - 1
                )
                try:
                    if request.future.done():
                        continue
                    ready = await self._wait_for_cul_credit(
                        self._estimate_cul_credit_cost(request.cmd),
                        reserve=self._credit_reserve_for(priority),
                        preempt_priority=priority,
                    )
                    if not ready:
                        _LOGGER.debug(
                            "Deferring %s for a more urgent command", request.description
                        )
                        self._queued_priority_counts[priority] = (
                            self._queued_priority_counts.get(priority, 0) + 1
                        )
                        self._command_queue.put_nowait((priority, seq, request))
                        continue
                    result = await self._execute_command_request(request)
                    if not request.future.done():
                        request.future.set_result(result)
                except asyncio.CancelledError:
                    if not request.future.done():
                        request.future.cancel()
                    raise
                except Exception as err:
                    _LOGGER.debug("Command worker propagates exception for %s: %s", request.description, err)
                    if not request.future.done():
                        request.future.set_exception(err)
                finally:
                    self._command_queue.task_done()
        except asyncio.CancelledError:
            return

    async def _execute_command_request(
        self,
        request: CommandRequest,
    ) -> MaxMessage | None:
        """Send one queued command, optionally waiting for ACK with retries."""
        if request.counter is None:
            try:
                await self._send_raw(request.cmd)
                if request.device_address:
                    await self._mark_command_success(request.device_address, retries=0, ack_at=None)
                return None
            except Exception as err:
                if request.device_address:
                    await self._mark_command_error(
                        request.device_address,
                        str(err),
                        retries=0,
                    )
                raise

        last_error: Exception | None = None
        lovf_resends = 0
        attempt = 0
        while attempt < request.retries + 1:
            attempt += 1
            future: asyncio.Future[MaxMessage] = self.hass.loop.create_future()
            self._pending_ack = PendingAck(
                counter=request.counter,
                expected_src=request.expected_src.upper() if request.expected_src else None,
                future=future,
                description=request.description,
            )
            try:
                await self._send_raw(
                    request.cmd, reserve=self._credit_reserve_for(request.priority)
                )
                ack = await asyncio.wait_for(future, timeout=request.timeout)
                self._pending_ack = None
                if request.device_address:
                    await self._mark_command_success(
                        request.device_address,
                        retries=attempt - 1,
                        ack_at=datetime.now(UTC).isoformat(),
                    )
                _LOGGER.info("ACK ok for %s on attempt %d", request.description, attempt)
                return ack
            except asyncio.TimeoutError as err:
                last_error = err
                if not future.done():
                    future.cancel()
                self._pending_ack = None
                _LOGGER.warning(
                    "ACK timeout for %s on attempt %d/%d",
                    request.description,
                    attempt,
                    request.retries + 1,
                )
            except CulCreditError as err:
                last_error = err
                self._pending_ack = None
                lovf_resends += 1
                _LOGGER.warning(
                    "CUL dropped %s (LOVF, out of send credit); resending when credit is available",
                    request.description,
                )
                if lovf_resends <= CUL_LOVF_MAX_RESENDS:
                    attempt -= 1  # the packet never went on air
                continue
            except DeviceNackError as err:
                self._pending_ack = None
                _LOGGER.warning("Device rejected %s: %s", request.description, err)
                if request.device_address:
                    await self._mark_command_error(
                        request.device_address, str(err), retries=attempt - 1
                    )
                raise
            except Exception as err:
                last_error = err
                if not future.done():
                    future.cancel()
                self._pending_ack = None
                _LOGGER.warning(
                    "Send failed for %s on attempt %d/%d: %s",
                    request.description,
                    attempt,
                    request.retries + 1,
                    err,
                )
                if isinstance(err, (BrokenPipeError, ConnectionResetError, OSError, ConnectionError)):
                    break
        if isinstance(last_error, ConnectionError):
            error_message = f"Connection lost while sending {request.description}: {last_error}"
            if request.device_address:
                await self._mark_command_error(
                    request.device_address,
                    error_message,
                    retries=max(0, attempt - 1),
                )
            raise ConnectionError(error_message) from last_error
        if request.device_address:
            await self._mark_command_error(
                request.device_address,
                f"No ACK for {request.description}",
                retries=request.retries + 1,
            )
        raise ConnectionError(f"No ACK for {request.description}") from last_error

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _handle_line(self, line: str) -> None:
        """Parse and dispatch a received CULFW line."""
        if line.startswith("V"):
            _LOGGER.info("CULFW version: %s", line)
            return

        if line == "LOVF":
            _LOGGER.warning("CUL reports LOVF: send credit exhausted, packet dropped")
            self._handle_lovf()
            return

        credit = parse_credit_report(line)
        if credit is not None:
            _LOGGER.debug("CUL credit_10ms: %d", credit)
            self._handle_credit_report(credit)
            return

        if not line.startswith("Z"):
            _LOGGER.debug("Non-MAX line ignored: %s", line)
            return

        msg = parse_message(line)
        if msg is None:
            return
        if msg.src in (self.own_address, self.virtual_wall_thermostat_address):
            # Echo of an ACK that culfw sent on its own (auto-ACK via "Za"/"Zw").
            _LOGGER.debug("CUL auto-ACK sent to %s (counter=%d)", msg.dst_hex, msg.counter)
            self._consume_cul_credit(self._estimate_cul_credit_cost("Zf" + line[1:].split(" ")[0]))
            return
        await self._touch_device(msg.src_hex)
        source_device = self.get_device(msg.src_hex)
        if source_device is not None:
            self._check_foreign_central(msg, source_device)

        decoded: ThermostatState | ShutterContactState | None = None
        is_climate_source = (
            source_device is not None and source_device.device_type in CLIMATE_DEVICE_TYPES
        )

        if msg.msg_type == MSG_PAIR_PING:
            if self._pairing_mode:
                await self._handle_pair_ping(msg)
            else:
                _LOGGER.info(
                    "PairPing from %s ignored because pairing mode is not active",
                    msg.src_hex,
                )
            return

        if msg.msg_type in (0x60, 0x70):  # ThermostatState / WallThermostatState
            decoded = decode_thermostat_state(msg)
            if decoded:
                await self._update_device_group(msg.src_hex, msg.group)
                decoded = await self._merge_thermostat_state(
                    msg.src_hex, decoded.__dict__, keep_missing_measurement=True
                )
            else:
                _LOGGER.warning("Failed to decode thermostat state from %s", line)

        elif msg.msg_type == 0x42:  # WallThermostatControl
            control = decode_wall_thermostat_control(msg)
            if control:
                await self._update_device_group(msg.src_hex, msg.group)
                # 0x42 only carries desired + measured temperature. Do not
                # let it overwrite mode/flags of the wall thermostat.
                decoded = await self._merge_thermostat_state(
                    msg.src_hex,
                    {key: getattr(control, key) for key in WALL_CONTROL_STATE_FIELDS},
                    keep_missing_measurement=True,
                )
            else:
                _LOGGER.warning("Failed to decode wall thermostat control from %s", line)

        elif msg.msg_type == MSG_SET_TEMPERATURE and is_climate_source:
            # A wall thermostat announcing a new target/mode (knob, mode
            # button or its week program) to its thermostats and the central.
            set_state = decode_set_temperature(msg)
            if set_state:
                decoded = await self._merge_thermostat_state(
                    msg.src_hex, set_state, keep_missing_measurement=True
                )

        elif msg.msg_type == 0x30:  # ShutterContactState
            decoded = decode_shutter_contact_state(msg)
            if decoded:
                await self._update_device_group(msg.src_hex, msg.group)
                await self._update_device_state(msg.src_hex, decoded.__dict__)

        elif msg.msg_type == MSG_TIME_INFORMATION:
            await self._handle_time_information(msg)

        elif msg.msg_type == MSG_ACK:
            self._handle_ack(msg)
            if is_climate_source and source_device is not None:
                ack_state = decode_ack_state(
                    msg, is_wall=source_device.device_type == DEVICE_WALL_THERMOSTAT
                )
                if ack_state is not None:
                    decoded = await self._merge_thermostat_state(
                        msg.src_hex, ack_state, keep_missing_measurement=True
                    )

        self._log_decoded_message(msg, decoded)

        if source_device and source_device.device_type == DEVICE_SHUTTER_CONTACT:
            self._schedule_shutter_config_processing(msg.src_hex, trigger=f"rx:{msg.msg_type:02X}")
        if source_device and source_device.device_type in CLIMATE_DEVICE_TYPES:
            self._schedule_climate_config_processing(msg.src_hex, trigger=f"rx:{msg.msg_type:02X}")

        self._dispatch(msg, decoded)

    async def _handle_time_information(self, msg: MaxMessage) -> None:
        """Process incoming MAX! TimeInformation telegrams."""
        parsed = parse_time_information_payload(msg.payload) if msg.payload else None
        if parsed is not None:
            now_local = datetime.now().astimezone().replace(tzinfo=None)
            offset_seconds = int((now_local - parsed).total_seconds())
            await self._update_device_time_status(
                msg.src_hex,
                reported_time=parsed,
                offset_seconds=offset_seconds,
            )
            _LOGGER.info(
                "RX TimeInformation from %s: %s (offset=%ss)",
                self._format_device_identity(msg.src_hex),
                parsed.isoformat(sep=" "),
                offset_seconds,
            )
        elif msg.payload:
            _LOGGER.warning(
                "RX TimeInformation from %s could not be parsed: %s",
                self._format_device_identity(msg.src_hex),
                msg.payload.hex(),
            )

        if msg.dst != self.own_address:
            return

        if not msg.payload:
            _LOGGER.info(
                "TimeInformation request from %s without payload; sending current local time",
                self._format_device_identity(msg.src_hex),
            )
            self._reply_time_information(msg.src_hex)
            return

        if parsed is None:
            _LOGGER.info(
                "TimeInformation from %s has invalid payload; sending corrected time",
                self._format_device_identity(msg.src_hex),
            )
            self._reply_time_information(msg.src_hex)
            return

        if abs(offset_seconds) > 5:
            _LOGGER.info(
                "TimeInformation from %s is %ss out of sync; sending corrected time",
                self._format_device_identity(msg.src_hex),
                offset_seconds,
            )
            self._reply_time_information(msg.src_hex)

    # ------------------------------------------------------------------
    # External room temperature (virtual wall thermostat)
    # ------------------------------------------------------------------

    @property
    def controller_identifier(self) -> str:
        """Device-registry identifier of the CUL controller device."""
        return f"controller_{self.host}:{self.port}"

    @property
    def display_name(self) -> str:
        """Name of the controller device, e.g. 'MAX! CUL (192.168.1.5:2323)'."""
        if self.serial:
            return f"MAX! CUL ({self.host.rsplit('/', 1)[-1]})"
        return f"MAX! CUL ({self.host}:{self.port})"

    @property
    def virtual_wall_thermostat_address(self) -> int:
        """Address of the virtual wall thermostat (own address + 1)."""
        return (self.own_address + 1) & 0xFFFFFF

    def _read_external_temperature(self, device: KnownDevice) -> tuple[float | None, str]:
        """Return (temperature in °C, status) of the configured sensor."""
        state = self.hass.states.get(device.external_sensor)
        if state is None:
            return None, "sensor_missing"
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None, "sensor_unavailable"
        unit = state.attributes.get("unit_of_measurement")
        if unit == UnitOfTemperature.FAHRENHEIT:
            value = (value - 32.0) * 5.0 / 9.0
        reported = max(
            state.last_updated,
            getattr(state, "last_reported", state.last_updated) or state.last_updated,
        )
        if dt_util.utcnow() - reported > EXTERNAL_TEMP_SENSOR_MAX_AGE:
            return None, "sensor_stale"
        if not 0.0 <= value <= 51.0:
            return None, "sensor_out_of_range"
        return round(value, 1), "ok"

    def _intended_target(self, device: KnownDevice) -> float | None:
        """Target the virtual wall thermostat sends along.

        The thermostat's week program stays in charge: in auto mode the
        profile value applies unless the target was changed (HA, knob) after
        the current profile segment began. An open window never becomes the
        target. In other modes the thermostat's own target is kept.
        """
        state = device.last_state or {}
        desired = state.get("desired_temperature")
        mode = state.get("mode")
        if mode == MODE_VACATION and _vacation_until_passed(state.get("until")):
            mode = MODE_AUTO  # the thermostat has returned to its program by itself
        validation = self.get_week_profile_validation(device.address)
        window_open = bool(validation.get("window_open_active"))
        remembered = self._ext_intended.get(device.address)
        if mode == MODE_AUTO:
            now = dt_util.now()
            profile = self.get_effective_week_profile(device.address)
            expected = self.get_expected_week_profile_temperature(device.address)
            if window_open:
                return remembered if remembered is not None else expected
            if expected is None:
                result = desired
            else:
                segment_start = get_week_profile_segment_start(profile, now)
                changed_at = None
                if device.last_target_change_at:
                    try:
                        changed_at = datetime.fromisoformat(device.last_target_change_at)
                    except ValueError:
                        changed_at = None
                if changed_at is not None and segment_start is not None and changed_at >= segment_start:
                    result = desired
                else:
                    result = expected
        else:
            if window_open:
                return remembered if remembered is not None else desired
            result = desired
        if result is not None:
            self._ext_intended[device.address] = float(result)
        return float(result) if result is not None else None

    def get_external_temperature_status(self, address: str) -> dict[str, Any]:
        """Diagnostics for the climate entity / week profile card."""
        device = self.get_device(address)
        if device is None or not device.external_sensor:
            return {"external_temperature_sensor": None}
        last = self._ext_last.get(device.address, {})
        value, sensor_status = self._read_external_temperature(device)
        if sensor_status != "ok":
            status = sensor_status
        elif not last:
            status = "waiting"
        elif last.get("confirmed"):
            status = "active"
        else:
            status = "unconfirmed"
        return {
            "external_temperature_sensor": device.external_sensor,
            "external_temperature": value,
            "external_temperature_status": status,
            "external_temperature_sent": last.get("measured"),
            "external_target_sent": last.get("desired"),
            "external_temperature_sent_at": last.get("at_iso"),
            "external_temperature_confirmed": bool(last.get("confirmed")),
        }

    @callback
    def _subscribe_external_sensor(self, address: str) -> None:
        """(Re)subscribe to the configured external sensor."""
        normalized = address.upper()
        unsub = self._ext_unsubs.pop(normalized, None)
        if unsub is not None:
            unsub()
        device = self.get_device(normalized)
        if device is None or not device.external_sensor:
            return

        @callback
        def _changed(event: Event) -> None:
            self.hass.async_create_task(
                self._external_temperature_tick(normalized, reason="sensor")
            )

        self._ext_unsubs[normalized] = async_track_state_change_event(
            self.hass, [device.external_sensor], _changed
        )

    async def async_set_external_temperature_sensor(
        self, address: str, sensor_entity_id: str | None
    ) -> dict[str, Any]:
        """Let a thermostat regulate on an external sensor, or switch back.

        Links/unlinks the thermostat with the virtual wall thermostat on the
        device itself (AddLinkPartner/RemoveLinkPartner, type wall thermostat).
        """
        normalized = address.upper()
        device = self.get_device(normalized)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if device.device_type not in (DEVICE_HEATING_THERMOSTAT, DEVICE_HEATING_THERMOSTAT_PLUS):
            raise ValueError(
                "Ein externer Raumfuehler ist nur fuer Heizkoerperthermostate moeglich "
                "(Wandthermostate haben einen eigenen Fuehler)."
            )
        self._require_paired_for_write(normalized)
        sensor = (sensor_entity_id or "").strip()
        if sensor:
            if self.hass.states.get(sensor) is None:
                raise ValueError(f"Sensor {sensor} nicht gefunden.")
            if not sensor.startswith("sensor."):
                raise ValueError("Bitte einen Temperatursensor (sensor.*) waehlen.")
        previous = device.external_sensor
        vwt = self.virtual_wall_thermostat_address
        label = self.format_device_label(normalized)
        if sensor and not previous:
            counter = self._next_counter()
            await self._set_last_command(normalized, "AddLinkPartner virtueller Wandthermostat")
            await self._send_command(
                build_add_link_partner(counter, self.own_address, int(normalized, 16), vwt, DEVICE_WALL_THERMOSTAT),
                expected_src=normalized,
                device_address=normalized,
                counter=counter,
                description=f"AddLinkPartner {label} -> virtueller Wandthermostat {vwt:06X}",
                retries=self._send_profile.config_retries,
                timeout=CONFIG_ACK_TIMEOUT,
            )
        elif not sensor and previous:
            counter = self._next_counter()
            await self._set_last_command(normalized, "RemoveLinkPartner virtueller Wandthermostat")
            await self._send_command(
                build_remove_link_partner(counter, self.own_address, int(normalized, 16), vwt, DEVICE_WALL_THERMOSTAT),
                expected_src=normalized,
                device_address=normalized,
                counter=counter,
                description=f"RemoveLinkPartner {label} -> virtueller Wandthermostat {vwt:06X}",
                retries=self._send_profile.config_retries,
                timeout=CONFIG_ACK_TIMEOUT,
            )
        device.external_sensor = sensor
        self._ext_last.pop(normalized, None)
        await self._save_devices()
        self._subscribe_external_sensor(normalized)
        _LOGGER.info(
            "%s regulates on %s",
            self._format_device_identity(normalized),
            sensor or "its own sensor",
        )
        if sensor:
            await self._external_temperature_tick(normalized, reason="enabled")
        self._notify_week_profile_updated(normalized)
        self._notify_diagnostics_updated(normalized)
        return self.get_external_temperature_status(normalized)

    async def _external_temperature_tick(self, address: str, *, reason: str) -> None:
        """Send WallThermostatControl if the value or target changed or a heartbeat is due."""
        device = self.get_device(address)
        if device is None or not device.external_sensor or self._writer is None:
            return
        lock = self._ext_locks.setdefault(device.address, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            measured, sensor_status = self._read_external_temperature(device)
            if measured is None:
                _LOGGER.debug(
                    "External temperature for %s not sent: %s",
                    self._format_device_identity(device.address),
                    sensor_status,
                )
                return
            desired = self._intended_target(device)
            if desired is None:
                return
            profile = self._send_profile.name
            now = self.hass.loop.time()
            last = self._ext_last.get(device.address)
            if last is not None:
                age = now - last["at"]
                if not last.get("confirmed"):
                    due = age >= EXTERNAL_TEMP_RETRY_DELAY
                elif desired != last["desired"]:
                    due = age >= EXTERNAL_TEMP_TARGET_MIN_INTERVAL
                elif abs(measured - last["measured"]) >= EXTERNAL_TEMP_MIN_CHANGE:
                    due = age >= EXTERNAL_TEMP_MIN_INTERVAL.get(profile, 300.0)
                else:
                    due = age >= EXTERNAL_TEMP_HEARTBEAT.get(profile, 1200.0)
                if not due:
                    return
            counter = self._next_counter()
            cmd = build_wall_thermostat_control(
                counter,
                self.virtual_wall_thermostat_address,
                int(device.address, 16),
                desired,
                measured,
                0,
            )
            description = (
                f"WallThermostatControl {self.format_device_label(device.address)}: "
                f"Ist {measured:.1f} (extern), Soll {desired:.1f}"
            )
            confirmed = True
            try:
                await self._send_command(
                    cmd,
                    expected_src=device.address,
                    device_address=device.address,
                    counter=counter,
                    description=description,
                    retries=2,
                    timeout=self._send_profile.set_temperature_timeout,
                    priority=COMMAND_PRIORITY_NORMAL,
                )
            except Exception as err:  # noqa: BLE001 - retried later
                confirmed = False
                _LOGGER.warning("%s not confirmed (%s, trigger %s)", description, err, reason)
            self._ext_last[device.address] = {
                "at": self.hass.loop.time(),
                "at_iso": datetime.now(UTC).isoformat(),
                "measured": measured,
                "desired": desired,
                "confirmed": confirmed,
            }
            self._notify_week_profile_updated(device.address)

    # ------------------------------------------------------------------
    # Vacation mode
    # ------------------------------------------------------------------
    #
    # Uses the thermostats' own vacation mode (SetTemperature mode 2 with an
    # until timestamp): they hold the vacation temperature and return to
    # their week program at the until time on their own, even if Home
    # Assistant or the CUL is offline. HA remembers each thermostat's
    # previous state so manual/off thermostats are restored afterwards and
    # an early return switches everything back right away.

    def add_vacation_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._vacation_listeners.append(cb)

        def remove() -> None:
            if cb in self._vacation_listeners:
                self._vacation_listeners.remove(cb)

        return remove

    def _notify_vacation(self) -> None:
        for cb in list(self._vacation_listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Vacation listener failed")

    def _vacation_targets(self, addresses: list[str] | None = None) -> list[KnownDevice]:
        """Paired real thermostats; wall thermostats first (they drive their room)."""
        wanted = {a.upper() for a in addresses} if addresses else None
        devices = [
            d for d in self._devices.values()
            if d.device_type in CLIMATE_DEVICE_TYPES
            and d.paired
            and not d.is_virtual
            and not d.superseded_by
            and (wanted is None or d.address in wanted)
        ]
        if wanted is not None:
            unknown = wanted - {d.address for d in devices}
            if unknown:
                raise ValueError(
                    "Keine angemeldeten MAX!-Thermostate: " + ", ".join(sorted(unknown))
                )
        return sorted(devices, key=lambda d: (d.device_type != DEVICE_WALL_THERMOSTAT, d.name.lower()))

    def get_vacation_status(self) -> dict[str, Any]:
        """Settings, run state and per-thermostat delivery for entities and services."""
        vac = self._vacation
        devices = vac.get("devices") or {}
        counts: dict[str, int] = {}
        details: dict[str, str] = {}
        registry = dr.async_get(self.hass)
        for address, info in devices.items():
            status = str(info.get("status", "pending"))
            counts[status] = counts.get(status, 0) + 1
            entry = self.get_registry_device(registry, address)
            device = self.get_device(address)
            name = (
                (entry.name_by_user or entry.name) if entry is not None
                else (device.name if device else address)
            )
            details[name] = status
        return {
            "active": bool(vac.get("active")),
            "temperature": float(vac.get("temperature") or VACATION_DEFAULT_TEMPERATURE),
            "end": vac.get("end"),
            "preheat_hours": float(vac.get("preheat_hours") or 0.0),
            "device_end": vac.get("device_end"),
            "started_at": vac.get("started_at"),
            "counts": counts,
            "devices": details,
        }

    def vacation_end(self) -> datetime | None:
        """Planned return (local time) or None."""
        return self._vacation_end_datetime()

    def _vacation_end_datetime(self) -> datetime | None:
        raw = self._vacation.get("end")
        if not raw:
            return None
        try:
            return dt_util.as_local(datetime.fromisoformat(str(raw)))
        except ValueError:
            return None

    def _compute_device_end(self, end: datetime, preheat_hours: float) -> datetime:
        return _floor_half_hour(dt_util.as_local(end) - timedelta(hours=preheat_hours))

    async def async_set_vacation_settings(
        self,
        *,
        temperature: float | None = None,
        end: datetime | None = None,
        preheat_hours: float | None = None,
    ) -> None:
        """Change the settings; a running vacation is re-sent with the new values."""
        changed = False
        if temperature is not None and float(temperature) != self._vacation.get("temperature"):
            self._vacation["temperature"] = max(TEMP_MIN, min(TEMP_MAX, round(float(temperature) * 2) / 2))
            changed = True
        if end is not None:
            iso = dt_util.as_local(end).replace(second=0, microsecond=0).isoformat()
            if iso != self._vacation.get("end"):
                self._vacation["end"] = iso
                changed = True
        if preheat_hours is not None and float(preheat_hours) != self._vacation.get("preheat_hours"):
            self._vacation["preheat_hours"] = max(0.0, float(preheat_hours))
            changed = True
        if not changed:
            return
        await self._save_devices()
        self._notify_vacation()
        if self._vacation.get("active"):
            await self.async_start_vacation(
                addresses=list((self._vacation.get("devices") or {}).keys()) or None
            )

    async def async_start_vacation(
        self,
        *,
        temperature: float | None = None,
        end: datetime | None = None,
        preheat_hours: float | None = None,
        addresses: list[str] | None = None,
    ) -> dict[str, Any]:
        """Put the thermostats into vacation mode until the (preheat-adjusted) end."""
        if temperature is not None:
            self._vacation["temperature"] = max(TEMP_MIN, min(TEMP_MAX, round(float(temperature) * 2) / 2))
        if end is not None:
            self._vacation["end"] = dt_util.as_local(end).replace(second=0, microsecond=0).isoformat()
        if preheat_hours is not None:
            self._vacation["preheat_hours"] = max(0.0, float(preheat_hours))
        end_dt = self._vacation_end_datetime()
        if end_dt is None:
            raise ValueError("Bitte zuerst das Urlaubsende (Rückkehr) setzen.")
        device_end = self._compute_device_end(end_dt, float(self._vacation.get("preheat_hours") or 0.0))
        if device_end <= dt_util.now() + timedelta(minutes=5):
            raise ValueError(
                "Das Urlaubsende (abzüglich Vorheizen) muss mindestens ein paar Minuten in der Zukunft liegen."
            )
        targets = self._vacation_targets(addresses)
        if not targets:
            raise ValueError("Keine angemeldeten MAX!-Thermostate gefunden.")

        was_active = bool(self._vacation.get("active"))
        records: dict[str, dict[str, Any]] = (
            dict(self._vacation.get("devices") or {}) if was_active else {}
        )
        for device in targets:
            record = records.get(device.address)
            if record is None:
                state = device.last_state or {}
                prev_mode = state.get("mode", MODE_AUTO)
                if prev_mode in (MODE_BOOST, MODE_VACATION):
                    prev_mode = MODE_AUTO
                record = {
                    "prev_mode": int(prev_mode),
                    "prev_temperature": state.get("desired_temperature"),
                }
            record.update(status="pending", error="", updated_at=self._now_iso())
            records[device.address] = record
        self._vacation.update(
            active=True,
            devices=records,
            device_end=device_end.isoformat(),
            started_at=self._vacation.get("started_at") if was_active else self._now_iso(),
        )
        await self._save_devices_now()
        self._arm_vacation_timer()
        self._notify_vacation()
        _LOGGER.info(
            "Vacation: %d thermostat(s) to %.1f °C until %s (return %s)",
            len(targets),
            self._vacation["temperature"],
            device_end.strftime("%Y-%m-%d %H:%M"),
            end_dt.strftime("%Y-%m-%d %H:%M"),
        )
        self._run_vacation_task(self._vacation_send_all([d.address for d in targets]))
        return self.get_vacation_status()

    async def async_end_vacation(self, *, reason: str = "manual") -> dict[str, Any]:
        """Return early (or finish): restore every thermostat's previous state."""
        if not self._vacation.get("active"):
            return self.get_vacation_status()
        if self._vacation_timer_unsub is not None:
            self._vacation_timer_unsub()
            self._vacation_timer_unsub = None
        records = dict(self._vacation.get("devices") or {})
        for record in records.values():
            record.update(status="restoring", error="", updated_at=self._now_iso())
        self._vacation["active"] = False
        await self._save_devices_now()
        self._notify_vacation()
        _LOGGER.info("Vacation ended (%s): restoring %d thermostat(s)", reason, len(records))
        self._run_vacation_task(self._vacation_restore_all(records, natural=(reason == "finished")))
        return self.get_vacation_status()

    def _run_vacation_task(self, coro) -> None:
        if self._vacation_task is not None and not self._vacation_task.done():
            self._vacation_task.cancel()
        self._vacation_task = self.hass.loop.create_task(coro)

    async def _vacation_set_record(self, address: str, **values: Any) -> None:
        record = (self._vacation.get("devices") or {}).get(address)
        if record is None:
            return
        record.update(values, updated_at=self._now_iso())
        await self._save_devices()
        self._notify_vacation()

    async def _vacation_send_all(self, addresses: list[str]) -> None:
        """Send the vacation command; retry thermostats that did not confirm."""
        temperature = float(self._vacation["temperature"])
        device_end = datetime.fromisoformat(self._vacation["device_end"])
        remaining = list(addresses)
        for attempt in range(VACATION_SEND_ROUNDS):
            failed: list[str] = []
            for address in remaining:
                if not self._vacation.get("active"):
                    return
                try:
                    await self.async_set_temperature(address, temperature, until=device_end)
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001 - retried below
                    failed.append(address)
                    await self._vacation_set_record(address, status="failed", error=str(err))
                else:
                    # the ACK carries mode and target but not the until time
                    await self._merge_thermostat_state(
                        address,
                        {"mode": MODE_VACATION, "until": device_end.strftime("%Y-%m-%d %H:%M")},
                        keep_missing_measurement=True,
                    )
                    self._dispatch_state_refresh(address)
                    await self._vacation_set_record(address, status="confirmed", error="")
            if not failed:
                return
            remaining = failed
            if attempt + 1 < VACATION_SEND_ROUNDS:
                await asyncio.sleep(VACATION_RETRY_DELAY)
        _LOGGER.warning(
            "Vacation command not confirmed by: %s",
            ", ".join(self.format_device_label(a) for a in remaining),
        )

    async def _vacation_restore_all(self, records: dict[str, dict[str, Any]], *, natural: bool) -> None:
        """Bring the thermostats back to where they were before the vacation."""
        order = sorted(
            records,
            key=lambda a: (
                (self.get_device(a).device_type if self.get_device(a) else 0) != DEVICE_WALL_THERMOSTAT,
                a,
            ),
        )
        remaining = order
        for attempt in range(VACATION_SEND_ROUNDS):
            failed: list[str] = []
            for address in remaining:
                if self._vacation.get("active"):
                    return  # a new vacation started meanwhile
                record = records[address]
                device = self.get_device(address)
                if device is None:
                    continue
                state = device.last_state or {}
                prev_mode = int(record.get("prev_mode", MODE_AUTO))
                prev_temp = record.get("prev_temperature")
                still_in_vacation = state.get("mode") == MODE_VACATION
                try:
                    if prev_mode == MODE_MANUAL and prev_temp is not None:
                        if natural or still_in_vacation or state.get("mode") == MODE_AUTO:
                            await self.async_set_temperature(address, float(prev_temp), mode=MODE_MANUAL)
                    elif natural:
                        # The thermostat already switched back to its program at
                        # the until time; reflect that until it reports again.
                        if still_in_vacation:
                            await self._merge_thermostat_state(
                                address, {"mode": MODE_AUTO}, keep_missing_measurement=True
                            )
                            self._dispatch_state_refresh(address)
                    elif still_in_vacation or not state:
                        await self.async_set_temperature(address, 0.0, mode=MODE_AUTO)
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001 - retried below
                    failed.append(address)
                    record.update(status="restore_failed", error=str(err), updated_at=self._now_iso())
                else:
                    record.update(status="restored", error="", updated_at=self._now_iso())
                self._vacation["devices"] = records
                await self._save_devices()
                self._notify_vacation()
                if device.external_sensor:
                    self.hass.async_create_task(
                        self._external_temperature_tick(address, reason="vacation end")
                    )
            if not failed:
                return
            remaining = failed
            if attempt + 1 < VACATION_SEND_ROUNDS:
                await asyncio.sleep(VACATION_RETRY_DELAY)

    def _dispatch_state_refresh(self, address: str) -> None:
        """Push the stored state to the climate entity of one thermostat."""
        device = self.get_device(address)
        if device is None:
            return
        state = thermostat_state_from_dict(address, device.last_state)
        for cb in list(self._listeners.get(address, [])):
            try:
                cb(None, state)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("State refresh listener failed for %s", address)

    def _arm_vacation_timer(self) -> None:
        if self._vacation_timer_unsub is not None:
            self._vacation_timer_unsub()
            self._vacation_timer_unsub = None
        raw = self._vacation.get("device_end")
        if not self._vacation.get("active") or not raw:
            return
        try:
            device_end = datetime.fromisoformat(str(raw))
        except ValueError:
            return

        @callback
        def _finished(_now: datetime) -> None:
            self._vacation_timer_unsub = None
            self.hass.async_create_task(self.async_end_vacation(reason="finished"))

        # a little after the thermostats switched back by themselves
        self._vacation_timer_unsub = async_track_point_in_time(
            self.hass, _finished, device_end + timedelta(minutes=2)
        )

    def _resume_vacation(self) -> None:
        """After a restart: finish an expired vacation or continue a running one."""
        if not self._vacation.get("active"):
            return
        raw = self._vacation.get("device_end")
        try:
            device_end = datetime.fromisoformat(str(raw)) if raw else None
        except ValueError:
            device_end = None
        if device_end is None or device_end <= dt_util.now():
            self.hass.async_create_task(self.async_end_vacation(reason="finished"))
            return
        self._arm_vacation_timer()
        unconfirmed = [
            address for address, record in (self._vacation.get("devices") or {}).items()
            if record.get("status") != "confirmed"
        ]
        if unconfirmed:
            self._run_vacation_task(self._vacation_send_all(unconfirmed))

    # ------------------------------------------------------------------
    # Topology picture
    # ------------------------------------------------------------------

    def render_topology(self) -> str:
        """Return an SVG with rooms (HA areas), devices and their links."""
        registry = dr.async_get(self.hass)
        areas = ar.async_get(self.hass)
        nodes: list[TopologyNode] = []
        keys: set[str] = set()
        now = datetime.now(UTC)
        for device in self.get_all_devices():
            if device.superseded_by:
                continue
            if device.device_type == DEVICE_SHUTTER_CONTACT:
                kind = KIND_CONTACT
            elif device.device_type == DEVICE_WALL_THERMOSTAT:
                kind = KIND_WALL
            elif device.device_type in CLIMATE_DEVICE_TYPES:
                kind = KIND_THERMOSTAT
            else:
                continue
            entry = self.get_registry_device(registry, device.address)
            name = (entry.name_by_user or entry.name) if entry is not None else device.name
            area = areas.async_get_area(entry.area_id) if entry is not None and entry.area_id else None
            state = device.last_state or {}
            if kind == KIND_CONTACT:
                is_open = state.get("is_open")
                status = "offen" if is_open else "geschlossen" if is_open is not None else "unbekannt"
            else:
                mode = state.get("mode")
                target = state.get("desired_temperature")
                measured = state.get("measured_temperature")
                parts = []
                if mode is not None:
                    parts.append(
                        "Aus" if mode == MODE_MANUAL and target is not None and target <= 4.5
                        else {0: "Auto", 1: "Manuell", 2: "Urlaub", 3: "Boost"}.get(int(mode), "?")
                    )
                if target is not None and not (mode == MODE_MANUAL and target <= 4.5):
                    parts.append(f"{target:.1f}°".replace(".", ","))
                if measured is not None:
                    parts.append(f"ist {measured:.1f}°".replace(".", ","))
                status = " · ".join(parts)
            notes: list[str] = []
            problems: list[str] = []
            if device.external_sensor:
                sensor_state = self.hass.states.get(device.external_sensor)
                sensor_name = (
                    sensor_state.attributes.get("friendly_name", device.external_sensor)
                    if sensor_state is not None
                    else device.external_sensor
                )
                notes.append(f"Raumfühler: {sensor_name}")
            if device.foreign_central:
                problems.append(f"andere Zentrale ({device.foreign_central})")
            if not device.is_virtual and device.last_seen:
                try:
                    last_seen = datetime.fromisoformat(device.last_seen)
                except ValueError:
                    last_seen = None
                limit = STALE_TIMEOUT_SHUTTER_CONTACT if kind == KIND_CONTACT else STALE_TIMEOUT_CLIMATE
                if last_seen is not None and now - last_seen > limit:
                    problems.append(f"keine Meldung seit {(now - last_seen).days} Tagen")
            if state.get("battery_low"):
                problems.append("Batterie schwach")
            if device.pending_config:
                problems.append("Konfiguration ausstehend")
            nodes.append(
                TopologyNode(
                    key=device.address,
                    room=area.name if area is not None else "Ohne Raum",
                    kind=kind,
                    name=name,
                    status=status,
                    virtual=device.is_virtual,
                    problems=problems,
                    notes=notes,
                )
            )
            keys.add(device.address)
        edges: list[TopologyEdge] = []
        seen: set[frozenset[str]] = set()
        for device in self.get_all_devices():
            if device.address not in keys:
                continue
            for partner in device.linked_partners:
                pair = frozenset((device.address, partner.upper()))
                if partner.upper() in keys and pair not in seen and len(pair) == 2:
                    seen.add(pair)
                    edges.append(TopologyEdge(device.address, partner.upper()))
        by_key = {node.key: node for node in nodes}
        for node in nodes:
            if node.virtual and node.room == "Ohne Raum":
                partner_rooms = {
                    by_key[other].room
                    for edge in edges
                    for other in ((edge.b,) if edge.a == node.key else (edge.a,) if edge.b == node.key else ())
                    if other in by_key and by_key[other].room != "Ohne Raum"
                }
                if len(partner_rooms) == 1:
                    node.room = partner_rooms.pop()
        rooms = {node.room for node in nodes}
        title = f"MAX! Topologie · {len(nodes)} Geräte in {len(rooms)} Räumen"
        return render_topology_svg(nodes, edges, title=title)

    def _check_foreign_central(self, msg: MaxMessage, device: KnownDevice) -> None:
        """Detect devices that still report to another controller (e.g. old Cube).

        Such a device ignores configuration from this central and repeats its
        telegrams because nobody answers. It must be factory reset and paired
        again. A device that also talks to this central is only linked to an
        unknown device and is not flagged.
        """
        if device.is_virtual:
            return
        now_iso = datetime.now(UTC).isoformat()
        if msg.dst == self.own_address:
            device.last_central_contact_at = now_iso
            if device.foreign_central:
                _LOGGER.info(
                    "%s now reports to this central; clearing 'paired elsewhere' (%s)",
                    self._format_device_identity(device.address),
                    device.foreign_central,
                )
                device.foreign_central = ""
                device.foreign_central_seen_at = ""
                self._sync_foreign_central_issue(device)
                self.hass.async_create_task(self._sync_device_registry_entry(device.address))
                self._notify_diagnostics_updated(device.address)
            return
        if msg.dst == 0 or msg.msg_type not in FOREIGN_CENTRAL_MSG_TYPES:
            return
        if self.get_device(msg.dst_hex) is not None or msg.dst == self.virtual_wall_thermostat_address:
            return  # talks to a device we know (link partner / virtual WT)
        if device.last_central_contact_at:
            try:
                last = datetime.fromisoformat(device.last_central_contact_at)
            except ValueError:
                last = None
            if last is not None and datetime.now(UTC) - last < FOREIGN_CENTRAL_GRACE:
                return
        newly = device.foreign_central != msg.dst_hex
        device.foreign_central = msg.dst_hex
        device.foreign_central_seen_at = now_iso
        if newly:
            _LOGGER.warning(
                "%s reports to unknown address %s instead of this central (%06X): "
                "it is probably still paired with another controller (old MAX! Cube). "
                "Factory reset the device and pair it again.",
                self._format_device_identity(device.address),
                msg.dst_hex,
                self.own_address,
            )
            self._sync_foreign_central_issue(device)
            self.hass.async_create_task(self._sync_device_registry_entry(device.address))
            self._notify_diagnostics_updated(device.address)

    def _sync_foreign_central_issue(self, device: KnownDevice) -> None:
        """Create or remove the repair issue for a device paired elsewhere."""
        issue_id = f"paired_elsewhere_{device.address}"
        if device.foreign_central and not device.is_virtual:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="paired_elsewhere",
                translation_placeholders={
                    "name": device.name,
                    "address": device.address,
                    "central": device.foreign_central,
                    "own_address": f"{self.own_address:06X}",
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def _reply_time_information(self, address: str) -> None:
        """Answer a device's time request without blocking the read loop."""

        async def _send() -> None:
            try:
                await self.async_send_time_information(address, priority=COMMAND_PRIORITY_NORMAL)
            except Exception as err:  # noqa: BLE001 - background task
                _LOGGER.warning(
                    "TimeInformation reply to %s failed: %s",
                    self._format_device_identity(address),
                    err,
                )

        self.hass.async_create_task(_send())

    def _dispatch(self, msg: MaxMessage, decoded: Any) -> None:
        """Call all registered listeners for this message."""
        addr = msg.src_hex
        for cb in self._listeners.get(addr, []):
            self.hass.loop.call_soon(cb, msg, decoded)
        for cb in self._global_listeners:
            self.hass.loop.call_soon(cb, msg, decoded)

    def _handle_ack(self, msg: MaxMessage) -> None:
        """Resolve the pending ACK future if the incoming ACK matches."""
        pending = self._pending_ack
        if pending is None or pending.future.done():
            return
        if pending.counter != msg.counter:
            return
        if pending.expected_src and pending.expected_src != msg.src_hex:
            return
        if is_ack_nack(msg):
            pending.future.set_exception(
                DeviceNackError(
                    f"{pending.description}: device answered 'invalid command/argument' "
                    f"(0x{msg.payload[0]:02X})"
                )
            )
            return
        pending.future.set_result(msg)

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------

    async def async_start_pairing(self, duration: int = PAIRING_DURATION) -> None:
        """Enter pairing mode for the requested number of seconds."""
        if duration < 1:
            raise ValueError("Pairing-Dauer muss mindestens 1 Sekunde betragen.")
        _LOGGER.info("MAX! pairing mode active for %d seconds", duration)
        self._pairing_mode = True
        self._pairing_until = datetime.now(UTC) + timedelta(seconds=duration)
        if self._pairing_task:
            self._pairing_task.cancel()
        self._notify_pairing_state_updated()
        self._pairing_task = self.hass.loop.create_task(self._pairing_timeout(duration))

    async def _pairing_timeout(self, duration: int) -> None:
        await asyncio.sleep(duration)
        self._pairing_mode = False
        self._pairing_until = None
        _LOGGER.info("MAX! pairing mode ended")
        self._notify_pairing_state_updated()

    async def _handle_pair_ping(self, msg: MaxMessage) -> None:
        """Handle a PairPing — respond with PairPong and register the new device."""
        src = msg.src_hex
        _LOGGER.info("PairPing from new device %s (payload: %s)", src, msg.payload.hex())

        # Pairing responses must go out immediately. Running PairPong through the
        # normal serialized command queue can delay it behind config traffic and
        # cause pairing timeouts on real devices.
        counter = self._next_counter()
        cmd = build_pair_pong(counter, self.own_address, msg.src)
        await self._send_raw(cmd, priority=True)
        _LOGGER.info("Sent PairPong immediately to %s", src)

        # PairPing payload seen on real devices starts with an extra leading byte
        # before the actual device type. Older parsing treated that byte as the
        # device type, which stored bogus values like 0x10 instead of 0x03.
        if len(msg.payload) >= 12 and msg.payload[1] in DEVICE_TYPE_NAMES:
            device_type = msg.payload[1]
            firmware = 0
            serial_bytes = msg.payload[2:12]
        else:
            # Fallback for older assumptions or unexpected payload variants.
            device_type = msg.payload[0] if msg.payload else 0
            firmware = msg.payload[1] if len(msg.payload) > 1 else 0
            serial_bytes = msg.payload[2:12] if len(msg.payload) >= 12 else b""

        serial_str = _sanitize_serial_number(serial_bytes.decode("ascii", errors="ignore"))
        _LOGGER.info(
            "PairPing details: address=%s serial=%s device_type=%s firmware=%s",
            src,
            serial_str or "n/a",
            DEVICE_TYPE_NAMES.get(device_type, f"unknown:{device_type}"),
            firmware,
        )
        # Keep the read loop free for additional PairPing telegrams. Device
        # persistence, entity dispatch, and initial time sync can happen in a
        # short follow-up task after the critical PairPong has been sent.
        self.hass.loop.create_task(
            self._finalize_pair_ping(
                msg=msg,
                src=src,
                device_type=device_type,
                firmware=firmware,
                serial_str=serial_str,
            )
        )

    async def _finalize_pair_ping(
        self,
        *,
        msg: MaxMessage,
        src: str,
        device_type: int,
        firmware: int,
        serial_str: str,
    ) -> None:
        """Persist a paired device and notify listeners without blocking RX."""
        try:
            auto_name = _default_device_name(device_type, src, serial_str)
            existing_device = self.get_device(src)
            if (
                existing_device is not None
                and existing_device.name.strip()
                and not _is_legacy_auto_name(existing_device.name, device_type, src)
            ):
                name = existing_device.name
                _LOGGER.info(
                    "Preserving existing device name for %s during re-pairing: '%s'",
                    src,
                    name,
                )
            else:
                name = auto_name
            if existing_device is not None and existing_device.device_type == device_type:
                # Re-pairing a known device: keep links, group, schedule and
                # config, and keep the object entities already reference.
                device = existing_device
                device.name = name
                device.serial_number = serial_str or device.serial_number
                device.firmware_version = str(firmware)
                device.paired = True
                device.superseded_by = ""
                device.duplicate_reason = ""
                device.last_seen = datetime.now(UTC).isoformat()
                _LOGGER.info(
                    "Re-paired known device %s; keeping stored links %s and group %d",
                    src,
                    device.linked_partners,
                    device.group_id,
                )
            else:
                device = KnownDevice(
                    address=src,
                    device_type=device_type,
                    name=name,
                    serial_number=serial_str,
                    firmware_version=str(firmware),
                    paired=True,
                    last_seen=datetime.now(UTC).isoformat(),
                )
            self._devices[src] = device
            await self._ensure_time_slots_assigned()
            superseded_devices = self._mark_superseded_devices(
                new_address=src,
                serial_number=serial_str,
                name=name,
            )
            await self._save_devices()
            await self._sync_device_registry_entry(src)
            _LOGGER.info(
                "Paired: %s name='%s' type=%s serial=%s",
                self._format_device_identity(src),
                name,
                DEVICE_TYPE_NAMES.get(device_type, device_type),
                serial_str or "n/a",
            )
            if superseded_devices:
                _LOGGER.warning(
                    "Paired device %s supersedes older entries: %s",
                    self._format_device_identity(src),
                    [
                        f"{self._format_device_identity(device.address)} ({device.duplicate_reason})"
                        for device in superseded_devices
                    ],
                )

            # Notify platform listeners so they can create new entities.
            self._dispatch(msg, None)

            if device_type in CLIMATE_DEVICE_TYPES:
                await asyncio.sleep(0.5)
                await self.async_send_time_information(src)
        except Exception:
            _LOGGER.exception("Failed to finalize pairing for %s", src)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_set_temperature(
        self,
        address: str,
        temperature: float,
        mode: int = 1,  # manual
        until: datetime | None = None,
    ) -> None:
        """Send SetTemperature (0x40) to a thermostat."""
        normalized = address.upper()
        self._require_paired_for_write(normalized)
        pending_task = self._pending_climate_tasks.get(normalized)
        if self._pending_climate_config.get(normalized) or (
            pending_task is not None and not pending_task.done()
        ):
            _LOGGER.info(
                "SetTemperature for %s waits briefly for pending climate config to settle",
                self._format_device_identity(normalized),
            )
            if pending_task is not None and not pending_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(pending_task), timeout=10.0)
                except asyncio.TimeoutError:
                    _LOGGER.info(
                        "Pending climate config for %s still active; proceeding with SetTemperature anyway",
                        self._format_device_identity(normalized),
                    )

        dst = int(address, 16)
        label = self.format_device_label(address)
        counter = self._next_counter()
        effective_mode = MODE_VACATION if until is not None else mode
        until_hex = encode_max_until_datetime(until) if until is not None else ""
        device = self.get_device(normalized)
        payload_group_id = device.group_id if device is not None else 0
        cmd = build_set_temperature(
            counter,
            self.own_address,
            dst,
            temperature,
            effective_mode,
            until_hex=until_hex,
            group_id=payload_group_id,
        )
        _LOGGER.debug(
            "SetTemperature → %s: %.1f°C mode=%d until=%s",
            label,
            temperature,
            effective_mode,
            until.isoformat() if until is not None else "-",
        )
        command_label = f"SetTemperature {temperature:.1f} mode={MODE_NAMES.get(effective_mode, effective_mode)}"
        if until is not None:
            command_label += f" until={until.strftime('%Y-%m-%d %H:%M')}"
        await self._set_last_command(address, command_label)
        await self._send_command(
            cmd,
            expected_src=address,
            device_address=address,
            counter=counter,
            description=f"SetTemperature {label}",
            retries=self._send_profile.set_temperature_retries,
            timeout=self._send_profile.set_temperature_timeout,
            priority=COMMAND_PRIORITY_HIGH,
        )
        if effective_mode == MODE_AUTO and temperature <= 0 and until is None:
            self._schedule_auto_mode_time_sync_followup(normalized)

    async def _async_send_temperature_config(
        self,
        address: str,
        *,
        comfort_temperature: float | None = None,
        eco_temperature: float | None = None,
        window_open_temperature: float | None = None,
        window_open_duration: int | None = None,
        measurement_offset: float | None = None,
    ) -> None:
        """Send one combined ConfigTemperatures command and persist the values."""
        device = self.get_device(address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if device.device_type not in CLIMATE_DEVICE_TYPES:
            raise ValueError(f"Geraet {address} unterstuetzt keine Temperatur-Konfiguration.")
        self._require_paired_for_write(address)

        comfort = (
            float(comfort_temperature)
            if comfort_temperature is not None
            else device.comfort_temperature
        )
        eco = float(eco_temperature) if eco_temperature is not None else device.eco_temperature
        window_open = (
            float(window_open_temperature)
            if window_open_temperature is not None
            else device.window_open_temperature
        )
        window_duration = (
            int(window_open_duration)
            if window_open_duration is not None
            else device.window_open_duration
        )
        offset = (
            float(measurement_offset)
            if measurement_offset is not None
            else device.measurement_offset
        )
        payload_group_id = device.group_id
        if (
            measurement_offset is not None
            and comfort_temperature is None
            and eco_temperature is None
            and window_open_temperature is None
            and window_open_duration is None
        ):
            payload_group_id = 0

        await self._prepare_device_for_config(address)
        counter = self._next_counter()
        label = self.format_device_label(address)
        cmd = build_config_temperatures(
            counter,
            self.own_address,
            int(address, 16),
            comfort_temperature=comfort,
            eco_temperature=eco,
            maximum_temperature=device.maximum_temperature,
            minimum_temperature=device.minimum_temperature,
            measurement_offset=offset,
            window_open_temperature=window_open,
            window_open_duration=window_duration,
            group_id=payload_group_id,
        )
        summary_bits: list[str] = []
        if comfort_temperature is not None:
            summary_bits.append(f"comfort={comfort:.1f}")
        if eco_temperature is not None:
            summary_bits.append(f"eco={eco:.1f}")
        if window_open_temperature is not None:
            summary_bits.append(f"window_open={window_open:.1f}")
        if window_open_duration is not None:
            summary_bits.append(f"window_open_duration={window_duration}")
        if measurement_offset is not None:
            summary_bits.append(f"measurement_offset={offset:.1f}")
        summary = ", ".join(summary_bits) or "ConfigTemperatures"
        _LOGGER.info("ConfigTemperatures → %s: %s", label, summary)
        await self._set_last_command(address, f"ConfigTemperatures {summary}")
        await self._send_command(
            cmd,
            expected_src=address,
            device_address=address,
            counter=counter,
            description=f"ConfigTemperatures {label}",
            retries=self._send_profile.config_retries,
            timeout=CONFIG_ACK_TIMEOUT,
        )

        device.comfort_temperature = comfort
        device.eco_temperature = eco
        device.window_open_temperature = window_open
        device.window_open_duration = window_duration
        device.measurement_offset = offset
        await self._save_devices()
        self._notify_diagnostics_updated(address)

    async def async_set_comfort_temperature(self, address: str, temperature: float) -> None:
        """Write the comfort/day temperature into one thermostat."""
        await self._async_send_temperature_config(address, comfort_temperature=temperature)

    async def async_set_eco_temperature(self, address: str, temperature: float) -> None:
        """Write the eco/night temperature into one thermostat."""
        await self._async_send_temperature_config(address, eco_temperature=temperature)

    async def async_set_window_open_temperature(self, address: str, temperature: float) -> None:
        """Write the window-open temperature into one thermostat."""
        await self._async_send_temperature_config(address, window_open_temperature=temperature)

    async def async_set_window_open_duration(self, address: str, duration: int) -> None:
        """Write the window-open duration into one thermostat."""
        await self._async_send_temperature_config(address, window_open_duration=duration)

    async def _prepare_device_for_config(self, address: str) -> None:
        """Prepare a climate device for config writes.

        FHEM does not send an automatic WakeUp before normal config telegrams
        such as SetGroupId/AddLinkPartner/ConfigTemperatures. In practice this
        extra WakeUp can delay or destabilize writes on some thermostats even
        though state updates are still received normally. Keep the hook for
        future tweaks, but default to the conservative no-op behavior.
        """
        device = self.get_device(address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if device.device_type in CLIMATE_DEVICE_TYPES:
            _LOGGER.debug(
                "Skipping automatic WakeUp before config write for %s",
                self._format_device_identity(address),
            )

    async def _sync_pending_config_reading(self, address: str) -> None:
        """Mirror queued shutter-contact config into the persistent device record."""
        device = self.get_device(address)
        if device is None:
            return
        pending_descriptions = [
            command.description
            for command in self._pending_shutter_config.get(address.upper(), [])
        ]
        pending_descriptions.extend(
            command.description
            for command in self._pending_climate_config.get(address.upper(), [])
        )
        device.pending_config = pending_descriptions
        await self._save_devices()
        self._notify_diagnostics_updated(address)

    def _now_iso(self) -> str:
        """Return the current UTC timestamp as ISO string."""
        return datetime.now(UTC).isoformat()

    def _pending_retry_delay(self, attempts: int) -> float:
        """Return a conservative retry delay for queued config commands."""
        exponent = max(0, attempts - 1)
        profile = self._send_profile
        return min(
            profile.pending_retry_max_delay,
            profile.pending_retry_base_delay * (2 ** exponent),
        )

    def _mark_pending_attempt(
        self,
        command: PendingShutterCommand | PendingClimateCommand,
    ) -> None:
        """Update metadata before one pending command is sent."""
        command.attempts += 1
        command.last_attempt_at = self._now_iso()
        command.last_error = ""
        command.last_error_at = ""
        command.next_attempt_at = ""

    def _mark_pending_failure(
        self,
        command: PendingShutterCommand | PendingClimateCommand,
        err: Exception,
    ) -> None:
        """Update metadata after one pending command failed."""
        command.last_error = str(err)
        command.last_error_at = self._now_iso()
        retry_at = datetime.now(UTC) + timedelta(seconds=self._pending_retry_delay(command.attempts))
        command.next_attempt_at = retry_at.isoformat()

    def _pending_due(
        self,
        command: PendingShutterCommand | PendingClimateCommand,
    ) -> bool:
        """Return whether the queued command may be retried now."""
        if not command.next_attempt_at:
            return True
        try:
            return datetime.fromisoformat(command.next_attempt_at) <= datetime.now(UTC)
        except ValueError:
            return True

    def _is_recently_seen(self, address: str, *, within_seconds: int = 30) -> bool:
        """Return whether a device was seen recently enough for follow-up delivery."""
        device = self.get_device(address)
        if device is None or not device.last_seen:
            return False
        try:
            last_seen = datetime.fromisoformat(device.last_seen)
        except ValueError:
            return False
        return last_seen >= datetime.now(UTC) - timedelta(seconds=within_seconds)

    def _pending_shutter_command_exists(self, address: str, command: PendingShutterCommand) -> bool:
        """Return whether an equivalent pending shutter command is already queued."""
        normalized = address.upper()
        for item in self._pending_shutter_config.get(normalized, []):
            if item.op != command.op:
                continue
            if command.op in {"set_group_id", "remove_group_id"}:
                if item.group_id == command.group_id:
                    return True
                continue
            if item.partner_address == command.partner_address:
                return True
        return False

    def get_pending_queue_details(self, address: str) -> dict[str, Any]:
        """Return one consolidated diagnostic snapshot for the pending queue."""
        normalized = address.upper()
        shutter_queue = self._pending_shutter_config.get(normalized, [])
        climate_queue = self._pending_climate_config.get(normalized, [])
        queue_type = "shutter" if shutter_queue else "climate" if climate_queue else None
        queue: list[PendingShutterCommand | PendingClimateCommand] = shutter_queue or climate_queue
        head = queue[0] if queue else None
        active_task = (
            self._pending_shutter_tasks.get(normalized)
            if queue_type == "shutter"
            else self._pending_climate_tasks.get(normalized)
            if queue_type == "climate"
            else None
        )
        return {
            "pending_queue_type": queue_type,
            "pending_queue_length": len(queue),
            "pending_queue_active": bool(active_task and not active_task.done()),
            "pending_queue_current": head.description if head else None,
            "pending_queue_attempts": head.attempts if head else 0,
            "pending_queue_last_attempt_at": head.last_attempt_at or None if head else None,
            "pending_queue_next_attempt_at": head.next_attempt_at or None if head else None,
            "pending_queue_last_error": head.last_error or None if head else None,
            "pending_queue_last_error_at": head.last_error_at or None if head else None,
            "pending_queue_queued_at": head.queued_at or None if head else None,
        }

    async def _set_last_command(self, address: str, command: str) -> None:
        """Persist the last queued or executed command label for a device."""
        device = self._devices.get(address.upper())
        if device is None:
            return
        if device.last_command == command:
            return
        device.last_command = command
        await self._save_devices()
        self._notify_diagnostics_updated(address)

    async def _enqueue_shutter_command(
        self,
        address: str,
        command: PendingShutterCommand,
    ) -> None:
        """Queue one deferred config command for a shutter contact."""
        normalized = address.upper()
        queue = self._pending_shutter_config.setdefault(normalized, [])
        if command.op in {"set_group_id", "remove_group_id"}:
            queue[:] = [item for item in queue if item.op not in {"set_group_id", "remove_group_id"}]
        elif command.partner_address:
            queue[:] = [
                item
                for item in queue
                if not (item.op == command.op and item.partner_address == command.partner_address)
            ]
        if not command.queued_at:
            command.queued_at = self._now_iso()
        queue.append(command)
        _LOGGER.info(
            "Queued pending shutter-contact config for %s: %s",
            self._format_device_identity(normalized),
            command.description,
        )
        await self._set_last_command(normalized, command.description)
        await self._sync_pending_config_reading(normalized)
        if self._is_recently_seen(normalized):
            self._schedule_shutter_config_processing(normalized, trigger="recent_activity")

    def _schedule_shutter_config_processing(self, address: str, *, trigger: str) -> None:
        """Schedule delivery of queued config to one shutter contact after activity."""
        normalized = address.upper()
        if not self._pending_shutter_config.get(normalized):
            return
        existing = self._pending_shutter_tasks.get(normalized)
        if existing and not existing.done():
            return
        _LOGGER.info(
            "Scheduling pending config delivery for %s due to %s",
            self._format_device_identity(normalized),
            trigger,
        )
        self._pending_shutter_tasks[normalized] = self.hass.loop.create_task(
            self._process_shutter_config_queue(normalized, trigger=trigger)
        )

    async def _process_shutter_config_queue(self, address: str, *, trigger: str) -> None:
        """Try to deliver pending config commands to one shutter contact."""
        normalized = address.upper()
        try:
            await asyncio.sleep(0.1)
            while self._pending_shutter_config.get(normalized):
                command = self._pending_shutter_config[normalized][0]
                if not self._pending_due(command):
                    break
                try:
                    self._mark_pending_attempt(command)
                    await self._send_shutter_pending_command(normalized, command, trigger=trigger)
                except Exception as err:
                    self._mark_pending_failure(command, err)
                    await self._sync_pending_config_reading(normalized)
                    _LOGGER.warning(
                        "Pending shutter-contact config for %s not delivered yet (%s): %s: %s",
                        self._format_device_identity(normalized),
                        command.description,
                        err.__class__.__name__,
                        err,
                    )
                    break
                self._pending_shutter_config[normalized].pop(0)
                if not self._pending_shutter_config[normalized]:
                    del self._pending_shutter_config[normalized]
                await self._sync_pending_config_reading(normalized)
                await asyncio.sleep(0.15)
        finally:
            self._pending_shutter_tasks.pop(normalized, None)

    async def _send_shutter_pending_command(
        self,
        address: str,
        command: PendingShutterCommand,
        *,
        trigger: str,
    ) -> None:
        """Deliver one queued shutter-contact config command inside an activity window."""
        device = self.get_device(address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        counter = self._next_counter()
        if command.op == "set_group_id":
            assert command.group_id is not None
            cmd = build_set_group_id(counter, self.own_address, int(address, 16), command.group_id)
        elif command.op == "remove_group_id":
            cmd = build_remove_group_id(counter, self.own_address, int(address, 16))
        elif command.op == "add_link_partner":
            assert command.partner_address is not None
            partner = self.get_device(command.partner_address)
            if partner is None:
                raise ValueError(f"Unbekannte Partneradresse {command.partner_address}")
            cmd = build_add_link_partner(
                counter,
                self.own_address,
                int(address, 16),
                int(command.partner_address, 16),
                partner.device_type,
            )
        elif command.op == "remove_link_partner":
            assert command.partner_address is not None
            partner = self.get_device(command.partner_address)
            if partner is not None:
                partner_type = partner.device_type
            elif command.partner_type is not None:
                partner_type = command.partner_type  # stale link to an unknown device
            else:
                raise ValueError(f"Unbekannte Partneradresse {command.partner_address}")
            cmd = build_remove_link_partner(
                counter,
                self.own_address,
                int(address, 16),
                int(command.partner_address, 16),
                partner_type,
            )
        else:
            raise ValueError(f"Unbekannte pending shutter command {command.op}")

        _LOGGER.info(
            "Delivering pending config to %s after %s: %s",
            self._format_device_identity(address),
            trigger,
            command.description,
        )
        try:
            await self._send_command(
                cmd,
                expected_src=address,
                device_address=address,
                counter=counter,
                description=f"{command.description} [pending]",
                retries=0,
                timeout=2.0,
            )
        except ConnectionError as err:
            # Real shutter contacts often apply config inside their short wake/activity
            # window without giving us a clean ACK that matches our tracking.
            if "No ACK for" not in str(err):
                raise
            _LOGGER.warning(
                "No ACK from shutter contact %s for pending command, but treating it as delivered "
                "because it was sent inside an activity window after %s: %s",
                self._format_device_identity(address),
                trigger,
                command.description,
            )
            await self._mark_command_success(address, retries=0, ack_at=None)
        if command.op == "set_group_id" and command.group_id is not None:
            device.group_id = command.group_id
        elif command.op == "remove_group_id":
            device.group_id = 0
        elif command.op == "add_link_partner" and command.partner_address:
            if command.partner_address not in device.linked_partners:
                device.linked_partners.append(command.partner_address)
                device.linked_partners.sort()
        elif command.op == "remove_link_partner" and command.partner_address:
            if command.partner_address in device.linked_partners:
                device.linked_partners.remove(command.partner_address)
        await self._save_devices()
        _LOGGER.info(
            "Pending config applied to %s: %s",
            self._format_device_identity(address),
            command.description,
        )

    async def _replace_pending_climate_commands(
        self,
        address: str,
        commands: list[PendingClimateCommand],
    ) -> None:
        """Replace queued climate-config commands for one device."""
        normalized = address.upper()
        now_iso = self._now_iso()
        for command in commands:
            if not command.queued_at:
                command.queued_at = now_iso
        self._pending_climate_config[normalized] = commands
        if commands:
            _LOGGER.info(
                "Queued %d pending climate-config commands for %s",
                len(commands),
                self._format_device_identity(normalized),
            )
            await self._set_last_command(normalized, commands[0].description)
        await self._sync_pending_config_reading(normalized)

    def _schedule_climate_config_processing(self, address: str, *, trigger: str) -> None:
        """Schedule delivery of queued climate config after device activity."""
        normalized = address.upper()
        if not self._pending_climate_config.get(normalized):
            return
        existing = self._pending_climate_tasks.get(normalized)
        if existing and not existing.done():
            return
        _LOGGER.info(
            "Scheduling pending climate config delivery for %s due to %s",
            self._format_device_identity(normalized),
            trigger,
        )
        self._pending_climate_tasks[normalized] = self.hass.loop.create_task(
            self._process_climate_config_queue(normalized, trigger=trigger)
        )

    async def _process_climate_config_queue(self, address: str, *, trigger: str) -> None:
        """Try to deliver queued climate config commands one by one."""
        normalized = address.upper()
        current_task = asyncio.current_task()
        existing = self._pending_climate_tasks.get(normalized)
        if existing is not None and existing is not current_task and not existing.done():
            await existing
            return

        owns_task = existing is current_task
        if not owns_task and current_task is not None:
            self._pending_climate_tasks[normalized] = current_task
            owns_task = True
        queue_drained = False
        try:
            await asyncio.sleep(0.1)
            while self._pending_climate_config.get(normalized):
                queue = self._pending_climate_config.get(normalized)
                if not queue:
                    break
                command = queue[0]
                if not self._pending_due(command):
                    break
                try:
                    self._mark_pending_attempt(command)
                    await self._send_climate_pending_command(normalized, command, trigger=trigger)
                except Exception as err:
                    self._mark_pending_failure(command, err)
                    await self._sync_pending_config_reading(normalized)
                    _LOGGER.warning(
                        "Pending climate config for %s not delivered yet (%s): %s: %s",
                        self._format_device_identity(normalized),
                        command.description,
                        err.__class__.__name__,
                        err,
                    )
                    break
                queue = self._pending_climate_config.get(normalized)
                if not queue:
                    break
                if queue and queue[0] == command:
                    queue.pop(0)
                else:
                    # The queue was replaced while this command was in flight.
                    # Leave reconciliation to the newer queue contents.
                    break
                if not queue:
                    self._pending_climate_config.pop(normalized, None)
                    queue_drained = True
                await self._sync_pending_config_reading(normalized)
                await asyncio.sleep(WEEK_PROFILE_PART_DELAY)
        finally:
            if owns_task:
                self._pending_climate_tasks.pop(normalized, None)
        if queue_drained and not self._pending_climate_config.get(normalized):
            await self._maybe_sync_time_after_climate_config(normalized, reason=trigger)

    async def _pending_queue_maintenance_loop(self) -> None:
        """Keep pending config queues alive and retry due climate items."""
        try:
            await asyncio.sleep(45)
            while True:
                try:
                    await self._run_pending_queue_maintenance()
                except Exception:
                    _LOGGER.exception("Pending MAX! queue maintenance failed")
                await asyncio.sleep(PENDING_QUEUE_MAINTENANCE_INTERVAL)
        except asyncio.CancelledError:
            return

    async def _run_pending_queue_maintenance(self) -> None:
        """Retry due queued climate config in the background."""
        if self._writer is None:
            return
        await self._refresh_virtual_contacts()
        for device in list(self._devices.values()):
            if device.external_sensor:
                await self._external_temperature_tick(device.address, reason="periodic")
        if self.hass.loop.time() - self._cul_credit_reported_at >= CUL_CREDIT_POLL_INTERVAL:
            # Keeps the budget sensor current and feeds the recovery-rate
            # measurement; "X" does not use the radio.
            await self._query_cul_credit(force=True)
        for address, queue in list(self._pending_climate_config.items()):
            if not queue:
                continue
            current = queue[0]
            if not self._pending_due(current):
                continue
            task = self._pending_climate_tasks.get(address)
            if task and not task.done():
                continue
            _LOGGER.info(
                "Retrying pending climate queue for %s in background: %s",
                self._format_device_identity(address),
                current.description,
            )
            self._schedule_climate_config_processing(address, trigger="background_retry")

    async def _send_climate_pending_command(
        self,
        address: str,
        command: PendingClimateCommand,
        *,
        trigger: str,
    ) -> None:
        """Deliver one queued climate config command."""
        if command.op != "config_week_profile":
            raise ValueError(f"Unbekannter pending climate command {command.op}")

        counter = self._next_counter()
        cmd = build_config_week_profile(
            counter,
            self.own_address,
            int(address, 16),
            int(command.day or 0),
            int(command.part or 0),
            command.chunk_hex,
        )
        _LOGGER.info(
            "Delivering pending climate config to %s after %s: %s",
            self._format_device_identity(address),
            trigger,
            command.description,
        )
        await self._set_last_command(address, command.description)
        await self._send_command(
            cmd,
            expected_src=address,
            device_address=address,
            counter=counter,
            description=f"{command.description} [pending]",
            retries=self._send_profile.week_profile_retries,
            timeout=WEEK_PROFILE_ACK_TIMEOUT,
        )
        device = self.get_device(address)
        if device is not None and command.profile_hex:
            device.week_profile = command.profile_hex
            await self._save_devices()
            self._notify_week_profile_updated(address)
        _LOGGER.info(
            "Pending climate config applied to %s: %s",
            self._format_device_identity(address),
            command.description,
        )

    async def async_create_virtual_shutter_contact(
        self,
        address: str,
        name: str,
        group_id: int = 0,
    ) -> None:
        """Create a persisted virtual MAX! shutter contact."""
        normalized = address.upper()
        if len(normalized) != 6 or any(ch not in "0123456789ABCDEF" for ch in normalized):
            raise ValueError("Adresse muss 6-stellig hexadezimal sein.")
        existing = self.get_device(normalized)
        if existing is not None:
            raise ValueError(f"Geraeteadresse {normalized} existiert bereits.")

        device = KnownDevice(
            address=normalized,
            device_type=DEVICE_SHUTTER_CONTACT,
            name=name,
            is_virtual=True,
            paired=True,
            group_id=group_id,
            last_state={"is_open": False, "battery_low": False, "rf_error": False},
        )
        self._devices[normalized] = device
        await self._save_devices()
        _LOGGER.info(
            "Created virtual shutter contact %s with group_id=%d",
            self._format_device_identity(normalized),
            group_id,
        )
        self._dispatch(
            MaxMessage(
                raw="",
                length=0,
                counter=self._counter,
                flags=0x06,
                msg_type=0x30,
                src=int(normalized, 16),
                dst=self.own_address,
                group=group_id,
                payload=bytes.fromhex("10"),
            ),
            ShutterContactState(
                address=normalized,
                is_open=False,
                battery_low=False,
                rf_error=False,
            ),
        )

    async def async_delete_virtual_device(self, address: str) -> None:
        """Delete a persisted virtual MAX! device."""
        device = self.get_device(address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if not device.is_virtual:
            raise ValueError(f"Geraet {address} ist kein virtuelles Geraet.")
        del self._devices[address.upper()]
        await self._save_devices()
        _LOGGER.info("Deleted virtual device %s", self._format_device_identity(address))

    def _virtual_contact_targets(self, device: KnownDevice) -> list[KnownDevice]:
        """Return the linked thermostats a virtual contact reports to."""
        targets: list[KnownDevice] = []
        for partner_address in device.linked_partners:
            partner = self.get_device(partner_address)
            if partner is not None and partner.device_type in CLIMATE_DEVICE_TYPES:
                targets.append(partner)
        return targets

    async def async_send_virtual_shutter_contact_state(
        self,
        address: str,
        is_open: bool,
        *,
        reason: str = "state change",
    ) -> bool:
        """Report a virtual window contact's state like a real MAX! contact.

        The ShutterContactState goes directly to every linked thermostat (with
        the thermostat's group, like FHEM's fakeSC) and must be ACKed by it.
        The ACK carries the thermostat's new state, so the result is visible
        at once. Without linked thermostats the old broadcast to the central
        is used. Returns True when every target confirmed.
        """
        normalized = address.upper()
        device = self.get_device(normalized)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if not device.is_virtual or device.device_type != DEVICE_SHUTTER_CONTACT:
            raise ValueError(f"Geraet {address} ist kein virtueller Fensterkontakt.")

        lock = self._virtual_contact_locks.setdefault(normalized, asyncio.Lock())
        async with lock:
            # Keep the contact entity in step with the requested state at once.
            await self._update_device_state(
                normalized,
                {"is_open": is_open, "battery_low": False, "rf_error": False},
            )
            await self._touch_device(normalized)
            state_text = "open" if is_open else "closed"
            await self._set_last_command(normalized, f"VirtualShutterContactState {state_text}")
            self._dispatch_virtual_contact_state(device, is_open)

            targets = self._virtual_contact_targets(device)
            if not targets:
                return await self._broadcast_virtual_contact_state(device, is_open)

            confirmed = True
            for target in targets:
                counter = self._next_counter()
                cmd = build_shutter_contact_state(
                    counter,
                    int(normalized, 16),
                    int(target.address, 16),
                    is_open,
                    target.group_id,
                )
                description = (
                    f"VirtualShutterContactState {state_text} "
                    f"{self.format_device_label(normalized)} -> {self.format_device_label(target.address)}"
                )
                _LOGGER.info("%s (%s)", description, reason)
                try:
                    await self._send_command(
                        cmd,
                        expected_src=target.address,
                        device_address=normalized,
                        counter=counter,
                        description=description,
                        retries=self._send_profile.set_temperature_retries,
                        timeout=self._send_profile.set_temperature_timeout,
                        priority=COMMAND_PRIORITY_HIGH,
                    )
                except Exception as err:  # noqa: BLE001 - retried in background
                    confirmed = False
                    _LOGGER.warning(
                        "%s not confirmed (%s); will retry in the background",
                        description,
                        err,
                    )
            self._virtual_contact_sent_at[normalized] = self.hass.loop.time()
            self._virtual_contact_confirmed[normalized] = confirmed
            if confirmed:
                self._virtual_contact_failures.pop(normalized, None)
            else:
                self._virtual_contact_failures[normalized] = (
                    self._virtual_contact_failures.get(normalized, 0) + 1
                )
            return confirmed

    async def _broadcast_virtual_contact_state(self, device: KnownDevice, is_open: bool) -> bool:
        """Legacy path for virtual contacts without linked thermostats."""
        counter = self._next_counter()
        cmd = build_shutter_contact_state(
            counter,
            int(device.address, 16),
            self.own_address,
            is_open,
            device.group_id,
        )
        _LOGGER.info(
            "VirtualShutterContactState broadcast → %s: is_open=%s group_id=%d (no linked thermostat)",
            self.format_device_label(device.address),
            is_open,
            device.group_id,
        )
        try:
            await self._send_raw(cmd, priority=True)
            await self._mark_command_success(device.address, retries=0, ack_at=None)
        except Exception as err:
            await self._mark_command_error(device.address, str(err), retries=0)
            raise
        self._virtual_contact_sent_at[device.address] = self.hass.loop.time()
        self._virtual_contact_confirmed[device.address] = True
        return True

    def _dispatch_virtual_contact_state(self, device: KnownDevice, is_open: bool) -> None:
        """Notify the virtual contact's entities about its new state."""
        self._dispatch(
            MaxMessage(
                raw="",
                length=11,
                counter=0,
                flags=0x06,
                msg_type=0x30,
                src=int(device.address, 16),
                dst=self.own_address,
                group=device.group_id,
                payload=bytes.fromhex("12" if is_open else "10"),
            ),
            ShutterContactState(
                address=device.address.upper(),
                is_open=is_open,
                battery_low=False,
                rf_error=False,
            ),
        )

    async def _refresh_virtual_contacts(self) -> None:
        """Re-send virtual contact states that are due (heartbeat / retry)."""
        now = self.hass.loop.time()
        if now < self._virtual_contact_refresh_after:
            return
        for device in self.get_all_devices():
            if not device.is_virtual or device.device_type != DEVICE_SHUTTER_CONTACT:
                continue
            if not self._virtual_contact_targets(device):
                continue
            is_open = (device.last_state or {}).get("is_open")
            if is_open is None:
                continue
            sent_at = self._virtual_contact_sent_at.get(device.address)
            confirmed = self._virtual_contact_confirmed.get(device.address, False)
            if sent_at is not None:
                age = now - sent_at
                if confirmed and age < VIRTUAL_CONTACT_REFRESH_INTERVAL:
                    continue
                failures = max(1, self._virtual_contact_failures.get(device.address, 1))
                retry_delay = min(
                    VIRTUAL_CONTACT_REFRESH_INTERVAL,
                    VIRTUAL_CONTACT_RETRY_DELAY * (2 ** (failures - 1)),
                )
                if not confirmed and age < retry_delay:
                    continue
            lock = self._virtual_contact_locks.get(device.address)
            if lock is not None and lock.locked():
                continue
            reason = "retry" if sent_at is not None and not confirmed else "refresh"
            try:
                await self.async_send_virtual_shutter_contact_state(
                    device.address, bool(is_open), reason=reason
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Virtual contact refresh for %s failed",
                    self._format_device_identity(device.address),
                )

    async def async_set_group_id(self, address: str, group_id: int) -> None:
        """Assign a MAX! group ID to one device."""
        device = self.get_device(address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        self._require_paired_for_write(address)

        if device.is_virtual:
            device.group_id = group_id
            await self._set_last_command(address, f"SetGroupId {group_id} [virtual]")
            await self._mark_command_success(address, retries=0, ack_at=None)
            await self._save_devices()
            _LOGGER.info("SetGroupId → %s: %d (virtual/local only)", self.format_device_label(address), group_id)
            return

        if device.device_type == DEVICE_SHUTTER_CONTACT and not device.is_virtual:
            await self._enqueue_shutter_command(
                address,
                PendingShutterCommand(
                    op="set_group_id",
                    description=f"SetGroupId {self.format_device_label(address)} -> {group_id}",
                    group_id=group_id,
                ),
            )
            return

        if not device.is_virtual:
            await self._prepare_device_for_config(address)
            counter = self._next_counter()
            label = self.format_device_label(address)
            cmd = build_set_group_id(counter, self.own_address, int(address, 16), group_id)
            _LOGGER.info("SetGroupId → %s: %d", label, group_id)
            await self._set_last_command(address, f"SetGroupId {group_id}")
            await self._send_command(
                cmd,
                expected_src=address,
                device_address=address,
                counter=counter,
                description=f"SetGroupId {label}",
                retries=self._send_profile.config_retries,
                timeout=CONFIG_ACK_TIMEOUT,
            )
        device.group_id = group_id
        await self._save_devices()

    async def async_remove_group_id(self, address: str) -> None:
        """Remove a MAX! group ID from one device."""
        device = self.get_device(address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        self._require_paired_for_write(address)

        if device.is_virtual:
            device.group_id = 0
            await self._set_last_command(address, "RemoveGroupId [virtual]")
            await self._mark_command_success(address, retries=0, ack_at=None)
            await self._save_devices()
            _LOGGER.info("RemoveGroupId → %s (virtual/local only)", self.format_device_label(address))
            return

        if device.device_type == DEVICE_SHUTTER_CONTACT and not device.is_virtual:
            await self._enqueue_shutter_command(
                address,
                PendingShutterCommand(
                    op="remove_group_id",
                    description=f"RemoveGroupId {self.format_device_label(address)}",
                ),
            )
            return

        if not device.is_virtual:
            await self._prepare_device_for_config(address)
            counter = self._next_counter()
            label = self.format_device_label(address)
            cmd = build_remove_group_id(counter, self.own_address, int(address, 16))
            _LOGGER.info("RemoveGroupId → %s", label)
            await self._set_last_command(address, "RemoveGroupId")
            await self._send_command(
                cmd,
                expected_src=address,
                device_address=address,
                counter=counter,
                description=f"RemoveGroupId {label}",
                retries=self._send_profile.config_retries,
                timeout=CONFIG_ACK_TIMEOUT,
            )
        device.group_id = 0
        await self._save_devices()

    async def async_add_link_partner(self, address: str, partner_address: str) -> None:
        """Link one MAX! device to another device on-device."""
        device = self.get_device(address)
        partner = self.get_device(partner_address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if partner is None:
            raise ValueError(f"Unbekannte Partneradresse {partner_address}")
        self._require_paired_for_write(address)
        self._require_paired_for_write(partner_address)
        self._validate_link_supported(address, partner_address)

        if device.is_virtual:
            if partner_address not in device.linked_partners:
                device.linked_partners.append(partner_address)
                device.linked_partners.sort()
            await self._set_last_command(address, f"AddLinkPartner {self.format_device_label(partner_address)} [virtual]")
            await self._mark_command_success(address, retries=0, ack_at=None)
            await self._save_devices()
            _LOGGER.info(
                "AddLinkPartner → %s: partner=%s (virtual/local only)",
                self.format_device_label(address),
                self.format_device_label(partner_address),
            )
            return

        if device.device_type == DEVICE_SHUTTER_CONTACT and not device.is_virtual:
            await self._enqueue_shutter_command(
                address,
                PendingShutterCommand(
                    op="add_link_partner",
                    description=(
                        f"AddLinkPartner {self.format_device_label(address)} -> "
                        f"{self.format_device_label(partner_address)}"
                    ),
                    partner_address=partner_address.upper(),
                ),
            )
            return

        await self._prepare_device_for_config(address)
        counter = self._next_counter()
        label = self.format_device_label(address)
        partner_label = self.format_device_label(partner_address)
        cmd = build_add_link_partner(
            counter,
            self.own_address,
            int(address, 16),
            int(partner_address, 16),
            partner.device_type,
        )
        _LOGGER.info(
            "AddLinkPartner → %s: partner=%s type=%d",
            label,
            partner_label,
            partner.device_type,
        )
        await self._set_last_command(address, f"AddLinkPartner {partner_label}")
        await self._send_command(
            cmd,
            expected_src=address,
            device_address=address,
            counter=counter,
            description=f"AddLinkPartner {label}",
            retries=self._send_profile.config_retries,
            timeout=CONFIG_ACK_TIMEOUT,
        )

        if partner_address not in device.linked_partners:
            device.linked_partners.append(partner_address)
            device.linked_partners.sort()
            await self._save_devices()

    async def async_remove_link_partner(
        self,
        address: str,
        partner_address: str,
        *,
        partner_type: int | None = None,
    ) -> None:
        """Remove an on-device link between two MAX! devices.

        partner_type allows removing a stale link to a device this integration
        does not know (e.g. a replaced thermostat a window contact still
        reports to).
        """
        device = self.get_device(address)
        partner = self.get_device(partner_address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if partner is None:
            if partner_type is None:
                raise ValueError(
                    f"Unbekannte Partneradresse {partner_address}. "
                    "Fuer eine veraltete Verknuepfung zu einem unbekannten Geraet bitte partner_type angeben."
                )
            return await self._remove_stale_link_partner(address, partner_address.upper(), partner_type)
        self._require_paired_for_write(address)
        self._require_paired_for_write(partner_address)
        self._validate_link_supported(address, partner_address)

        if device.is_virtual:
            if partner_address in device.linked_partners:
                device.linked_partners.remove(partner_address)
            await self._set_last_command(address, f"RemoveLinkPartner {self.format_device_label(partner_address)} [virtual]")
            await self._mark_command_success(address, retries=0, ack_at=None)
            await self._save_devices()
            _LOGGER.info(
                "RemoveLinkPartner → %s: partner=%s (virtual/local only)",
                self.format_device_label(address),
                self.format_device_label(partner_address),
            )
            return

        if device.device_type == DEVICE_SHUTTER_CONTACT and not device.is_virtual:
            await self._enqueue_shutter_command(
                address,
                PendingShutterCommand(
                    op="remove_link_partner",
                    description=(
                        f"RemoveLinkPartner {self.format_device_label(address)} -> "
                        f"{self.format_device_label(partner_address)}"
                    ),
                    partner_address=partner_address.upper(),
                ),
            )
            return

        await self._prepare_device_for_config(address)
        counter = self._next_counter()
        label = self.format_device_label(address)
        partner_label = self.format_device_label(partner_address)
        cmd = build_remove_link_partner(
            counter,
            self.own_address,
            int(address, 16),
            int(partner_address, 16),
            partner.device_type,
        )
        _LOGGER.info(
            "RemoveLinkPartner → %s: partner=%s type=%d",
            label,
            partner_label,
            partner.device_type,
        )
        await self._set_last_command(address, f"RemoveLinkPartner {partner_label}")
        await self._send_command(
            cmd,
            expected_src=address,
            device_address=address,
            counter=counter,
            description=f"RemoveLinkPartner {label}",
            retries=self._send_profile.config_retries,
            timeout=CONFIG_ACK_TIMEOUT,
        )

        if partner_address in device.linked_partners:
            device.linked_partners.remove(partner_address)
            await self._save_devices()

    async def _remove_stale_link_partner(
        self, address: str, partner_address: str, partner_type: int
    ) -> None:
        """Remove a link to an unknown device from a real MAX! device."""
        device = self.get_device(address)
        assert device is not None
        self._require_paired_for_write(address)
        if device.is_virtual:
            raise ValueError("Virtuelle Geraete haben keine Verknuepfungen auf dem Geraet.")
        if partner_type not in DEVICE_TYPE_NAMES:
            raise ValueError(f"Unbekannter partner_type {partner_type}.")
        description = (
            f"RemoveLinkPartner {self.format_device_label(address)} -> {partner_address} "
            f"(unbekannt, {DEVICE_TYPE_NAMES[partner_type]})"
        )
        if device.device_type == DEVICE_SHUTTER_CONTACT:
            await self._enqueue_shutter_command(
                address,
                PendingShutterCommand(
                    op="remove_link_partner",
                    description=description,
                    partner_address=partner_address,
                    partner_type=partner_type,
                ),
            )
            return
        counter = self._next_counter()
        cmd = build_remove_link_partner(
            counter, self.own_address, int(address, 16), int(partner_address, 16), partner_type
        )
        _LOGGER.info("%s", description)
        await self._set_last_command(address, description)
        await self._send_command(
            cmd,
            expected_src=address,
            device_address=address,
            counter=counter,
            description=description,
            retries=self._send_profile.config_retries,
            timeout=CONFIG_ACK_TIMEOUT,
        )
        if partner_address in device.linked_partners:
            device.linked_partners.remove(partner_address)
            await self._save_devices()

    async def async_associate_devices(
        self,
        addresses: list[str],
        group_id: int,
        bidirectional: bool = True,
    ) -> None:
        """Assign one group ID and create link-partner relations for multiple devices."""
        unique_addresses = list(dict.fromkeys(address.upper() for address in addresses))
        if len(unique_addresses) < 2:
            raise ValueError("Mindestens zwei Geraete werden fuer eine Assoziation benoetigt.")
        if group_id < 1 or group_id > 255:
            raise ValueError("group_id muss zwischen 1 und 255 liegen.")

        for address in unique_addresses:
            if self.get_device(address) is None:
                raise ValueError(f"Unbekannte Geraeteadresse {address}")
            self._require_paired_for_write(address)

        for address in unique_addresses:
            _LOGGER.info("Associating %s with group_id=%d", self._format_device_identity(address), group_id)
            await self.async_set_group_id(address, group_id)
            await asyncio.sleep(0.15)

        for index, address in enumerate(unique_addresses):
            for partner_address in unique_addresses[index + 1:]:
                forward_supported = False
                reverse_supported = False
                try:
                    self._validate_link_supported(address, partner_address)
                    forward_supported = True
                except ValueError:
                    forward_supported = False
                try:
                    self._validate_link_supported(partner_address, address)
                    reverse_supported = True
                except ValueError:
                    reverse_supported = False

                if not forward_supported and not reverse_supported:
                    _LOGGER.info(
                        "Skipping unsupported room link between %s and %s",
                        self._format_device_identity(address),
                        self._format_device_identity(partner_address),
                    )
                    continue

                if forward_supported:
                    await self.async_add_link_partner(address, partner_address)
                    await asyncio.sleep(0.15)
                elif bidirectional:
                    _LOGGER.info(
                        "Skipping unsupported link direction %s -> %s",
                        self._format_device_identity(address),
                        self._format_device_identity(partner_address),
                    )
                elif reverse_supported:
                    _LOGGER.info(
                        "Using reverse-only supported link direction %s -> %s",
                        self._format_device_identity(partner_address),
                        self._format_device_identity(address),
                    )
                    await self.async_add_link_partner(partner_address, address)
                    await asyncio.sleep(0.15)

                if bidirectional:
                    if reverse_supported:
                        await self.async_add_link_partner(partner_address, address)
                        await asyncio.sleep(0.15)
                    elif forward_supported:
                        _LOGGER.info(
                            "Skipping unsupported link direction %s -> %s",
                            self._format_device_identity(partner_address),
                            self._format_device_identity(address),
                        )
        pending_shutters = [
            self._format_device_identity(address)
            for address in unique_addresses
            if self._pending_shutter_config.get(address)
        ]
        _LOGGER.info(
            "Association complete: group_id=%d devices=%s",
            group_id,
            [self._format_device_identity(address) for address in unique_addresses],
        )
        if pending_shutters:
            _LOGGER.info(
                "Association has pending shutter-contact config waiting for device activity: %s",
                pending_shutters,
            )

    def _iter_room_association_pairs(
        self,
        climates: list[str],
        windows: list[str],
        *,
        bidirectional: bool,
    ) -> list[tuple[str, str]]:
        """Return a practical room-link plan instead of all theoretical pairs.

        For real-world room setups we mainly need:
        - wall thermostat <-> heating thermostats
        - heating thermostats <-> window contacts

        Linking wall thermostats directly to window contacts adds considerable
        traffic but provides little practical value in the common room model.
        Likewise, thermostat<->thermostat links are not needed here.
        """
        directed_pairs: list[tuple[str, str]] = []

        heatings = [
            address
            for address in climates
            if (device := self.get_device(address))
            and device.device_type in {DEVICE_HEATING_THERMOSTAT, DEVICE_HEATING_THERMOSTAT_PLUS}
        ]
        walls = [
            address
            for address in climates
            if (device := self.get_device(address))
            and device.device_type == DEVICE_WALL_THERMOSTAT
        ]

        def _add_pair(src: str, dst: str) -> None:
            if (src, dst) not in directed_pairs:
                directed_pairs.append((src, dst))

        for wall in walls:
            for heating in heatings:
                _add_pair(wall, heating)
                if bidirectional:
                    _add_pair(heating, wall)

        if heatings:
            for heating in heatings:
                for window in windows:
                    _add_pair(heating, window)
                    if bidirectional:
                        _add_pair(window, heating)
        else:
            # Fallback for unusual rooms that only have wall thermostats plus
            # windows. Keep functionality even though this is less common.
            for wall in walls:
                for window in windows:
                    _add_pair(wall, window)
                    if bidirectional:
                        _add_pair(window, wall)

        return directed_pairs

    def _build_room_association_status(
        self,
        *,
        room_name: str,
        climates: list[str],
        windows: list[str],
        group_id: int,
        bidirectional: bool,
        created_virtual_address: str | None,
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Summarize room-association progress and what is still missing."""
        all_addresses = climates + windows
        pair_plan = self._iter_room_association_pairs(
            climates,
            windows,
            bidirectional=bidirectional,
        )

        group_assignments: list[dict[str, Any]] = []
        missing_group_ids: list[dict[str, Any]] = []
        pending_devices: list[dict[str, Any]] = []
        for address in all_addresses:
            device = self.get_device(address)
            if device is None:
                continue
            payload = {
                "address": address,
                "label": self.format_device_label(address),
                "group_id": device.group_id,
                "pairing_state": self.get_pairing_state(address),
                "pending_config": list(device.pending_config or []),
            }
            group_assignments.append(payload)
            if device.group_id != group_id:
                missing_group_ids.append(
                    {
                        "address": address,
                        "label": self.format_device_label(address),
                        "expected_group_id": group_id,
                        "actual_group_id": device.group_id,
                        "retry_service_data": {
                            "address": address,
                            "group_id": group_id,
                        },
                    }
                )
            if device.pending_config:
                pending_devices.append(payload)

        completed_links: list[dict[str, Any]] = []
        missing_links: list[dict[str, Any]] = []
        pending_links: list[dict[str, Any]] = []
        activity_required_devices: list[dict[str, Any]] = []
        activity_required_seen: set[str] = set()
        for src, dst in pair_plan:
            device = self.get_device(src)
            present = bool(device and dst in device.linked_partners)
            pending = False
            if not present and device is not None:
                if device.device_type == DEVICE_SHUTTER_CONTACT and not device.is_virtual:
                    pending = any(
                        item.op == "add_link_partner" and item.partner_address == dst
                        for item in self._pending_shutter_config.get(src, [])
                    )
            payload = {
                "address": src,
                "partner_address": dst,
                "label": f"{self.format_device_label(src)} -> {self.format_device_label(dst)}",
                "present": present,
                "pending_after_activity": pending,
                "retry_service_data": {
                    "address": src,
                    "partner_address": dst,
                },
            }
            if present:
                completed_links.append(payload)
            elif pending:
                pending_links.append(payload)
                if src not in activity_required_seen:
                    activity_required_seen.add(src)
                    activity_required_devices.append(
                        {
                            "address": src,
                            "label": self.format_device_label(src),
                            "reason": "pending_window_activity",
                        }
                    )
            else:
                missing_links.append(payload)

        pending_group_ids: list[dict[str, Any]] = []
        for item in missing_group_ids:
            address = str(item["address"])
            device = self.get_device(address)
            expected_group_id = int(item["expected_group_id"])
            if not device or device.device_type != DEVICE_SHUTTER_CONTACT or device.is_virtual:
                continue
            pending = any(
                queued.op == "set_group_id" and queued.group_id == expected_group_id
                for queued in self._pending_shutter_config.get(address, [])
            )
            if not pending:
                continue
            pending_item = dict(item)
            pending_item["pending_after_activity"] = True
            pending_group_ids.append(pending_item)
            if address not in activity_required_seen:
                activity_required_seen.add(address)
                activity_required_devices.append(
                    {
                        "address": address,
                        "label": self.format_device_label(address),
                        "reason": "pending_window_activity",
                    }
                )

        effective_missing_group_ids = [
            item
            for item in missing_group_ids
            if not any(
                pending_item["address"] == item["address"]
                for pending_item in pending_group_ids
            )
        ]

        status = (
            "complete"
            if not effective_missing_group_ids and not missing_links and not errors and not pending_links and not pending_group_ids
            else "pending_activity"
            if (pending_links or pending_group_ids) and not effective_missing_group_ids and not missing_links and not errors
            else "partial"
        )
        summary = (
            "Raum-Assoziierung abgeschlossen."
            if status == "complete"
            else (
                "Fensterkontakte haben noch ausstehende Befehle. Bitte die betroffenen Fensterkontakte einmal ausloesen oder oeffnen/schliessen und danach den Status erneut pruefen."
                if status == "pending_activity"
                else (
                    "Raum-Assoziierung nur teilweise abgeschlossen. Es fehlen noch Gruppen- oder Link-Beziehungen; die Rueckgabe enthaelt einen Retry-Plan."
                )
            )
        )
        return {
            "room_name": room_name,
            "status": status,
            "summary": summary,
            "group_id": group_id,
            "climate_addresses": climates,
            "window_addresses": windows,
            "virtual_shutter_contact_address": created_virtual_address,
            "group_assignments": group_assignments,
            "missing_group_ids": effective_missing_group_ids,
            "pending_group_ids": pending_group_ids,
            "completed_links": completed_links,
            "missing_links": missing_links,
            "pending_links": pending_links,
            "pending_devices": pending_devices,
            "activity_required_devices": activity_required_devices,
            "errors": errors,
            "retry_plan": {
                "set_group_id": [item["retry_service_data"] for item in effective_missing_group_ids],
                "add_link_partner": [item["retry_service_data"] for item in missing_links],
            },
        }

    async def async_deassociate_devices(
        self,
        addresses: list[str],
        clear_group_id: bool = False,
        bidirectional: bool = True,
    ) -> None:
        """Remove link-partner relations for multiple devices and optionally clear the group ID."""
        unique_addresses = list(dict.fromkeys(address.upper() for address in addresses))
        if len(unique_addresses) < 2:
            raise ValueError("Mindestens zwei Geraete werden fuer eine Deassoziation benoetigt.")

        for address in unique_addresses:
            if self.get_device(address) is None:
                raise ValueError(f"Unbekannte Geraeteadresse {address}")
            self._require_paired_for_write(address)

        for index, address in enumerate(unique_addresses):
            for partner_address in unique_addresses[index + 1:]:
                forward_supported = False
                reverse_supported = False
                try:
                    self._validate_link_supported(address, partner_address)
                    forward_supported = True
                except ValueError:
                    forward_supported = False
                try:
                    self._validate_link_supported(partner_address, address)
                    reverse_supported = True
                except ValueError:
                    reverse_supported = False

                if forward_supported:
                    await self.async_remove_link_partner(address, partner_address)
                    await asyncio.sleep(0.15)
                elif not bidirectional and reverse_supported:
                    await self.async_remove_link_partner(partner_address, address)
                    await asyncio.sleep(0.15)
                if bidirectional and reverse_supported:
                    await self.async_remove_link_partner(partner_address, address)
                    await asyncio.sleep(0.15)

        if clear_group_id:
            for address in unique_addresses:
                await self.async_remove_group_id(address)
                await asyncio.sleep(0.15)
        _LOGGER.info(
            "Deassociation complete: devices=%s clear_group_id=%s",
            [self._format_device_identity(address) for address in unique_addresses],
            clear_group_id,
        )

    async def async_create_room_association(
        self,
        *,
        room_name: str,
        climate_addresses: list[str],
        window_addresses: list[str] | None = None,
        group_id: int | None = None,
        create_virtual_shutter_contact: bool = False,
        virtual_shutter_contact_address: str | None = None,
        virtual_shutter_contact_name: str | None = None,
        bidirectional: bool = True,
    ) -> dict[str, Any]:
        """Create a full room association with optional virtual shutter contact."""
        climates = list(dict.fromkeys(address.upper() for address in climate_addresses))
        windows = list(dict.fromkeys(address.upper() for address in (window_addresses or [])))

        if not climates:
            raise ValueError("Mindestens ein Klima-Geraet wird fuer einen Raum benoetigt.")
        for address in climates + windows:
            if self.get_device(address) is None:
                raise ValueError(f"Unbekannte Geraeteadresse {address}")
            self._require_paired_for_write(address)

        resolved_group_id = group_id or self.get_next_free_group_id()
        if resolved_group_id < 1 or resolved_group_id > 255:
            raise ValueError("group_id muss zwischen 1 und 255 liegen.")
        _LOGGER.info(
            "Creating room association '%s' with climates=%s windows=%s requested_group_id=%s",
            room_name,
            [self._format_device_identity(address) for address in climates],
            [self._format_device_identity(address) for address in windows],
            group_id,
        )

        created_virtual_address: str | None = None
        if create_virtual_shutter_contact:
            created_virtual_address = (
                virtual_shutter_contact_address.upper()
                if virtual_shutter_contact_address
                else self.get_next_virtual_address()
            )
            await self.async_create_virtual_shutter_contact(
                created_virtual_address,
                virtual_shutter_contact_name or f"{room_name} Fensterkontakt",
                resolved_group_id,
            )
            windows.append(created_virtual_address)

        all_addresses = climates + windows
        if len(all_addresses) < 2:
            raise ValueError("Ein Raum braucht mindestens zwei beteiligte Geraete.")

        errors: list[dict[str, Any]] = []

        for address in all_addresses:
            device = self.get_device(address)
            if device is not None and device.group_id == resolved_group_id:
                _LOGGER.info(
                    "Room association '%s': skipping SetGroupId for %s because group_id=%d is already set",
                    room_name,
                    self._format_device_identity(address),
                    resolved_group_id,
                )
                continue
            if (
                device is not None
                and device.device_type == DEVICE_SHUTTER_CONTACT
                and not device.is_virtual
                and self._pending_shutter_command_exists(
                    address,
                    PendingShutterCommand(
                        op="set_group_id",
                        description="",
                        group_id=resolved_group_id,
                    ),
                )
            ):
                _LOGGER.info(
                    "Room association '%s': skipping SetGroupId for %s because an equivalent pending command already exists",
                    room_name,
                    self._format_device_identity(address),
                )
                continue
            _LOGGER.info(
                "Room association '%s': setting group_id=%d on %s",
                room_name,
                resolved_group_id,
                self._format_device_identity(address),
            )
            try:
                await self.async_set_group_id(address, resolved_group_id)
            except Exception as err:
                _LOGGER.warning(
                    "Room association '%s': SetGroupId failed for %s: %s: %s",
                    room_name,
                    self._format_device_identity(address),
                    err.__class__.__name__,
                    err,
                )
                errors.append(
                    {
                        "step": "set_group_id",
                        "address": address,
                        "label": self.format_device_label(address),
                        "error": str(err),
                        "error_type": err.__class__.__name__,
                    }
                )
            await asyncio.sleep(0.05)

        pair_plan = self._iter_room_association_pairs(
            climates,
            windows,
            bidirectional=bidirectional,
        )
        _LOGGER.info(
            "Room association '%s': planned directed links=%s",
            room_name,
            [
                f"{self._format_device_identity(src)} -> {self._format_device_identity(dst)}"
                for src, dst in pair_plan
            ],
        )
        for src, dst in pair_plan:
            source_device = self.get_device(src)
            if source_device is not None and dst in source_device.linked_partners:
                _LOGGER.info(
                    "Room association '%s': skipping AddLinkPartner for %s -> %s because the peer already exists",
                    room_name,
                    self._format_device_identity(src),
                    self._format_device_identity(dst),
                )
                continue
            if (
                source_device is not None
                and source_device.device_type == DEVICE_SHUTTER_CONTACT
                and not source_device.is_virtual
                and self._pending_shutter_command_exists(
                    src,
                    PendingShutterCommand(
                        op="add_link_partner",
                        description="",
                        partner_address=dst,
                    ),
                )
            ):
                _LOGGER.info(
                    "Room association '%s': skipping AddLinkPartner for %s -> %s because an equivalent pending command already exists",
                    room_name,
                    self._format_device_identity(src),
                    self._format_device_identity(dst),
                )
                continue
            try:
                await self.async_add_link_partner(src, dst)
            except Exception as err:
                _LOGGER.warning(
                    "Room association '%s': AddLinkPartner failed for %s -> %s: %s: %s",
                    room_name,
                    self._format_device_identity(src),
                    self._format_device_identity(dst),
                    err.__class__.__name__,
                    err,
                )
                errors.append(
                    {
                        "step": "add_link_partner",
                        "address": src,
                        "partner_address": dst,
                        "label": f"{self.format_device_label(src)} -> {self.format_device_label(dst)}",
                        "error": str(err),
                        "error_type": err.__class__.__name__,
                    }
                )
            await asyncio.sleep(0.05)
        result = self._build_room_association_status(
            room_name=room_name,
            climates=climates,
            windows=windows,
            group_id=resolved_group_id,
            bidirectional=bidirectional,
            created_virtual_address=created_virtual_address,
            errors=errors,
        )
        _LOGGER.info(
            "Room association '%s' finished with status=%s missing_group_ids=%d missing_links=%d errors=%d",
            room_name,
            result["status"],
            len(result["missing_group_ids"]),
            len(result["missing_links"]),
            len(result["errors"]),
        )
        return result

    async def async_delete_room_association(
        self,
        *,
        room_name: str,
        climate_addresses: list[str],
        window_addresses: list[str] | None = None,
        clear_group_id: bool = True,
        delete_virtual_shutter_contacts: bool = False,
        bidirectional: bool = True,
    ) -> dict[str, Any]:
        """Delete a full room association and optionally remove virtual contacts."""
        climates = list(dict.fromkeys(address.upper() for address in climate_addresses))
        windows = list(dict.fromkeys(address.upper() for address in (window_addresses or [])))
        all_addresses = climates + windows

        if len(all_addresses) < 2:
            raise ValueError("Ein Raumabbau braucht mindestens zwei beteiligte Geraete.")
        for address in all_addresses:
            if self.get_device(address) is None:
                raise ValueError(f"Unbekannte Geraeteadresse {address}")
            self._require_paired_for_write(address)
        _LOGGER.info(
            "Deleting room association '%s' for devices=%s",
            room_name,
            [self._format_device_identity(address) for address in all_addresses],
        )

        await self.async_deassociate_devices(
            all_addresses,
            clear_group_id=clear_group_id,
            bidirectional=bidirectional,
        )

        deleted_virtual_addresses: list[str] = []
        if delete_virtual_shutter_contacts:
            for address in windows:
                device = self.get_device(address)
                if device and device.is_virtual and device.device_type == DEVICE_SHUTTER_CONTACT:
                    await self.async_delete_virtual_device(address)
                    deleted_virtual_addresses.append(address)

        return {
            "room_name": room_name,
            "climate_addresses": climates,
            "window_addresses": windows,
            "deleted_virtual_addresses": deleted_virtual_addresses,
            "clear_group_id": clear_group_id,
        }

    async def async_rebuild_room_association(
        self,
        *,
        room_name: str,
        climate_addresses: list[str],
        window_addresses: list[str] | None = None,
        group_id: int | None = None,
        create_virtual_shutter_contact: bool = False,
        virtual_shutter_contact_address: str | None = None,
        virtual_shutter_contact_name: str | None = None,
        clear_group_id: bool = True,
        delete_virtual_shutter_contacts: bool = False,
        bidirectional: bool = True,
    ) -> dict[str, Any]:
        """Rebuild a full room association from the supplied device set."""
        climates = list(dict.fromkeys(address.upper() for address in climate_addresses))
        windows = list(dict.fromkeys(address.upper() for address in (window_addresses or [])))

        await self.async_delete_room_association(
            room_name=room_name,
            climate_addresses=climates,
            window_addresses=windows,
            clear_group_id=clear_group_id,
            delete_virtual_shutter_contacts=delete_virtual_shutter_contacts,
            bidirectional=bidirectional,
        )

        return await self.async_create_room_association(
            room_name=room_name,
            climate_addresses=climates,
            window_addresses=windows,
            group_id=group_id,
            create_virtual_shutter_contact=create_virtual_shutter_contact,
            virtual_shutter_contact_address=virtual_shutter_contact_address,
            virtual_shutter_contact_name=virtual_shutter_contact_name,
            bidirectional=bidirectional,
        )

    async def async_set_week_profile(self, address: str, profile_text: str) -> str:
        """Parse, upload and persist a week profile for one thermostat."""
        device = self.get_device(address)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {address}")
        if device.device_type not in CLIMATE_DEVICE_TYPES:
            raise ValueError(f"Geraet {address} unterstuetzt kein Wochenprofil")
        self._require_paired_for_write(address)

        updates = parse_week_profile_text(profile_text)
        base_profile = self.get_local_week_profile(address)
        merged_profile = encode_week_profile(updates, base_profile)
        if base_profile:
            known_days = set(device.week_profile_days) if device.week_profile_days else set(range(7))
        else:
            known_days = set()  # the device's other days were programmed elsewhere
        known_days |= set(updates)
        pending_commands: list[PendingClimateCommand] = []
        for day in sorted(updates):
            for part, chunk_hex in split_week_profile_for_send(merged_profile, day):
                pending_commands.append(
                    PendingClimateCommand(
                        op="config_week_profile",
                        description=f"ConfigWeekProfile {address} day={day} part={part}",
                        day=day,
                        part=part,
                        chunk_hex=chunk_hex,
                        profile_hex=merged_profile,
                    )
                )

        await self._replace_pending_climate_commands(address, pending_commands)
        _LOGGER.info(
            "Week profile upload for %s starts without automatic WakeUp. "
            "This mirrors the more conservative FHEM behavior and avoids losing early packets on some devices.",
            self._format_device_identity(address),
        )
        await self._process_climate_config_queue(address, trigger="save_week_profile")

        if self._pending_climate_config.get(address.upper()):
            _LOGGER.warning(
                "Week profile for %s is queued and will continue to retry in the background. Pending: %d packets",
                self._format_device_identity(address),
                len(self._pending_climate_config[address.upper()]),
            )
        else:
            _LOGGER.info("Week profile for %s uploaded successfully", self._format_device_identity(address))

        device.week_profile = merged_profile
        device.week_profile_days = [] if len(known_days) == 7 else sorted(known_days)
        await self._save_devices()
        self._notify_week_profile_updated(address)
        await self._sync_pending_config_reading(address)
        return "\n".join(format_week_profile_lines(merged_profile))

    async def async_wake_all_thermostats(self) -> None:
        """Send WakeUp to all known thermostats (for manual polling)."""
        _LOGGER.warning(
            "Manual WakeUp for all thermostats requested. This is intended for diagnostics/config only "
            "and can noticeably increase battery usage if used often."
        )
        for device in self._devices.values():
            if device.device_type in CLIMATE_DEVICE_TYPES:
                await self.async_wake_device(device.address)
                await asyncio.sleep(0.5)  # Longer delay for manual wake

    async def _periodic_time_sync_loop(self) -> None:
        """Periodically synchronize device clocks in sparse hourly timeslots."""
        try:
            await asyncio.sleep(60)
            while True:
                try:
                    await self._run_periodic_time_sync()
                except Exception:
                    _LOGGER.exception("Periodic MAX! time sync failed")
                await asyncio.sleep(PERIODIC_TIME_SYNC_INTERVAL)
        except asyncio.CancelledError:
            return

    def _schedule_startup_time_sync(self) -> None:
        """Schedule one staggered startup time sync for paired climate devices."""
        if self._startup_time_sync_task and not self._startup_time_sync_task.done():
            return
        self._startup_time_sync_task = self.hass.loop.create_task(self._startup_time_sync_once())

    async def _startup_time_sync_once(self) -> None:
        """Shortly after startup, push time once to paired climate devices.

        This is intentionally more eager than the sparse hourly slot logic. A
        single missed TimeInformation packet can otherwise leave devices with a
        stale clock for many hours, which then breaks the observed weekly
        schedule even though the stored profile itself is valid.
        """
        try:
            await asyncio.sleep(STARTUP_TIME_SYNC_INITIAL_DELAY)
            targets = [
                device.address
                for device in self.get_all_devices()
                if device.device_type in CLIMATE_DEVICE_TYPES
                and self.is_device_paired(device.address)
                and not device.pending_config
            ]
            if not targets:
                return
            _LOGGER.info(
                "Startup MAX! time sync for %s",
                [self._format_device_identity(address) for address in targets],
            )
            for address in targets:
                try:
                    await self.async_send_time_information(address)
                except Exception:
                    _LOGGER.exception(
                        "Startup time sync to %s failed",
                        self._format_device_identity(address),
                    )
                await asyncio.sleep(self._send_profile.startup_time_sync_device_delay)
        except asyncio.CancelledError:
            return

    async def _ensure_time_slots_assigned(self) -> None:
        """Assign stable 0..11 time-sync slots to paired climate devices."""
        slot_usage = [0] * 12
        changed = False
        for device in self.get_all_devices():
            if device.device_type not in CLIMATE_DEVICE_TYPES or not self.is_device_paired(device.address):
                continue
            if 0 <= device.time_slot <= 11:
                slot_usage[device.time_slot] += 1
        for device in self.get_all_devices():
            if device.device_type not in CLIMATE_DEVICE_TYPES or not self.is_device_paired(device.address):
                continue
            if 0 <= device.time_slot <= 11:
                continue
            slot = min(range(12), key=lambda idx: slot_usage[idx])
            device.time_slot = slot
            slot_usage[slot] += 1
            changed = True
            _LOGGER.info("Assigned MAX! time-sync slot %d to %s", slot, self._format_device_identity(device.address))
        if changed:
            await self._save_devices()
            for device in self.get_all_devices():
                if device.device_type in CLIMATE_DEVICE_TYPES:
                    self._notify_diagnostics_updated(device.address)

    async def _run_periodic_time_sync(self) -> None:
        """Send time to thermostats whose sparse hourly slot is due."""
        await self._ensure_time_slots_assigned()
        current_slot = datetime.now().astimezone().hour % 12
        now = datetime.now(UTC)
        targets: list[str] = []
        for device in self.get_all_devices():
            if device.device_type not in CLIMATE_DEVICE_TYPES:
                continue
            if not self.is_device_paired(device.address):
                continue
            if device.pending_config:
                continue
            if device.time_slot != current_slot:
                continue
            last_sync = datetime.fromisoformat(device.last_time_sync_at) if device.last_time_sync_at else None
            if last_sync is not None and (now - last_sync) < PERIODIC_TIME_SYNC_MIN_AGE:
                continue
            targets.append(device.address)

        if not targets:
            return

        _LOGGER.info(
            "Periodic MAX! time sync for slot %d: %s",
            current_slot,
            [self._format_device_identity(address) for address in targets],
        )
        for address in targets:
            try:
                await self.async_send_time_information(address)
            except Exception:
                _LOGGER.exception("Periodic time sync to %s failed", self._format_device_identity(address))
            await asyncio.sleep(0.5)

    async def _maybe_sync_time_after_climate_config(self, address: str, *, reason: str) -> None:
        """Synchronize time after climate config completed if the device clock is stale or unknown."""
        normalized = address.upper()
        device = self.get_device(normalized)
        if device is None or device.device_type not in CLIMATE_DEVICE_TYPES:
            return
        if not self.is_device_paired(normalized):
            return
        if self._pending_climate_config.get(normalized):
            return

        should_sync = not device.last_time_sync_at
        if not should_sync and device.last_time_sync_at:
            try:
                last_sync = datetime.fromisoformat(device.last_time_sync_at)
            except ValueError:
                should_sync = True
            else:
                should_sync = (datetime.now(UTC) - last_sync) >= timedelta(hours=6)

        if not should_sync:
            return

        try:
            await asyncio.sleep(0.5)
            await self.async_send_time_information(normalized)
            _LOGGER.info(
                "Sent follow-up time sync to %s after %s",
                self._format_device_identity(normalized),
                reason,
            )
        except Exception:
            _LOGGER.exception(
                "Follow-up time sync to %s after %s failed",
                self._format_device_identity(normalized),
                reason,
            )

    async def async_send_time_information(
        self,
        address: str,
        *,
        priority: int = COMMAND_PRIORITY_LOW,
    ) -> None:
        """Send current local time to one thermostat/wall thermostat.

        Thermostats and wall thermostats ACK TimeInformation (verified on real
        devices, ~1.1 s after the 1 s preamble). One acknowledged packet with
        retries is therefore enough; FHEM does the same. Each unacknowledged
        repeat would cost a full 1 s of the CUL's 1 % duty-cycle budget.
        """
        normalized = address.upper()
        device = self.get_device(normalized)
        if device is None:
            raise ValueError(f"Unbekannte Geraeteadresse {normalized}")
        if device.device_type not in CLIMATE_DEVICE_TYPES:
            raise ValueError(f"Geraet {normalized} unterstuetzt keine Zeitsynchronisation.")
        self._require_paired_for_write(normalized)

        _LOGGER.info("Sending TimeInformation to %s", self._format_device_identity(normalized))
        await self._set_last_command(normalized, "TimeInformation")
        counter = self._next_counter()
        cmd = build_time_information(counter, self.own_address, int(normalized, 16))
        await self._send_command(
            cmd,
            expected_src=normalized,
            device_address=normalized,
            counter=counter,
            description=f"TimeInformation {self.format_device_label(normalized)}",
            retries=TIME_INFORMATION_ACK_RETRIES,
            timeout=TIME_INFORMATION_ACK_TIMEOUT,
            priority=priority,
        )
        await self._mark_time_sync_sent(normalized)

    async def async_sync_time(self, addresses: list[str] | None = None) -> list[str]:
        """Synchronize time to selected or all paired thermostats."""
        targets = (
            [address.upper() for address in addresses]
            if addresses
            else [
                device.address
                for device in self.get_all_devices()
                if device.device_type in CLIMATE_DEVICE_TYPES and self.is_device_paired(device.address)
            ]
        )
        synced: list[str] = []
        for address in list(dict.fromkeys(targets)):
            await self.async_send_time_information(address)
            synced.append(address)
            await asyncio.sleep(0.25)
        return synced

    def _schedule_auto_mode_time_sync_followup(self, address: str) -> None:
        """Schedule one delayed time refresh after switching a device to auto."""
        normalized = address.upper()
        existing = self._auto_mode_time_sync_tasks.get(normalized)
        if existing is not None and not existing.done():
            existing.cancel()
        self._auto_mode_time_sync_tasks[normalized] = self.hass.loop.create_task(
            self._auto_mode_time_sync_followup(normalized)
        )

    async def _auto_mode_time_sync_followup(self, address: str) -> None:
        """Repeat TimeInformation shortly after entering auto mode.

        TimeInformation has no ACK. Sending it once immediately and once a bit
        later makes schedule re-entry more reliable after manual overrides.
        """
        try:
            await asyncio.sleep(AUTO_MODE_TIME_SYNC_FOLLOWUP_DELAY)
            device = self.get_device(address)
            if (
                device is None
                or device.device_type not in CLIMATE_DEVICE_TYPES
                or not device.paired
                or device.pending_config
            ):
                return
            await self.async_send_time_information(address)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Delayed auto-mode time sync failed for %s",
                self._format_device_identity(address),
            )
        finally:
            self._auto_mode_time_sync_tasks.pop(address, None)

    async def async_wake_device(self, address: str) -> None:
        """Send WakeUp (0xF1) — keeps device RF receiver open briefly."""
        _LOGGER.info(
            "Sending WakeUp to %s. Frequent WakeUp use can increase battery drain and RF traffic.",
            self._format_device_identity(address),
        )
        dst = int(address, 16)
        counter = self._next_counter()
        cmd = build_wake_up(counter, self.own_address, dst)
        await self._set_last_command(address, "WakeUp")
        await self._send_command(
            cmd,
            expected_src=None,
            device_address=address,
            counter=None,
            description=f"WakeUp {self.format_device_label(address)}",
        )

    async def _mark_time_sync_sent(self, address: str) -> None:
        """Persist that time information was sent to a device."""
        device = self._devices.get(address.upper())
        if device is None:
            return
        device.last_time_sync_at = datetime.now(UTC).isoformat()
        await self._save_devices()
        self._notify_diagnostics_updated(address)

    async def _update_device_time_status(
        self,
        address: str,
        *,
        reported_time: datetime,
        offset_seconds: int,
    ) -> None:
        """Persist time diagnostics learned from device TimeInformation packets."""
        device = self._devices.get(address.upper())
        if device is None:
            return
        device.last_reported_time = reported_time.isoformat(sep=" ")
        device.last_time_offset_seconds = offset_seconds
        await self._save_devices()
        self._notify_diagnostics_updated(address)

    def _next_counter(self) -> int:
        """Return the next MAX! message counter value."""
        self._counter = (self._counter + 1) % 256
        return self._counter

    async def _send_command(
        self,
        cmd: str,
        *,
        expected_src: str | None,
        device_address: str | None,
        counter: int | None,
        description: str,
        retries: int = ACK_RETRIES,
        timeout: float = ACK_TIMEOUT,
        priority: int = COMMAND_PRIORITY_NORMAL,
    ) -> MaxMessage | None:
        """Queue one MAX! command for serialized execution."""
        future: asyncio.Future[MaxMessage | None] = self.hass.loop.create_future()
        self._enqueue_command_request(
            CommandRequest(
                cmd=cmd,
                expected_src=expected_src,
                device_address=device_address,
                counter=counter,
                description=description,
                retries=retries,
                timeout=timeout,
                future=future,
                priority=priority,
            )
        )
        return await future

    async def _send_raw(
        self,
        cmd: str,
        *,
        priority: bool = False,
        reserve: float = 0.0,
    ) -> None:
        """Write a raw CULFW command string over TCP."""
        if self._writer is None:
            _LOGGER.warning("Cannot send immediately because CULFW is disconnected, waiting for reconnect")
            await self._ensure_connected()
        cost = self._estimate_cul_credit_cost(cmd)
        if cost > 0 and not priority:
            await self._wait_for_cul_credit(cost, reserve=reserve)
        cmd = self._refresh_time_information_command(cmd)
        async with self._send_lock:
            if self._writer is None:
                _LOGGER.warning("CULFW disconnected while waiting to send, reconnecting")
                await self._ensure_connected()
            if not cmd.endswith("\n"):
                cmd += "\n"
            _LOGGER.debug("CUL TX: %s", cmd.strip())
            if cost > 0:
                self._consume_cul_credit(cost)
            try:
                self._writer.write(cmd.encode("ascii"))
                self._last_tx_at = self.hass.loop.time()
                await self._writer.drain()
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                _LOGGER.warning("CULFW send failed: %s", e)
                await self._close_connection()
                self._schedule_reconnect()
                raise

    def _extract_culfw_packet_hex(self, cmd: str) -> str | None:
        """Return the raw MAX!/CUL packet hex from one send command."""
        line = cmd.strip()
        if line.startswith(("Zs", "Zf")) and len(line) > 2:
            return line[2:]
        if line.startswith(("Za", "Zw", "Zr", "Zx")):
            return None  # culfw control commands (auto-ACK, fake WT, RX on/off)
        if line.startswith("Z") and len(line) > 1 and line[1] in "0123456789ABCDEFabcdef":
            return line[1:]
        return None

    def _refresh_time_information_command(self, cmd: str) -> str:
        """Rebuild queued TimeInformation right before send, like FHEM's send queue."""
        packet_hex = self._extract_culfw_packet_hex(cmd)
        if not packet_hex or len(packet_hex) < 22:
            return cmd
        try:
            msg_type = int(packet_hex[6:8], 16)
        except ValueError:
            return cmd
        if msg_type != MSG_TIME_INFORMATION:
            return cmd
        try:
            counter = int(packet_hex[2:4], 16)
            src = int(packet_hex[8:14], 16)
            dst = int(packet_hex[14:20], 16)
        except ValueError:
            return cmd
        refreshed = build_time_information(counter, src, dst)
        _LOGGER.debug("Refreshed queued TimeInformation payload immediately before send")
        return refreshed

    def _refresh_cul_credit_estimate(self) -> None:
        """Recover estimated CUL send credits over time."""
        now = self.hass.loop.time()
        if self._cul_credit_updated_at == 0.0:
            self._cul_credit_updated_at = now
            return
        elapsed = max(0.0, now - self._cul_credit_updated_at)
        self._cul_credit_estimate = min(
            self._cul_credit_max,
            self._cul_credit_estimate + elapsed * self._cul_credit_rate,
        )
        self._cul_credit_updated_at = now

    def _consume_cul_credit(self, cost: float) -> None:
        """Book one send against the local credit estimate."""
        self._refresh_cul_credit_estimate()
        self._cul_credit_estimate = max(0.0, self._cul_credit_estimate - cost)
        self._cul_credit_consumed_total += cost

    def _handle_credit_report(self, credit: int) -> None:
        """Adopt a credit_10ms value reported by culfw ("X" command)."""
        now = self.hass.loop.time()
        self._measure_cul_credit_rate(now, float(credit))
        self._cul_credit_estimate = float(credit)
        self._cul_credit_updated_at = now
        self._cul_credit_reported_at = now
        self._cul_credit_known = True
        if credit > self._cul_credit_max:
            _LOGGER.info(
                "CUL reports %d credit_10ms, more than the assumed maximum %.0f; adopting it",
                credit,
                self._cul_credit_max,
            )
            self._cul_credit_max = float(credit)
        self._update_send_profile()
        future = self._cul_credit_future
        if future is not None and not future.done():
            future.set_result(credit)
        self._notify_cul_status()

    def _measure_cul_credit_rate(self, now: float, credit: float) -> None:
        """Estimate how fast the CUL regains credit from two consecutive reports.

        Standard a-culfw adds 1 credit per second; modified firmware may add
        more. Samples are only usable while the credit is below its cap, so
        "recovered" = difference + everything we sent in between.
        """
        last = self._cul_credit_last_report
        self._cul_credit_last_report = (now, credit, self._cul_credit_consumed_total)
        if last is None:
            return
        last_time, last_credit, last_consumed = last
        elapsed = now - last_time
        cap = self._cul_credit_max
        if (
            elapsed < CUL_CREDIT_RATE_MIN_INTERVAL
            or last_credit >= cap * 0.98
            or credit >= cap * 0.98
        ):
            return
        recovered = credit - last_credit + (self._cul_credit_consumed_total - last_consumed)
        if recovered <= 0:
            return
        sample = max(0.1, recovered / elapsed)
        if self._cul_credit_rate_samples == 0:
            rate = sample
        else:
            rate = 0.7 * self._cul_credit_rate + 0.3 * sample
        self._cul_credit_rate_samples += 1
        if abs(rate - self._cul_credit_rate) > 0.05:
            _LOGGER.info("CUL credit recovery measured at %.2f credit_10ms/s", rate)
        self._cul_credit_rate = rate

    def _update_send_profile(self) -> None:
        """Pick standard or extended retry behaviour from the measured budget."""
        extended = (
            self._cul_credit_max > CUL_CREDIT_STANDARD_MAX * CUL_CREDIT_EXTENDED_MAX_FACTOR
            or self._cul_credit_rate > CUL_CREDIT_EXTENDED_RATE
        )
        profile = SEND_PROFILE_EXTENDED if extended else SEND_PROFILE_STANDARD
        if profile is self._send_profile:
            return
        _LOGGER.info(
            "CUL send budget %.0f (recovery %.2f/s): using %s send profile",
            self._cul_credit_max,
            self._cul_credit_rate,
            profile.name,
        )
        self._send_profile = profile

    @property
    def send_profile(self) -> SendProfile:
        """Return the active send profile."""
        return self._send_profile

    @callback
    def add_cul_status_listener(self, cb: Callable[[], None]) -> Callable:
        """Register a callback for CUL budget/queue status changes."""
        self._cul_status_listeners.append(cb)

        def remove() -> None:
            if cb in self._cul_status_listeners:
                self._cul_status_listeners.remove(cb)

        return remove

    def _notify_cul_status(self) -> None:
        for cb in list(self._cul_status_listeners):
            self.hass.loop.call_soon(cb)

    def _handle_lovf(self) -> None:
        """culfw dropped a packet because its duty-cycle credit was exhausted."""
        self._cul_credit_estimate = 0.0
        self._cul_credit_updated_at = self.hass.loop.time()
        self._cul_credit_queried_at = 0.0  # allow an immediate re-query
        pending = self._pending_ack
        # Only blame our in-flight packet if we just sent it; another client on
        # the same CUL could cause LOVF lines as well.
        if (
            pending is not None
            and not pending.future.done()
            and self.hass.loop.time() - self._last_tx_at < 1.5
        ):
            pending.future.set_exception(CulCreditError("CUL out of send credit (LOVF)"))

    def get_cul_credit_status(self) -> dict[str, Any]:
        """Return the current credit view for diagnostics."""
        self._refresh_cul_credit_estimate()
        return {
            "credit_10ms": round(self._cul_credit_estimate),
            "credit_max": round(self._cul_credit_max),
            "credit_known": self._cul_credit_known,
            "recovery_per_second": round(self._cul_credit_rate, 2),
            "recovery_measured": self._cul_credit_rate_samples > 0,
            "send_profile": self._send_profile.name,
            "queued_commands": self._command_queue.qsize(),
        }

    async def _query_cul_credit(self, *, force: bool = False) -> float | None:
        """Ask culfw for its real credit_10ms ("X"), rate limited."""
        if self._writer is None:
            return None
        now = self.hass.loop.time()
        if not force and now - self._cul_credit_queried_at < CUL_CREDIT_QUERY_MIN_INTERVAL:
            return self._cul_credit_estimate if self._cul_credit_known else None
        if self._cul_credit_future is not None and not self._cul_credit_future.done():
            future = self._cul_credit_future
        else:
            future = self.hass.loop.create_future()
            self._cul_credit_future = future
            self._cul_credit_queried_at = now
            try:
                async with self._send_lock:
                    if self._writer is None:
                        return None
                    self._writer.write(b"X\n")
                    await self._writer.drain()
            except (BrokenPipeError, ConnectionResetError, OSError) as err:
                _LOGGER.debug("CUL credit query failed: %s", err)
                return None
        try:
            credit = await asyncio.wait_for(asyncio.shield(future), timeout=CUL_CREDIT_QUERY_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.debug("CUL did not answer credit query in time")
            return None
        return float(credit)

    def _estimate_cul_credit_cost(self, cmd: str) -> float:
        """Return the culfw credit cost (rf_moritz.c: moritz_sendraw)."""
        packet_hex = self._extract_culfw_packet_hex(cmd)
        if not packet_hex:
            return 0.0
        bit_cost = (len(packet_hex) * 4) // 10
        preamble = CUL_CREDIT_PREAMBLE_COST if cmd.strip().startswith("Zs") else 0.0
        return preamble + float(bit_cost)

    async def _wait_for_cul_credit(
        self,
        cost: float,
        *,
        reserve: float = 0.0,
        preempt_priority: int | None = None,
    ) -> bool:
        """Wait until the CUL can send a packet of the given cost.

        Returns False (without waiting further) if a more urgent command was
        queued while waiting and preempt_priority was given.
        """
        if cost <= 0:
            return True
        # Never demand more than the CUL can ever hold.
        reserve = max(0.0, min(reserve, self._cul_credit_max - cost))
        needed = cost + reserve
        logged = False
        while True:
            if preempt_priority is not None and self._has_more_urgent_command(preempt_priority):
                return False
            self._refresh_cul_credit_estimate()
            if self._cul_credit_estimate >= needed:
                return True
            # The estimate is conservative; ask the CUL for the real value.
            await self._query_cul_credit()
            self._refresh_cul_credit_estimate()
            if self._cul_credit_estimate >= needed:
                return True
            if self._cul_credit_known:
                wait_time = min(
                    CUL_CREDIT_MAX_WAIT_SLICE,
                    (needed - self._cul_credit_estimate) / self._cul_credit_rate + 0.5,
                )
            else:
                wait_time = CUL_CREDIT_UNKNOWN_WAIT
            if not logged:
                _LOGGER.info(
                    "CUL credit pacing: need %.0f (incl. reserve %.0f), have %.0f%s; waiting",
                    needed,
                    reserve,
                    self._cul_credit_estimate,
                    "" if self._cul_credit_known else " (estimated)",
                )
                logged = True
            if preempt_priority is None:
                await asyncio.sleep(wait_time)
                continue
            self._command_enqueued.clear()
            try:
                await asyncio.wait_for(self._command_enqueued.wait(), timeout=wait_time)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Device registry
    # ------------------------------------------------------------------

    def get_device(self, address: str) -> KnownDevice | None:
        return self._devices.get(address.upper())

    def get_all_devices(self) -> list[KnownDevice]:
        return list(self._devices.values())

    def get_superseded_devices(self) -> list[KnownDevice]:
        """Return devices that have been superseded by another device entry."""
        return [device for device in self._devices.values() if device.superseded_by]

    def _find_devices_by_serial(self, serial_number: str) -> list[KnownDevice]:
        """Return devices with the exact same serial number."""
        serial = _sanitize_serial_number(serial_number)
        if not serial:
            return []
        return [
            device
            for device in self._devices.values()
            if _sanitize_serial_number(device.serial_number) == serial
        ]

    def _mark_superseded_devices(
        self,
        *,
        new_address: str,
        serial_number: str,
        name: str,
    ) -> list[KnownDevice]:
        """Mark older devices as superseded when a duplicate is paired again."""
        superseded: list[KnownDevice] = []
        normalized_new = new_address.upper()
        serial_matches = [
            device
            for device in self._find_devices_by_serial(serial_number)
            if device.address != normalized_new
        ]
        for device in serial_matches:
            device.superseded_by = normalized_new
            device.duplicate_reason = f"serial_number:{_sanitize_serial_number(serial_number)}"
            superseded.append(device)

        # Name-only duplicates are suspicious, but not safe enough for auto-cleanup.
        name_matches = [
            device
            for device in self._devices.values()
            if device.address != normalized_new and device.name.strip() and device.name == name
        ]
        if name_matches:
            _LOGGER.warning(
                "Possible duplicate by name for %s: same name '%s' already present at %s",
                self._format_device_identity(normalized_new),
                name,
                [self._format_device_identity(device.address) for device in name_matches],
            )

        return superseded

    async def async_remove_known_devices(self, addresses: list[str]) -> list[str]:
        """Remove devices from the internal known-device store."""
        removed: list[str] = []
        for address in dict.fromkeys(address.upper() for address in addresses):
            if address in self._devices:
                del self._devices[address]
                removed.append(address)
        if removed:
            await self._save_devices()
            _LOGGER.info(
                "Removed known MAX! devices from storage: %s",
                [self._format_device_identity(address) for address in removed],
            )
        return removed

    def get_used_group_ids(self) -> set[int]:
        """Return all currently used non-zero group IDs."""
        return {device.group_id for device in self._devices.values() if device.group_id > 0}

    def get_next_free_group_id(self) -> int:
        """Return the next free MAX! group ID."""
        used = self.get_used_group_ids()
        for group_id in range(1, 256):
            if group_id not in used:
                return group_id
        raise ValueError("Keine freie MAX!-Gruppen-ID mehr verfuegbar.")

    def get_next_virtual_address(self) -> str:
        """Return the next free address in the virtual device range A00000-AFFFFF."""
        used = {address.upper() for address in self._devices}
        for value in range(0xA00000, 0xB00000):
            address = f"{value:06X}"
            if address not in used:
                return address
        raise ValueError("Keine freie virtuelle MAX!-Adresse mehr verfuegbar.")

    def format_device_label(self, address: str) -> str:
        """Return one human-friendly device label for logs."""
        normalized = address.upper()
        device = self.get_device(normalized)
        if device is None or not device.name.strip():
            return normalized
        return f"{normalized} ({device.name})"

    def _format_device_identity(self, address: str) -> str:
        """Return one human-friendly device identity for logs."""
        normalized = address.upper()
        device = self.get_device(normalized)
        if device is None:
            return normalized
        serial = device.serial_number.strip()
        if serial:
            return f"{self.format_device_label(normalized)} [{serial}]"
        return self.format_device_label(normalized)

    def _log_decoded_message(
        self,
        msg: MaxMessage,
        decoded: ThermostatState | ShutterContactState | None,
    ) -> None:
        """Emit a readable info log for decoded incoming MAX! telegrams."""
        label = self._format_device_identity(msg.src_hex)
        if isinstance(decoded, ThermostatState):
            _LOGGER.info(
                "RX %s from %s: mode=%s desired=%.1f current=%s valve=%s%% group=%d battery_low=%s rf_error=%s",
                "WallThermostatState" if msg.msg_type == 0x70 else "ThermostatState",
                label,
                MODE_NAMES.get(decoded.mode, decoded.mode),
                decoded.desired_temperature,
                (
                    f"{decoded.measured_temperature:.1f}"
                    if decoded.measured_temperature is not None
                    else "n/a"
                ),
                decoded.valve_position,
                msg.group,
                decoded.battery_low,
                decoded.rf_error,
            )
            return
        if isinstance(decoded, ShutterContactState):
            _LOGGER.info(
                "RX ShutterContactState from %s: is_open=%s group=%d battery_low=%s rf_error=%s",
                label,
                decoded.is_open,
                msg.group,
                decoded.battery_low,
                decoded.rf_error,
            )
            return
        if msg.msg_type == MSG_ACK:
            _LOGGER.info("RX ACK from %s: counter=%d group=%d", label, msg.counter, msg.group)

    def export_topology(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the current MAX! topology."""
        devices: list[dict[str, Any]] = []
        for device in sorted(self._devices.values(), key=lambda entry: entry.address):
            profile_hex = device.week_profile.lower() if device.week_profile else ""
            devices.append(
                {
                    "address": device.address,
                    "device_type": device.device_type,
                    "device_type_name": DEVICE_TYPE_NAMES.get(device.device_type, "Unbekannt"),
                    "name": device.name,
                    "serial_number": device.serial_number,
                    "firmware_version": device.firmware_version,
                    "paired": device.paired,
                    "is_virtual": device.is_virtual,
                    "group_id": device.group_id,
                    "linked_partners": sorted(dict.fromkeys(device.linked_partners)),
                    "comfort_temperature": device.comfort_temperature,
                    "eco_temperature": device.eco_temperature,
                    "maximum_temperature": device.maximum_temperature,
                    "minimum_temperature": device.minimum_temperature,
                    "measurement_offset": device.measurement_offset,
                    "window_open_temperature": device.window_open_temperature,
                    "window_open_duration": device.window_open_duration,
                    "week_profile": profile_hex,
                    "week_profile_lines": format_week_profile_lines(profile_hex) if profile_hex else [],
                    "last_state": device.last_state,
                }
            )

        return {
            "schema_version": 1,
            "exported_at": datetime.now(UTC).isoformat(),
            "own_address": f"{self.own_address:06X}",
            "device_count": len(devices),
            "devices": devices,
        }

    def _resolve_topology_path(self, path: str | None) -> Path:
        """Resolve a topology JSON path relative to the HA config directory."""
        raw_path = (path or "cul_max_topology.json").strip()
        resolved = Path(raw_path)
        if not resolved.is_absolute():
            resolved = Path(self.hass.config.path(raw_path))
        return resolved

    async def async_export_topology_to_file(self, path: str | None = None) -> str:
        """Write the current topology snapshot to a JSON file."""
        resolved_path = self._resolve_topology_path(path)
        snapshot = self.export_topology()
        await self.hass.async_add_executor_job(
            self._write_topology_file,
            resolved_path,
            snapshot,
        )
        return str(resolved_path)

    async def async_load_topology_from_file(self, path: str) -> dict[str, Any]:
        """Load a topology snapshot from a JSON file."""
        resolved_path = self._resolve_topology_path(path)
        return await self.hass.async_add_executor_job(self._read_topology_file, resolved_path)

    @staticmethod
    def _write_topology_file(path: Path, payload: dict[str, Any]) -> None:
        """Persist one topology snapshot to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _read_topology_file(path: Path) -> dict[str, Any]:
        """Read one topology snapshot from disk."""
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _normalize_topology_devices(topology: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize supported topology JSON variants into a flat device list."""
        raw_devices = topology.get("devices")
        if isinstance(raw_devices, list):
            normalized = []
            for entry in raw_devices:
                if isinstance(entry, dict):
                    normalized.append(dict(entry))
            return normalized
        if isinstance(raw_devices, dict):
            normalized = []
            for address, entry in raw_devices.items():
                if not isinstance(entry, dict):
                    continue
                normalized.append({"address": address, **entry})
            return normalized
        raise ValueError("Topologie-JSON enthaelt keine gueltige 'devices'-Liste.")

    async def async_import_topology(
        self,
        topology: dict[str, Any],
        *,
        create_virtual_devices: bool = True,
        update_names: bool = True,
        apply_group_ids: bool = True,
        apply_links: bool = True,
        apply_week_profiles: bool = True,
    ) -> dict[str, Any]:
        """Import a MAX! topology snapshot into the current coordinator state."""
        if not isinstance(topology, dict):
            raise ValueError("Topologie muss ein JSON-Objekt sein.")

        entries = self._normalize_topology_devices(topology)
        if not entries:
            raise ValueError("Topologie enthaelt keine Geraete.")

        normalized_entries: list[dict[str, Any]] = []
        seen_addresses: set[str] = set()
        for entry in entries:
            address = str(entry.get("address", "")).upper()
            if len(address) != 6 or any(ch not in "0123456789ABCDEF" for ch in address):
                raise ValueError(f"Ungueltige Geraeteadresse im Import: {address or entry!r}")
            if address in seen_addresses:
                raise ValueError(f"Doppelte Geraeteadresse im Import: {address}")
            seen_addresses.add(address)
            normalized_entries.append({**entry, "address": address})

        created_virtual_addresses: list[str] = []
        updated_device_addresses: list[str] = []
        group_updates = 0
        week_profile_updates = 0
        link_updates = 0
        skipped_devices: list[str] = []

        for entry in normalized_entries:
            address = entry["address"]
            device = self.get_device(address)
            is_virtual = bool(entry.get("is_virtual", False))
            if device is not None or not is_virtual:
                continue
            if not create_virtual_devices:
                skipped_devices.append(address)
                continue
            device_type = int(entry.get("device_type", DEVICE_SHUTTER_CONTACT))
            if device_type != DEVICE_SHUTTER_CONTACT:
                skipped_devices.append(address)
                _LOGGER.warning(
                    "Skipping unsupported virtual device import for %s with type %s",
                    address,
                    device_type,
                )
                continue
            await self.async_create_virtual_shutter_contact(
                address,
                str(entry.get("name") or f"Virtuelles Geraet {address}"),
                int(entry.get("group_id", 0) or 0),
            )
            created_virtual_addresses.append(address)

        metadata_changed = False
        for entry in normalized_entries:
            address = entry["address"]
            device = self.get_device(address)
            if device is None:
                skipped_devices.append(address)
                continue

            device_changed = False
            snapshot_name = str(entry.get("name", "")).strip()
            if update_names and snapshot_name and device.name != snapshot_name:
                device.name = snapshot_name
                metadata_changed = True
                device_changed = True

            serial_number = _sanitize_serial_number(str(entry.get("serial_number", "")))
            if serial_number and device.serial_number != serial_number:
                device.serial_number = serial_number
                metadata_changed = True
                device_changed = True

            firmware_version = str(entry.get("firmware_version", "")).strip()
            if firmware_version and device.firmware_version != firmware_version:
                device.firmware_version = firmware_version
                metadata_changed = True
                device_changed = True

            if device_changed and address not in updated_device_addresses:
                updated_device_addresses.append(address)

        if metadata_changed:
            await self._save_devices()

        if apply_group_ids:
            for entry in normalized_entries:
                address = entry["address"]
                device = self.get_device(address)
                if device is None:
                    continue
                desired_group_id = int(entry.get("group_id", 0) or 0)
                if desired_group_id == device.group_id:
                    continue
                if desired_group_id > 0:
                    await self.async_set_group_id(address, desired_group_id)
                else:
                    await self.async_remove_group_id(address)
                group_updates += 1
                await asyncio.sleep(0.15)

        if apply_week_profiles:
            for entry in normalized_entries:
                address = entry["address"]
                device = self.get_device(address)
                if device is None or device.device_type not in CLIMATE_DEVICE_TYPES:
                    continue
                desired_profile = str(entry.get("week_profile", "")).strip().lower()
                if not desired_profile or desired_profile == device.week_profile.lower():
                    continue
                profile_lines = format_week_profile_lines(desired_profile)
                await self.async_set_week_profile(address, "\n".join(profile_lines))
                week_profile_updates += 1
                await asyncio.sleep(0.15)

        if apply_links:
            for entry in normalized_entries:
                address = entry["address"]
                device = self.get_device(address)
                if device is None:
                    continue
                desired_partners = []
                for partner_address in entry.get("linked_partners", []) or []:
                    partner = str(partner_address).upper()
                    if partner == address:
                        continue
                    if self.get_device(partner) is None:
                        _LOGGER.warning(
                            "Skipping link import %s -> %s because partner is unknown",
                            address,
                            partner,
                        )
                        continue
                    desired_partners.append(partner)

                for partner in dict.fromkeys(desired_partners):
                    if partner in device.linked_partners:
                        continue
                    await self.async_add_link_partner(address, partner)
                    link_updates += 1
                    await asyncio.sleep(0.15)

        return {
            "imported_devices": sorted(seen_addresses - set(skipped_devices)),
            "created_virtual_addresses": created_virtual_addresses,
            "updated_device_addresses": updated_device_addresses,
            "group_updates": group_updates,
            "week_profile_updates": week_profile_updates,
            "link_updates": link_updates,
            "skipped_devices": sorted(dict.fromkeys(skipped_devices)),
        }

    async def _merge_thermostat_state(
        self,
        address: str,
        partial: dict[str, Any],
        *,
        keep_missing_measurement: bool,
    ) -> ThermostatState:
        """Merge a (partial) thermostat state into last_state; return the full state."""
        update = dict(partial)
        update.pop("address", None)
        if keep_missing_measurement:
            for key in ("measured_temperature", "heater_temperature"):
                if update.get(key) is None:
                    update.pop(key, None)
        mode = update.get("mode")
        if mode is not None:
            if mode != MODE_VACATION:
                update.setdefault("until", None)
            if mode != MODE_BOOST:
                update.setdefault("boost_duration", None)
        device = self._devices.get(address)
        if device is None:
            return thermostat_state_from_dict(address, update)
        new_target = update.get("desired_temperature")
        if new_target is not None and new_target != device.last_state.get("desired_temperature"):
            device.last_target_change_at = datetime.now(UTC).isoformat()
        await self._update_device_state(address, update)
        return thermostat_state_from_dict(address, device.last_state)

    async def _update_device_state(self, address: str, state: dict) -> None:
        if address in self._devices:
            self._devices[address].last_state = {
                **self._devices[address].last_state,
                **state,
            }
            await self._save_devices()
            self._notify_diagnostics_updated(address)

    async def _touch_device(self, address: str) -> None:
        """Persist the timestamp of the last RF contact for a device."""
        device = self._devices.get(address.upper())
        if device is None:
            return
        device.last_seen = datetime.now(UTC).isoformat()
        await self._save_devices()
        self._notify_diagnostics_updated(address)

    async def _mark_command_success(
        self,
        address: str,
        *,
        retries: int,
        ack_at: str | None,
    ) -> None:
        """Persist successful command execution diagnostics."""
        device = self._devices.get(address.upper())
        if device is None:
            return
        device.last_command_success_at = datetime.now(UTC).isoformat()
        device.last_command_retries = retries
        device.total_retry_count += retries
        device.last_send_error = ""
        device.last_send_error_at = ""
        if ack_at is not None:
            device.last_ack_at = ack_at
        await self._save_devices()
        self._notify_diagnostics_updated(address)

    async def _mark_command_error(
        self,
        address: str,
        error_message: str,
        *,
        retries: int,
    ) -> None:
        """Persist failed command execution diagnostics."""
        device = self._devices.get(address.upper())
        if device is None:
            return
        device.last_send_error = error_message
        device.last_send_error_at = datetime.now(UTC).isoformat()
        device.last_command_retries = retries
        device.total_retry_count += retries
        await self._save_devices()
        self._notify_diagnostics_updated(address)

    async def _update_device_group(self, address: str, group_id: int) -> None:
        """Persist the last group ID seen from the device header."""
        if address not in self._devices:
            return
        # Many regular status telegrams still arrive with group header 0 even
        # after a room/group assignment was configured successfully. Do not
        # clobber an already known non-zero group with such telemetry. Real
        # group removals are handled explicitly via the write path.
        if group_id == 0 and self._devices[address].group_id > 0:
            return
        if self._devices[address].group_id == group_id:
            return
        self._devices[address].group_id = group_id
        await self._save_devices()
        self._notify_diagnostics_updated(address)

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    @callback
    def add_listener(self, address: str, cb: Callable) -> Callable:
        """Register a callback for messages from one specific device."""
        addr = address.upper()
        self._listeners.setdefault(addr, []).append(cb)
        def remove() -> None:
            self._listeners.get(addr, []).remove(cb)
        return remove

    @callback
    def add_global_listener(self, cb: Callable) -> Callable:
        """Register a callback for all incoming messages."""
        self._global_listeners.append(cb)
        def remove() -> None:
            self._global_listeners.remove(cb)
        return remove

    @callback
    def add_week_profile_listener(self, address: str, cb: Callable[[], None]) -> Callable:
        """Register a callback for week profile changes of one device."""
        addr = address.upper()
        self._week_profile_listeners.setdefault(addr, []).append(cb)

        def remove() -> None:
            self._week_profile_listeners.get(addr, []).remove(cb)

        return remove

    @callback
    def add_diagnostic_listener(self, address: str, cb: Callable[[], None]) -> Callable:
        """Register a callback for diagnostic changes of one device."""
        addr = address.upper()
        self._diagnostic_listeners.setdefault(addr, []).append(cb)

        def remove() -> None:
            self._diagnostic_listeners.get(addr, []).remove(cb)

        return remove

    @callback
    def add_pairing_state_listener(self, cb: Callable[[], None]) -> Callable:
        """Register a callback for integration-wide pairing mode changes."""
        self._pairing_state_listeners.append(cb)

        def remove() -> None:
            self._pairing_state_listeners.remove(cb)

        return remove

    @callback
    def _notify_diagnostics_updated(self, address: str) -> None:
        """Notify listeners that diagnostic data for a device changed."""
        addr = address.upper()
        for cb in self._diagnostic_listeners.get(addr, []):
            self.hass.loop.call_soon(cb)

    @callback
    def _notify_pairing_state_updated(self) -> None:
        """Notify listeners that the integration pairing state changed."""
        for cb in self._pairing_state_listeners:
            self.hass.loop.call_soon(cb)

    @callback
    def _notify_week_profile_updated(self, address: str) -> None:
        """Notify listeners that a device week profile changed."""
        addr = address.upper()
        for cb in self._week_profile_listeners.get(addr, []):
            self.hass.loop.call_soon(cb)

    def _resume_pending_config_processing(self) -> None:
        """Resume persisted pending config queues after startup or reconnect."""
        for address in self._pending_shutter_config:
            self._notify_diagnostics_updated(address)
            if self._is_recently_seen(address):
                self._schedule_shutter_config_processing(
                    address,
                    trigger="restore_recent_activity",
                )
        for address in self._pending_climate_config:
            self._notify_diagnostics_updated(address)
            self._schedule_climate_config_processing(address, trigger="restore")

    @property
    def is_pairing_mode(self) -> bool:
        """Return whether the integration is currently in pairing mode."""
        return self._pairing_mode

    @property
    def pairing_until(self) -> datetime | None:
        """Return when the current pairing window ends, if active."""
        return self._pairing_until

    def get_pairing_remaining_seconds(self) -> int:
        """Return remaining pairing window duration in whole seconds."""
        if not self._pairing_mode or self._pairing_until is None:
            return 0
        return max(0, int((self._pairing_until - datetime.now(UTC)).total_seconds()))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _load_devices(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        data, migrated = self._migrate_storage_data(data)
        changed = migrated
        self._pending_shutter_config = {}
        self._pending_climate_config = {}
        for addr, d in data.get("devices", {}).items():
            device_type = d["device_type"]
            firmware_version = d.get("firmware_version", "")
            serial_number = _sanitize_serial_number(d.get("serial_number", ""))
            stored_name = str(d.get("name", "")).strip()
            # Repair devices that were stored with the old PairPing offset bug:
            # e.g. device_type=16 and firmware_version="3" for a wall thermostat.
            if (
                device_type not in DEVICE_TYPE_NAMES
                and firmware_version.isdigit()
                and int(firmware_version) in DEVICE_TYPE_NAMES
            ):
                _LOGGER.info(
                    "Repairing stored MAX! device type for %s: %s -> %s",
                    addr,
                    device_type,
                    firmware_version,
                )
                device_type = int(firmware_version)
                firmware_version = ""
                changed = True

            if _is_legacy_auto_name(stored_name, device_type, addr):
                migrated_name = _default_device_name(device_type, addr, serial_number)
                if stored_name != migrated_name:
                    _LOGGER.info(
                        "Updating legacy auto-name for %s: '%s' -> '%s'",
                        addr,
                        stored_name,
                        migrated_name,
                    )
                    stored_name = migrated_name
                    changed = True

            self._devices[addr] = KnownDevice(
                address=d["address"],
                device_type=device_type,
                name=stored_name,
                serial_number=serial_number,
                firmware_version=firmware_version,
                paired=bool(d.get("paired", bool(serial_number or firmware_version or d.get("is_virtual", False)))),
                last_seen=d.get("last_seen", ""),
                last_ack_at=d.get("last_ack_at", ""),
                last_command_success_at=d.get("last_command_success_at", ""),
                last_send_error=d.get("last_send_error", ""),
                last_send_error_at=d.get("last_send_error_at", ""),
                last_command_retries=d.get("last_command_retries", 0),
                total_retry_count=d.get("total_retry_count", 0),
                is_virtual=d.get("is_virtual", False),
                group_id=d.get("group_id", 0),
                linked_partners=d.get("linked_partners", []),
                superseded_by=d.get("superseded_by", ""),
                duplicate_reason=d.get("duplicate_reason", ""),
                pending_config=[],
                last_command=d.get("last_command", ""),
                week_profile=d.get("week_profile", ""),
                comfort_temperature=float(d.get("comfort_temperature", 21.0)),
                eco_temperature=float(d.get("eco_temperature", 17.0)),
                maximum_temperature=float(d.get("maximum_temperature", 30.5)),
                minimum_temperature=float(d.get("minimum_temperature", 4.5)),
                measurement_offset=float(d.get("measurement_offset", 0.0)),
                window_open_temperature=float(d.get("window_open_temperature", 12.0)),
                window_open_duration=int(d.get("window_open_duration", 15)),
                last_state=d.get("last_state", {}),
                last_time_sync_at=d.get("last_time_sync_at", ""),
                last_reported_time=d.get("last_reported_time", ""),
                last_time_offset_seconds=d.get("last_time_offset_seconds"),
                time_slot=int(d.get("time_slot", -1)),
                foreign_central=str(d.get("foreign_central", "") or ""),
                foreign_central_seen_at=str(d.get("foreign_central_seen_at", "") or ""),
                last_central_contact_at=str(d.get("last_central_contact_at", "") or ""),
                external_sensor=str(d.get("external_sensor", "") or ""),
                last_target_change_at=str(d.get("last_target_change_at", "") or ""),
                week_profile_days=[
                    int(x) for x in (d.get("week_profile_days") or []) if str(x).isdigit() and 0 <= int(x) <= 6
                ],
            )
        for addr, commands in data.get("pending_shutter_config", {}).items():
            normalized = addr.upper()
            restored = [
                _deserialize_pending_shutter_command(command)
                for command in commands or []
                if isinstance(command, dict) and command.get("op") and command.get("description")
            ]
            if restored:
                self._pending_shutter_config[normalized] = restored
        for addr, commands in data.get("pending_climate_config", {}).items():
            normalized = addr.upper()
            restored = [
                _deserialize_pending_climate_command(command)
                for command in commands or []
                if isinstance(command, dict) and command.get("op") and command.get("description")
            ]
            if restored:
                self._pending_climate_config[normalized] = restored
        stored_vacation = data.get("vacation")
        if isinstance(stored_vacation, dict):
            self._vacation = {**_default_vacation_state(), **stored_vacation}
            if not isinstance(self._vacation.get("devices"), dict):
                self._vacation["devices"] = {}
        _LOGGER.info("Loaded %d known MAX! devices from storage", len(self._devices))
        for address in self._devices:
            await self._sync_device_registry_entry(address)
        for address in {
            *self._pending_shutter_config.keys(),
            *self._pending_climate_config.keys(),
        }:
            now_iso = self._now_iso()
            for command in self._pending_shutter_config.get(address, []):
                if not command.queued_at:
                    command.queued_at = now_iso
            for command in self._pending_climate_config.get(address, []):
                if not command.queued_at:
                    command.queued_at = now_iso
            await self._sync_pending_config_reading(address)
        if changed:
            await self._save_devices()

    async def _save_devices(self) -> None:
        """Schedule a debounced write of the device store.

        Called on nearly every received telegram (last_seen, state, ACK
        diagnostics). Writing synchronously each time stalled the RX loop on
        slow storage; HA's delayed save coalesces writes and flushes on stop.
        """
        self._store.async_delay_save(self._build_storage_data, STORAGE_SAVE_DELAY)

    async def _save_devices_now(self) -> None:
        """Write the device store immediately."""
        await self._store.async_save(self._build_storage_data())

    def _build_storage_data(self) -> dict[str, Any]:
        """Return the serialized device store."""
        data = {
            "schema_version": STORAGE_SCHEMA_VERSION,
            "devices": {
                addr: {
                    "address": d.address,
                    "device_type": d.device_type,
                    "name": d.name,
                    "serial_number": d.serial_number,
                    "firmware_version": d.firmware_version,
                    "paired": d.paired,
                    "last_seen": d.last_seen,
                    "last_ack_at": d.last_ack_at,
                    "last_command_success_at": d.last_command_success_at,
                    "last_send_error": d.last_send_error,
                    "last_send_error_at": d.last_send_error_at,
                    "last_command_retries": d.last_command_retries,
                    "total_retry_count": d.total_retry_count,
                    "is_virtual": d.is_virtual,
                    "group_id": d.group_id,
                    "linked_partners": d.linked_partners,
                    "superseded_by": d.superseded_by,
                    "duplicate_reason": d.duplicate_reason,
                    "last_command": d.last_command,
                    "week_profile": d.week_profile,
                    "comfort_temperature": d.comfort_temperature,
                    "eco_temperature": d.eco_temperature,
                    "maximum_temperature": d.maximum_temperature,
                    "minimum_temperature": d.minimum_temperature,
                    "measurement_offset": d.measurement_offset,
                    "window_open_temperature": d.window_open_temperature,
                    "window_open_duration": d.window_open_duration,
                    "last_state": d.last_state,
                    "last_time_sync_at": d.last_time_sync_at,
                    "last_reported_time": d.last_reported_time,
                    "last_time_offset_seconds": d.last_time_offset_seconds,
                    "time_slot": d.time_slot,
                    "foreign_central": d.foreign_central,
                    "foreign_central_seen_at": d.foreign_central_seen_at,
                    "last_central_contact_at": d.last_central_contact_at,
                    "external_sensor": d.external_sensor,
                    "last_target_change_at": d.last_target_change_at,
                    "week_profile_days": d.week_profile_days,
                }
                for addr, d in self._devices.items()
            },
            "pending_shutter_config": {
                addr: [
                    _serialize_pending_shutter_command(command)
                    for command in commands
                ]
                for addr, commands in self._pending_shutter_config.items()
                if commands
            },
            "pending_climate_config": {
                addr: [
                    _serialize_pending_climate_command(command)
                    for command in commands
                ]
                for addr, commands in self._pending_climate_config.items()
                if commands
            },
            "vacation": self._vacation,
        }
        return data
