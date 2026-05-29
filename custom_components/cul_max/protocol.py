"""
MAX! / MORITZ protocol implementation for CUL serial communication.

Message format (Z-prefix, received from CULFW):
  Z{LL}{CC}{FF}{TT}{SSSSSS}{DDDDDD}{GG}{PAYLOAD}
  Z         - prefix character
  LL        - length of remaining packet bytes (2 hex chars)
  CC        - message counter (2 hex chars)
  FF        - flags (2 hex chars)
  TT        - message type (2 hex chars)
  SSSSSS    - source address (6 hex chars = 3 bytes)
  DDDDDD    - destination address (6 hex chars = 3 bytes)
  GG        - group ID (2 hex chars)
  PAYLOAD   - variable length hex string

Reference: hobbyquaker/cul moritz.js, FHEM 10_MAX.pm, FHEM 10_CUL_MAX.pm
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any

from .const import (
    DEFAULT_WEEK_PROFILE,
    DEVICE_HEATING_THERMOSTAT,
    DEVICE_HEATING_THERMOSTAT_PLUS,
    DEVICE_SHUTTER_CONTACT,
    DEVICE_WALL_THERMOSTAT,
    MODE_AUTO,
    MODE_BOOST,
    MODE_MANUAL,
    MODE_NAMES,
    MSG_ACK,
    MSG_PAIR_PING,
    MSG_TIME_INFORMATION,
    MSG_SHUTTER_CONTACT_STATE,
    MSG_THERMOSTAT_STATE,
    MSG_WALL_THERMOSTAT_CONTROL,
    MSG_WALL_THERMOSTAT_STATE,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_OFF,
    TEMP_ON,
)

_LOGGER = logging.getLogger(__name__)

WEEK_PROFILE_DAY_MAP = {
    "sat": 0,
    "sa": 0,
    "samstag": 0,
    "sun": 1,
    "so": 1,
    "sonntag": 1,
    "mon": 2,
    "mo": 2,
    "montag": 2,
    "tue": 3,
    "tu": 3,
    "di": 3,
    "dienstag": 3,
    "wed": 4,
    "we": 4,
    "mi": 4,
    "mittwoch": 4,
    "thu": 5,
    "th": 5,
    "do": 5,
    "donnerstag": 5,
    "fri": 6,
    "fr": 6,
    "freitag": 6,
}

WEEK_PROFILE_DAY_NAMES = {
    0: "Sat",
    1: "Sun",
    2: "Mon",
    3: "Tue",
    4: "Wed",
    5: "Thu",
    6: "Fri",
}


def format_display_temperature(temp: float) -> str:
    """Render temperatures compactly for UI display."""
    return str(int(temp)) if float(temp).is_integer() else f"{temp:.1f}"


def local_datetime_to_max_day(when: datetime) -> int:
    """Convert Python weekday numbering to MAX! internal Saturday-first numbering."""
    return (when.weekday() + 2) % 7


@dataclass
class MaxMessage:
    """Parsed MAX! radio message."""
    raw: str
    length: int
    counter: int
    flags: int
    msg_type: int
    src: int       # source address as integer
    dst: int       # destination address as integer
    group: int
    payload: bytes

    @property
    def src_hex(self) -> str:
        return f"{self.src:06X}"

    @property
    def dst_hex(self) -> str:
        return f"{self.dst:06X}"

    @property
    def battery_low(self) -> bool:
        return bool(self.flags & 0x80)

    @property
    def rf_error(self) -> bool:
        return bool(self.flags & 0x40)


@dataclass
class ThermostatState:
    """Decoded thermostat state."""
    address: str
    mode: int
    battery_low: bool
    rf_error: bool
    panel_locked: bool
    gateway_known: bool
    dst_active: bool
    valve_position: int         # 0-100 %
    desired_temperature: float  # °C
    measured_temperature: float | None  # °C, None if not available
    boost_duration: int | None  # minutes, only in boost mode
    display_actual_temperature: bool | None = None
    heater_temperature: float | None = None
    until: str | None = None


@dataclass
class ShutterContactState:
    """Decoded shutter/window contact state."""
    address: str
    is_open: bool
    battery_low: bool
    rf_error: bool


def normalize_week_profile_hex(profile_hex: str | None) -> str:
    """Return a normalized 364-char hex week profile or the default profile."""
    if not profile_hex:
        return DEFAULT_WEEK_PROFILE
    profile_hex = profile_hex.strip().lower()
    if len(profile_hex) != 4 * 13 * 7:
        return DEFAULT_WEEK_PROFILE
    if any(ch not in "0123456789abcdef" for ch in profile_hex):
        return DEFAULT_WEEK_PROFILE
    return profile_hex


def parse_week_profile_text(profile_text: str) -> dict[int, list[tuple[float, int]]]:
    """
    Parse a FHEM-like week profile text into per-day schedules.

    Format per line:
      Mon 21,06:00,17,22:00,16

    Meaning:
      21.0 °C from 00:00-06:00, 17.0 °C from 06:00-22:00, 16.0 °C until 24:00.
    """
    updates: dict[int, list[tuple[float, int]]] = {}
    for raw_line in profile_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Ungueltige Zeile '{line}'. Erwartet: Tag und Profil.")

        day_key = parts[0].strip().lower()
        if day_key not in WEEK_PROFILE_DAY_MAP:
            raise ValueError(f"Unbekannter Tag '{parts[0]}'.")
        day = WEEK_PROFILE_DAY_MAP[day_key]

        tokens = [token.strip() for token in parts[1].split(",") if token.strip()]
        if len(tokens) < 1 or len(tokens) % 2 == 0:
            raise ValueError(
                f"Ungueltiges Profil fuer {parts[0]}. Format: temp,HH:MM,temp,HH:MM,temp"
            )

        schedule: list[tuple[float, int]] = []
        end_times: list[int] = []
        for idx, token in enumerate(tokens):
            if idx % 2 == 0:
                schedule.append((parse_max_temperature(token), 24 * 60))
            else:
                end_minute = parse_week_profile_time(token)
                end_times.append(end_minute)

        last_end = 0
        for idx, end_minute in enumerate(end_times):
            if end_minute <= last_end:
                raise ValueError(
                    f"Schaltzeiten fuer {parts[0]} muessen streng aufsteigend sein."
                )
            schedule[idx] = (schedule[idx][0], end_minute)
            last_end = end_minute

        schedule[-1] = (schedule[-1][0], 24 * 60)
        if len(schedule) > 13:
            raise ValueError(f"Zu viele Schaltpunkte fuer {parts[0]} (maximal 13).")

        updates[day] = schedule

    if not updates:
        raise ValueError("Kein Wochenprofil uebergeben.")

    return updates


def parse_max_temperature(value: str) -> float:
    """Parse a MAX! temperature token."""
    lowered = value.strip().lower()
    if lowered == "off":
        return TEMP_OFF
    if lowered == "on":
        return TEMP_ON
    try:
        temp = float(lowered)
    except ValueError as err:
        raise ValueError(f"Ungueltige Temperatur '{value}'.") from err
    if temp < TEMP_MIN or temp > TEMP_MAX or (temp * 2) % 1 != 0:
        raise ValueError(
            f"Temperatur '{value}' ist ungueltig. Erlaubt sind 4.5 bis 30.5 in 0.5-Schritten."
        )
    return temp


def parse_measurement_offset(value: float | str) -> float:
    """Parse a MAX! measurement offset token."""
    try:
        offset = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"Ungueltiger Temperatur-Offset '{value}'.") from err
    if offset < -3.5 or offset > 3.5 or (offset * 2) % 1 != 0:
        raise ValueError(
            f"Offset '{value}' ist ungueltig. Erlaubt sind -3.5 bis 3.5 in 0.5-Schritten."
        )
    return offset


def parse_window_open_duration(value: int | str) -> int:
    """Parse a MAX! window-open duration in minutes."""
    try:
        duration = int(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"Ungueltige Fenster-offen-Dauer '{value}'.") from err
    if duration < 0 or duration > 60:
        raise ValueError("Fenster-offen-Dauer muss zwischen 0 und 60 Minuten liegen.")
    if duration % 5 != 0:
        raise ValueError("Fenster-offen-Dauer muss in 5-Minuten-Schritten angegeben werden.")
    return duration


def parse_time_information_payload(payload: bytes) -> datetime | None:
    """Parse a MAX! TimeInformation payload into a local naive datetime."""
    if len(payload) < 5:
        return None
    try:
        year = payload[0] + 2000
        day = payload[1]
        hour = payload[2] & 0x1F
        minute = payload[3] & 0x3F
        second = payload[4] & 0x3F
        month = ((payload[3] >> 6) << 2) | (payload[4] >> 6)
        if month < 1 or month > 12:
            return None
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def parse_week_profile_time(value: str) -> int:
    """Parse a HH:MM time into minutes since midnight."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match:
        raise ValueError(f"Ungueltige Zeit '{value}'. Erwartet HH:MM.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour == 24 and minute == 0:
        return 24 * 60
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Ungueltige Zeit '{value}'.")
    if minute % 5 != 0:
        raise ValueError(f"Zeit '{value}' ist ungueltig. MAX! nutzt 5-Minuten-Schritte.")
    return hour * 60 + minute


def encode_week_profile(updates: dict[int, list[tuple[float, int]]], base_hex: str | None = None) -> str:
    """Merge updated days into a full MAX! week profile hex string."""
    profile_hex = normalize_week_profile_hex(base_hex)
    days = [profile_hex[idx * 52:(idx + 1) * 52] for idx in range(7)]
    for day, schedule in updates.items():
        days[day] = encode_week_profile_day(schedule)
    return "".join(days)


def encode_week_profile_day(schedule: list[tuple[float, int]]) -> str:
    """Encode one day of a MAX! week profile to 52 hex chars."""
    encoded_points: list[str] = []
    for temp, end_minute in schedule:
        encoded_points.append(encode_week_profile_point(temp, end_minute))

    while len(encoded_points) < 13:
        # FHEM fills all unused trailing control points with the neutral default
        # value 0x4520 instead of repeating the final real day temperature.
        encoded_points.append("4520")

    if len(encoded_points) != 13:
        raise ValueError("Ein Tagesprofil muss zwischen 1 und 13 Schaltpunkten enthalten.")

    return "".join(encoded_points)


def encode_week_profile_point(temp: float, end_minute: int) -> str:
    """Encode one MAX! week profile control point."""
    if end_minute < 0 or end_minute > 24 * 60 or end_minute % 5 != 0:
        raise ValueError("Schaltzeiten muessen zwischen 00:00 und 24:00 in 5-Minuten-Schritten liegen.")
    temp = parse_max_temperature(str(temp))
    # FHEM/Homegear encode 24:00 as slot 288 (0x120), not as 0.
    encoded_time = end_minute // 5
    encoded_temp = int(temp * 2) & 0x3F
    value = (encoded_temp << 9) | encoded_time
    return f"{value:04x}"


def split_week_profile_for_send(profile_hex: str, day: int) -> list[tuple[int, str]]:
    """Split one day profile into the two ConfigWeekProfile payload chunks."""
    day_hex = normalize_week_profile_hex(profile_hex)[day * 52:(day + 1) * 52]
    chunks: list[tuple[int, str]] = [(0, day_hex[:28])]
    second_chunk = day_hex[28:]
    if second_chunk != "4520" * 6:
        chunks.append((1, second_chunk))
    return chunks


def format_week_profile_lines(profile_hex: str) -> list[str]:
    """Return a readable FHEM-like line per day from a MAX! week profile hex string."""
    profile_hex = normalize_week_profile_hex(profile_hex)
    lines: list[str] = []
    for day in range(7):
        day_hex = profile_hex[day * 52:(day + 1) * 52]
        entries: list[str] = []
        reached_day_end = False
        for idx in range(13):
            value = int(day_hex[idx * 4:(idx + 1) * 4], 16)
            end_slot = value & 0x1FF
            end_minute = end_slot * 5
            temp = ((value >> 9) & 0x3F) / 2.0
            if reached_day_end:
                break
            entries.append(format_display_temperature(temp))
            if end_minute != 24 * 60:
                entries.append(f"{end_minute // 60:02d}:{end_minute % 60:02d}")
            else:
                # The first 24:00 control point is semantically part of the user
                # profile and must stay visible in editable text form, even if the
                # following filler slots repeat the same temperature.
                reached_day_end = True
        lines.append(f"{WEEK_PROFILE_DAY_NAMES[day]} " + ",".join(entries))
    return lines


def format_week_profile_by_day(profile_hex: str) -> dict[str, str]:
    """Return readable week profile strings keyed by lowercase day name."""
    lines = format_week_profile_lines(profile_hex)
    return {
        "saturday": lines[0].removeprefix("Sat ").strip(),
        "sunday": lines[1].removeprefix("Sun ").strip(),
        "monday": lines[2].removeprefix("Mon ").strip(),
        "tuesday": lines[3].removeprefix("Tue ").strip(),
        "wednesday": lines[4].removeprefix("Wed ").strip(),
        "thursday": lines[5].removeprefix("Thu ").strip(),
        "friday": lines[6].removeprefix("Fri ").strip(),
    }


def get_expected_week_profile_temperature(
    profile_hex: str,
    when: datetime | None = None,
) -> float | None:
    """Return the temperature from the stored week profile that should be active now."""
    if not profile_hex:
        return None
    local_when = (when or datetime.now().astimezone()).astimezone()
    day = local_datetime_to_max_day(local_when)
    day_hex = normalize_week_profile_hex(profile_hex)[day * 52:(day + 1) * 52]
    day_minutes = (local_when.hour * 60) + local_when.minute

    for idx in range(13):
        value = int(day_hex[idx * 4:(idx + 1) * 4], 16)
        end_minute = (value & 0x1FF) * 5
        temp = ((value >> 9) & 0x3F) / 2.0
        if day_minutes < end_minute:
            return temp

    last_value = int(day_hex[48:52], 16)
    return ((last_value >> 9) & 0x3F) / 2.0


def decode_max_until_datetime(byte1: int, byte2: int, byte3: int) -> str | None:
    """Decode the MAX! three-byte until representation into a readable local string."""
    day = byte1 & 0x1F
    month = ((byte1 & 0xE0) >> 4) | (byte2 >> 7)
    year = 2000 + (byte2 & 0x3F)
    slot = byte3 & 0x3F
    hour = slot // 2
    minute = 30 if slot % 2 else 0
    try:
        until = datetime(year, month, day, hour, minute)
    except ValueError:
        return None
    return until.strftime("%Y-%m-%d %H:%M")


def encode_max_until_datetime(until: datetime) -> str:
    """Encode one local datetime into MAX!'s three-byte until representation."""
    local_until = until.astimezone()
    year = local_until.year
    month = local_until.month
    day = local_until.day
    hour = local_until.hour
    minute = local_until.minute
    if year < 2000 or year > 2063:
        raise ValueError("Until-Jahr muss zwischen 2000 und 2063 liegen.")
    if minute not in (0, 30):
        raise ValueError("Until-Zeit muss auf :00 oder :30 liegen.")
    value = (
        ((month & 0xE) << 20)
        | (day << 16)
        | ((month & 0x1) << 15)
        | ((year - 2000) << 8)
        | (hour * 2 + int(minute / 30))
    )
    return f"{value:06X}"


def parse_message(line: str) -> MaxMessage | None:
    """
    Parse a raw CULFW Z-message string into a MaxMessage.
    Line should be the raw string including the leading 'Z'.
    """
    line = line.strip()
    if not line.startswith("Z") or len(line) < 23:
        return None

    try:
        packet_part, _, _suffix = line.partition(" ")
        hex_data = packet_part[1:]  # strip 'Z'
        length  = int(hex_data[0:2],  16)
        counter = int(hex_data[2:4],  16)
        flags   = int(hex_data[4:6],  16)
        msg_type = int(hex_data[6:8], 16)
        src     = int(hex_data[8:14],  16)
        dst     = int(hex_data[14:20], 16)
        group   = int(hex_data[20:22], 16)
        payload = bytes.fromhex(hex_data[22:]) if len(hex_data) > 22 else b""

        return MaxMessage(
            raw=line,
            length=length,
            counter=counter,
            flags=flags,
            msg_type=msg_type,
            src=src,
            dst=dst,
            group=group,
            payload=payload,
        )
    except (ValueError, IndexError) as e:
        _LOGGER.warning("Failed to parse MAX! message '%s': %s", line, e)
        return None


def decode_thermostat_state(msg: MaxMessage) -> ThermostatState | None:
    """
    Decode a ThermostatState (0x60) or WallThermostatState (0x70) message.

    Payload structure (HeatingThermostat):
      Byte 0:  flags2 — bits: [battery_low(7), rf_error(6), panel_lock(5),
                                gateway_known(4), dst(3), test(2), mode(1:0)]
      Byte 1:  valve_position (0-100)
      Byte 2:  desired_temp_raw — (bits 6:0) * 0.5 °C
      Byte 3:  until1 / measured_temp_msb
      Byte 4:  until2 / measured_temp_low
      Byte 5:  until3

    FHEM treats mode 2 as a temporary/until mode. In all other modes, bytes 3+4
    carry the measured temperature as:
      measured = (((byte3 & 0x01) << 8) | byte4) / 10.0

    WallMountedThermostatState uses several payload variants. FHEM handles
    these by length, with optional "display actual temperature", optional
    heater temperature and an optional until-triplet. We follow that layout
    more closely here.
    """
    if msg.msg_type not in (MSG_THERMOSTAT_STATE, MSG_WALL_THERMOSTAT_STATE):
        return None

    payload = msg.payload
    is_wall = msg.msg_type == MSG_WALL_THERMOSTAT_STATE

    if is_wall and len(payload) < 3:
        _LOGGER.warning("WallThermostatState payload too short: %s", msg.raw)
        return None
    if not is_wall and len(payload) < 3:
        _LOGGER.warning("ThermostatState payload too short: %s", msg.raw)
        return None

    try:
        if is_wall:
            flags2 = payload[0]
            display_actual_temperature = bool(payload[1]) if len(payload) > 1 else None
            desired_raw = payload[2] if len(payload) > 2 else 0
            until1 = payload[3] if len(payload) > 3 else None
            heater_temperature_raw = payload[4] if len(payload) > 4 else None
            until3 = payload[5] if len(payload) > 5 else None
            temperature_low = payload[6] if len(payload) > 6 else None
            valve_pos = 0
        else:
            flags2 = payload[0]
            valve_pos = payload[1]
            desired_raw = payload[2]
            until1 = payload[3] if len(payload) > 3 else None
            until2 = payload[4] if len(payload) > 4 else None
            until3 = payload[5] if len(payload) > 5 else None
            display_actual_temperature = None
            heater_temperature_raw = None

        _LOGGER.debug(
            "Thermostat %s payload: flags2=0x%02X, valve=%d, desired_raw=0x%02X",
            msg.src_hex,
            flags2,
            valve_pos,
            desired_raw,
        )

        mode         = flags2 & 0x03
        dst_active   = bool(flags2 & 0x08)
        gateway_known = bool(flags2 & 0x10)
        panel_locked  = bool(flags2 & 0x20)
        rf_error      = bool(flags2 & 0x40)
        battery_low   = bool(flags2 & 0x80)

        desired_temp = (desired_raw & 0x7F) / 2.0
        if desired_temp < TEMP_MIN:
            desired_temp = TEMP_MIN
        if desired_temp > TEMP_MAX:
            desired_temp = TEMP_MAX

        measured_temp = None
        heater_temperature = None
        until = None
        if is_wall:
            if (
                until1 is not None
                and heater_temperature_raw is not None
                and until3 is not None
                and (until1 != 0 or heater_temperature_raw != 0 or until3 != 0)
            ):
                until = decode_max_until_datetime(until1, heater_temperature_raw, until3)
            elif heater_temperature_raw is not None:
                heater_temperature = heater_temperature_raw / 10.0
                if heater_temperature < TEMP_MIN or heater_temperature > 51.1:
                    heater_temperature = None
            if temperature_low is not None:
                measured_temp = ((((desired_raw & 0x80) << 1) | temperature_low) / 10.0)
                if measured_temp < 1.0 or measured_temp > 51.1:
                    measured_temp = None
        else:
            if mode != 2 and until1 is not None and until2 is not None:
                measured_temp = (((until1 & 0x01) << 8) | until2) / 10.0
                if measured_temp < 1.0 or measured_temp > 40:
                    measured_temp = None  # invalid / not yet measured / implausible
            if mode == 2 and until1 is not None and until2 is not None and until3 is not None:
                until = decode_max_until_datetime(until1, until2, until3)

        # _LOGGER.debug("Thermostat %s decoded: desired=%.1f°C (raw=0x%02X), measured=%.1f°C, mode=%d",
        #              msg.src_hex, desired_temp, desired_raw, measured_temp or -1, mode)

        boost_duration = None
        if mode == 3 and len(payload) > (3 if is_wall else 4):
            # boost duration encoded in extra byte
            boost_raw = payload[3 if is_wall else 4]
            boost_duration = (boost_raw >> 5) * 5  # in minutes

        return ThermostatState(
            address=msg.src_hex,
            mode=mode,
            battery_low=battery_low,
            rf_error=rf_error,
            panel_locked=panel_locked,
            gateway_known=gateway_known,
            dst_active=dst_active,
            valve_position=valve_pos,
            desired_temperature=desired_temp,
            measured_temperature=measured_temp,
            boost_duration=boost_duration,
            display_actual_temperature=display_actual_temperature,
            heater_temperature=heater_temperature,
            until=until,
        )
    except (IndexError, ValueError) as e:
        _LOGGER.warning("Failed to decode thermostat state from '%s': %s", msg.raw, e)
        return None


def decode_wall_thermostat_control(msg: MaxMessage) -> ThermostatState | None:
    """
    Decode a WallThermostatControl (0x42) message.

    FHEM encodes/sends this payload as two bytes:
      Byte 0: bit 7 = measured temperature bit 8, bits 6:0 = desired * 2
      Byte 1: measured temperature low 8 bits, value / 10

    Unlike 0x70, the payload does not carry the full thermostat status block,
    so only desired and measured temperature are available reliably.
    """
    if msg.msg_type != MSG_WALL_THERMOSTAT_CONTROL:
        return None

    if len(msg.payload) < 2:
        _LOGGER.warning("WallThermostatControl payload too short: %s", msg.raw)
        return None

    try:
        desired_raw = msg.payload[0]
        measured_low = msg.payload[1]

        desired_temp = (desired_raw & 0x7F) / 2.0
        desired_temp = max(TEMP_MIN, min(TEMP_MAX, desired_temp))

        measured_temp = ((((desired_raw & 0x80) >> 7) << 8) | measured_low) / 10.0
        if measured_temp < TEMP_MIN or measured_temp > 51.1:
            measured_temp = None

        return ThermostatState(
            address=msg.src_hex,
            mode=MODE_MANUAL,
            battery_low=msg.battery_low,
            rf_error=msg.rf_error,
            panel_locked=False,
            gateway_known=False,
            dst_active=bool(msg.flags & 0x04),
            valve_position=0,
            desired_temperature=desired_temp,
            measured_temperature=measured_temp,
            boost_duration=None,
            display_actual_temperature=None,
            heater_temperature=None,
            until=None,
        )
    except (IndexError, ValueError) as e:
        _LOGGER.warning("Failed to decode wall thermostat control from '%s': %s", msg.raw, e)
        return None


def decode_shutter_contact_state(msg: MaxMessage) -> ShutterContactState | None:
    """
    Decode a ShutterContactState (0x30) message.

    Real MAX! contacts encode open/closed in the first payload byte:
      0x10 = closed
      0x12 = open
    RF error and battery low are still reflected in the message flags.
    """
    if msg.msg_type != MSG_SHUTTER_CONTACT_STATE:
        return None

    payload_byte = msg.payload[0] if msg.payload else 0x10
    is_open   = bool(payload_byte & 0x02)
    rf_error  = bool(msg.flags & 0x40)
    bat_low   = bool(msg.flags & 0x80)

    return ShutterContactState(
        address=msg.src_hex,
        is_open=is_open,
        battery_low=bat_low,
        rf_error=rf_error,
    )


def build_shutter_contact_state(
    counter: int,
    src_address: int,
    dst_address: int,
    is_open: bool,
    group_id: int = 0,
) -> str:
    """Build a ShutterContactState (0x30) telegram for a real or virtual contact."""
    if group_id < 0 or group_id > 255:
        raise ValueError("group_id must be in range 0..255")
    payload = "12" if is_open else "10"
    flags = 0x04 if group_id > 0 else 0x06
    inner = (
        f"{counter & 0xFF:02X}"
        f"{flags:02X}"
        f"30"
        f"{src_address:06X}"
        f"{dst_address:06X}"
        f"{group_id & 0xFF:02X}"
        f"{payload}"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_set_temperature(
    counter: int,
    own_address: int,
    dst_address: int,
    temperature: float,
    mode: int = MODE_MANUAL,
    until_hex: str = "",
    group_id: int = 0,
) -> str:
    """
    Build a SetTemperature (0x40) command string for CULFW.

    Payload byte:
      bits 7-6: mode (0=auto, 1=manual, 2=vacation, 3=boost)
      bits 5-0: temperature * 2 (half-degrees)

    Returns a complete CULFW command string ending with \\r\\n.
    """
    if mode == MODE_AUTO and temperature <= 0:
        temp_encoded = 0
    else:
        temperature = max(TEMP_MIN, min(TEMP_MAX, temperature))
        temp_encoded = int(temperature * 2)
    payload_byte = ((mode & 0x03) << 6) | (temp_encoded & 0x3F)
    if until_hex and len(until_hex) != 6:
        raise ValueError("until_hex muss genau 6 Hex-Zeichen lang sein.")
    if group_id < 0 or group_id > 255:
        raise ValueError("group_id must be in range 0..255")
    flags = 0x04 if group_id > 0 else 0x00

    # Build the inner MAX! packet (without length prefix)
    inner = (
        f"{counter & 0xFF:02X}"   # counter
        f"{flags:02X}"             # flags
        f"40"                      # message type SetTemperature
        f"{own_address:06X}"       # source
        f"{dst_address:06X}"       # destination
        f"{group_id & 0xFF:02X}"   # group
        f"{payload_byte:02X}"      # payload
        f"{until_hex.upper()}"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_config_week_profile(
    counter: int,
    own_address: int,
    dst_address: int,
    day: int,
    part: int,
    chunk_hex: str,
) -> str:
    """Build a ConfigWeekProfile (0x10) command for one day chunk."""
    if day < 0 or day > 6:
        raise ValueError("day must be in range 0..6")
    if part not in (0, 1):
        raise ValueError("part must be 0 or 1")
    if len(chunk_hex) not in (24, 28):
        raise ValueError("chunk_hex must encode 6 or 7 control points")

    selector = day | (part << 3)
    inner = (
        f"{counter & 0xFF:02X}"
        f"00"
        f"10"
        f"{own_address:06X}"
        f"{dst_address:06X}"
        f"00"
        f"{selector:02X}"
        f"{chunk_hex.upper()}"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_config_temperatures(
    counter: int,
    own_address: int,
    dst_address: int,
    *,
    comfort_temperature: float,
    eco_temperature: float,
    maximum_temperature: float,
    minimum_temperature: float,
    measurement_offset: float,
    window_open_temperature: float,
    window_open_duration: int,
    group_id: int = 0,
) -> str:
    """Build a ConfigTemperatures (0x11) command."""
    comfort = parse_max_temperature(str(comfort_temperature))
    eco = parse_max_temperature(str(eco_temperature))
    maximum = parse_max_temperature(str(maximum_temperature))
    minimum = parse_max_temperature(str(minimum_temperature))
    window_open = parse_max_temperature(str(window_open_temperature))
    offset = parse_measurement_offset(measurement_offset)
    duration = parse_window_open_duration(window_open_duration)

    flags = 0x04 if group_id > 0 else 0x00
    inner = (
        f"{counter & 0xFF:02X}"
        f"{flags:02X}"
        f"11"
        f"{own_address:06X}"
        f"{dst_address:06X}"
        f"{group_id & 0xFF:02X}"
        f"{int(comfort * 2):02X}"
        f"{int(eco * 2):02X}"
        f"{int(maximum * 2):02X}"
        f"{int(minimum * 2):02X}"
        f"{int((offset + 3.5) * 2):02X}"
        f"{int(window_open * 2):02X}"
        f"{int(duration / 5):02X}"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_add_link_partner(
    counter: int,
    own_address: int,
    dst_address: int,
    partner_address: int,
    partner_device_type: int,
) -> str:
    """Build an AddLinkPartner (0x20) command."""
    inner = (
        f"{counter & 0xFF:02X}"
        f"00"
        f"20"
        f"{own_address:06X}"
        f"{dst_address:06X}"
        f"00"
        f"{partner_address:06X}"
        f"{partner_device_type & 0xFF:02X}"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_remove_link_partner(
    counter: int,
    own_address: int,
    dst_address: int,
    partner_address: int,
    partner_device_type: int,
) -> str:
    """Build a RemoveLinkPartner (0x21) command."""
    inner = (
        f"{counter & 0xFF:02X}"
        f"00"
        f"21"
        f"{own_address:06X}"
        f"{dst_address:06X}"
        f"00"
        f"{partner_address:06X}"
        f"{partner_device_type & 0xFF:02X}"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_set_group_id(
    counter: int,
    own_address: int,
    dst_address: int,
    group_id: int,
) -> str:
    """Build a SetGroupId (0x22) command."""
    if group_id < 0 or group_id > 255:
        raise ValueError("group_id must be in range 0..255")
    inner = (
        f"{counter & 0xFF:02X}"
        f"00"
        f"22"
        f"{own_address:06X}"
        f"{dst_address:06X}"
        f"00"
        f"{group_id & 0xFF:02X}"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_remove_group_id(
    counter: int,
    own_address: int,
    dst_address: int,
) -> str:
    """Build a RemoveGroupId (0x23) command."""
    inner = (
        f"{counter & 0xFF:02X}"
        f"00"
        f"23"
        f"{own_address:06X}"
        f"{dst_address:06X}"
        f"00"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_wake_up(counter: int, own_address: int, dst_address: int) -> str:
    """Build a WakeUp (0xF1) command — asks the device to stay awake for a few seconds."""
    inner = (
        f"{counter & 0xFF:02X}"
        f"00"
        f"F1"
        f"{own_address:06X}"
        f"{dst_address:06X}"
        f"00"
        f"3F"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_time_information(
    counter: int,
    own_address: int,
    dst_address: int,
    when: datetime | None = None,
) -> str:
    """Build a TimeInformation (0x03) telegram using the FHEM/MAX encoding."""
    now = when or datetime.now().astimezone()
    month = now.month
    payload = (
        f"{now.year % 100:02X}"
        f"{now.day:02X}"
        f"{now.hour:02X}"
        f"{(now.minute | ((month & 0x0C) << 4)):02X}"
        f"{(now.second | ((month & 0x03) << 6)):02X}"
    )
    inner = (
        f"{counter & 0xFF:02X}"
        f"04"
        f"{MSG_TIME_INFORMATION:02X}"
        f"{own_address:06X}"
        f"{dst_address:06X}"
        f"00"
        f"{payload}"
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"


def build_pair_pong(counter: int, own_address: int, dst_address: int) -> str:
    """Build a PairPong (0x01) response to a PairPing from a new device."""
    inner = (
        f"{counter & 0xFF:02X}"
        f"00"
        f"01"
        f"{own_address:06X}"
        f"{dst_address:06X}"
        f"00"
        f"00"  # payload: device type 0 (we act as Cube)
    )
    length = len(bytes.fromhex(inner))
    packet = f"{length:02X}{inner}"
    return f"Zs{packet}\r\n"
