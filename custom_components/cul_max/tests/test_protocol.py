"""Focused protocol regression tests for MAX! via CUL."""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import time
import types
import unittest
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo
from unittest.mock import patch


def _load_module(module_name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
package = sys.modules.setdefault(
    "custom_components.cul_max",
    types.ModuleType("custom_components.cul_max"),
)
package.__path__ = [str(BASE_DIR)]


class _Platform(StrEnum):
    BUTTON = "button"
    CLIMATE = "climate"
    BINARY_SENSOR = "binary_sensor"
    NUMBER = "number"
    SENSOR = "sensor"
    TEXT = "text"


ha_module = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
ha_const_module = types.ModuleType("homeassistant.const")
ha_const_module.Platform = _Platform
sys.modules["homeassistant.const"] = ha_const_module
ha_module.const = ha_const_module

const = _load_module("custom_components.cul_max.const", BASE_DIR / "const.py")
protocol = _load_module("custom_components.cul_max.protocol", BASE_DIR / "protocol.py")

MODE_AUTO = const.MODE_AUTO
MODE_MANUAL = const.MODE_MANUAL

build_config_week_profile = protocol.build_config_week_profile
build_set_temperature = protocol.build_set_temperature
build_shutter_contact_state = protocol.build_shutter_contact_state
build_wake_up = protocol.build_wake_up
encode_week_profile = protocol.encode_week_profile
encode_week_profile_day = protocol.encode_week_profile_day
format_week_profile_by_day = protocol.format_week_profile_by_day
format_week_profile_lines = protocol.format_week_profile_lines
get_expected_week_profile_temperature = protocol.get_expected_week_profile_temperature
parse_week_profile_text = protocol.parse_week_profile_text
parse_week_profile_time = protocol.parse_week_profile_time
split_week_profile_for_send = protocol.split_week_profile_for_send


class WeekProfileEncodingTests(unittest.TestCase):
    """Byte-accurate regression tests against the FHEM-compatible profile format."""

    def test_parse_week_profile_time_accepts_2400(self) -> None:
        self.assertEqual(parse_week_profile_time("24:00"), 24 * 60)
        self.assertEqual(parse_week_profile_time("07:05"), 7 * 60 + 5)

    def test_parse_week_profile_time_rejects_non_5_minute_steps(self) -> None:
        with self.assertRaises(ValueError):
            parse_week_profile_time("07:03")

    def test_encode_rejects_invalid_day_schedules(self) -> None:
        schedules = [
            [],
            [(18.0, 60)],
            [(18.0, 0), (20.0, 1440)],
            [(18.0, 60), (20.0, 60), (18.0, 1440)],
            [(18.0, 120), (20.0, 60), (18.0, 1440)],
            [(18.0, 1440), (20.0, 1440)],
            [(18.0, 63), (20.0, 1440)],
            [(18.0, end) for end in range(5, 70, 5)] + [(20.0, 1440)],
        ]
        for schedule in schedules:
            with self.subTest(schedule=schedule), self.assertRaises(ValueError):
                encode_week_profile_day(schedule)

    def test_encode_and_split_reject_invalid_days(self) -> None:
        profile = encode_week_profile({2: [(18.0, 1440)]})
        for day in (-1, 7):
            with self.subTest(day=day):
                with self.assertRaises(ValueError):
                    encode_week_profile({day: [(18.0, 1440)]})
                with self.assertRaises(ValueError):
                    split_week_profile_for_send(profile, day)

    @unittest.skipUnless(hasattr(time, "tzset"), "Requires timezone switching")
    def test_expected_temperature_preserves_supplied_timezone_and_weekday(self) -> None:
        profile = encode_week_profile({
            2: [(17.0, 1440)],
            3: [(18.0, 360), (23.0, 1440)],
        })
        try:
            with patch.dict(os.environ, {"TZ": "UTC"}):
                time.tzset()
                # Tokyo is already on Tuesday while the UTC host is on Monday.
                when = datetime(2026, 4, 7, 0, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
                self.assertEqual(get_expected_week_profile_temperature(profile, when), 18.0)
                # A UTC conversion would also choose the wrong time slot here.
                when = datetime(2026, 4, 7, 1, 30, tzinfo=ZoneInfo("America/New_York"))
                self.assertEqual(get_expected_week_profile_temperature(profile, when), 18.0)
        finally:
            time.tzset()

    def test_expected_temperature_switches_at_exact_boundary(self) -> None:
        profile = encode_week_profile({3: [(18.0, 360), (23.0, 1440)]})
        self.assertEqual(
            get_expected_week_profile_temperature(profile, datetime(2026, 4, 7, 6, 0)),
            23.0,
        )

    def test_encode_week_profile_day_matches_fhem_for_weekday(self) -> None:
        schedule = [(18.0, 7 * 60 + 5), (23.0, 15 * 60 + 30), (18.0, 24 * 60)]
        self.assertEqual(
            encode_week_profile_day(schedule),
            "48555cba49204520452045204520452045204520452045204520",
        )

    def test_encode_week_profile_day_matches_fhem_for_weekend(self) -> None:
        schedule = [(18.0, 7 * 60 + 5), (18.0, 15 * 60 + 30), (18.0, 24 * 60)]
        self.assertEqual(
            encode_week_profile_day(schedule),
            "485548ba49204520452045204520452045204520452045204520",
        )

    def test_format_preserves_final_temperature_segment(self) -> None:
        profile = encode_week_profile(
            {
                0: [(18.0, 7 * 60 + 5), (18.0, 15 * 60 + 30), (18.0, 24 * 60)],
                2: [(18.0, 7 * 60 + 5), (23.0, 15 * 60 + 30), (18.0, 24 * 60)],
            }
        )
        by_day = format_week_profile_by_day(profile)
        self.assertEqual(by_day["saturday"], "18,07:05,18,15:30,18")
        self.assertEqual(by_day["monday"], "18,07:05,23,15:30,18")

    def test_split_week_profile_omits_second_chunk_if_only_fillers_remain(self) -> None:
        profile = encode_week_profile(
            {2: [(18.0, 7 * 60 + 5), (23.0, 15 * 60 + 30), (18.0, 24 * 60)]}
        )
        self.assertEqual(
            split_week_profile_for_send(profile, 2),
            [(0, "48555cba49204520452045204520")],
        )

    def test_split_week_profile_includes_second_chunk_for_long_days(self) -> None:
        profile = encode_week_profile(
            {
                2: [
                    (18.0, 60),
                    (19.0, 120),
                    (20.0, 180),
                    (21.0, 240),
                    (22.0, 300),
                    (23.0, 360),
                    (18.0, 420),
                    (19.0, 24 * 60),
                ]
            }
        )
        chunks = split_week_profile_for_send(profile, 2)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0][0], 0)
        self.assertEqual(chunks[1][0], 1)
        self.assertEqual(len(chunks[0][1]), 28)
        self.assertEqual(len(chunks[1][1]), 24)

    def test_build_config_week_profile_matches_expected_packet(self) -> None:
        packet = build_config_week_profile(
            counter=1,
            own_address=0x000001,
            dst_address=0x000002,
            day=2,
            part=0,
            chunk_hex="48555CBA49204520452045204520",
        )
        self.assertEqual(
            packet,
            "Zs19010010000001000002000248555CBA49204520452045204520\r\n",
        )

    def test_expected_week_profile_temperature_uses_active_slot(self) -> None:
        profile = encode_week_profile(
            {3: [(18.0, 7 * 60 + 5), (23.0, 15 * 60 + 30), (18.0, 24 * 60)]}
        )
        when = datetime(2026, 4, 7, 9, 36, tzinfo=ZoneInfo("Europe/Berlin"))
        self.assertEqual(get_expected_week_profile_temperature(profile, when), 23.0)

    def test_format_week_profile_lines_are_human_editable(self) -> None:
        profile = encode_week_profile(
            {2: [(18.0, 7 * 60 + 5), (23.0, 15 * 60 + 30), (18.0, 24 * 60)]}
        )
        lines = format_week_profile_lines(profile)
        self.assertEqual(lines[2], "Mon 18,07:05,23,15:30,18")


class CommandPacketTests(unittest.TestCase):
    """Regression tests for command packet builders that were aligned with FHEM."""

    def test_build_set_temperature_manual_without_group(self) -> None:
        self.assertEqual(
            build_set_temperature(
                counter=1,
                own_address=0x000001,
                dst_address=0x000002,
                temperature=18.0,
                mode=MODE_MANUAL,
            ),
            "Zs0B0100400000010000020064\r\n",
        )

    def test_build_set_temperature_auto_with_group_uses_flags_and_group(self) -> None:
        self.assertEqual(
            build_set_temperature(
                counter=1,
                own_address=0x000001,
                dst_address=0x000002,
                temperature=0.0,
                mode=MODE_AUTO,
                group_id=5,
            ),
            "Zs0B0104400000010000020500\r\n",
        )

    def test_build_wake_up_uses_fhem_payload(self) -> None:
        self.assertEqual(
            build_wake_up(counter=1, own_address=0x000001, dst_address=0x000002),
            "Zs0B0100F1000001000002003F\r\n",
        )

    def test_build_shutter_contact_state_without_group_uses_flags_06(self) -> None:
        self.assertEqual(
            build_shutter_contact_state(
                counter=1,
                src_address=0x000001,
                dst_address=0x000002,
                is_open=True,
                group_id=0,
            ),
            "Zs0B0106300000010000020012\r\n",
        )

    def test_build_shutter_contact_state_with_group_uses_flags_04(self) -> None:
        self.assertEqual(
            build_shutter_contact_state(
                counter=1,
                src_address=0x000001,
                dst_address=0x000002,
                is_open=True,
                group_id=7,
            ),
            "Zs0B0104300000010000020712\r\n",
        )


class WeekProfileParserTests(unittest.TestCase):
    """Behavioral tests for the FHEM-like text parser."""

    def test_parse_week_profile_text_understands_multiple_days(self) -> None:
        parsed = parse_week_profile_text(
            "Mon 18,07:05,23,15:30,18\nTue 18,07:05,23,15:30,18"
        )
        self.assertEqual(parsed[2], [(18.0, 425), (23.0, 930), (18.0, 1440)])
        self.assertEqual(parsed[3], [(18.0, 425), (23.0, 930), (18.0, 1440)])

    def test_parse_week_profile_text_requires_final_temperature(self) -> None:
        with self.assertRaises(ValueError):
            parse_week_profile_text("Sat 18,07:05,18,15:30")

    def test_parse_rejects_empty_fields(self) -> None:
        for text in ("Mon 18,,07:05,23", "Mon ,18", "Mon 18,"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_week_profile_text(text)

    def test_parse_rejects_duplicate_day_aliases(self) -> None:
        with self.assertRaises(ValueError):
            parse_week_profile_text("Mon 18\nMontag 23")

    def test_parse_rejects_unreachable_final_temperature(self) -> None:
        with self.assertRaises(ValueError):
            parse_week_profile_text("Mon 18,24:00,23")

    def test_all_days_round_trip_through_text(self) -> None:
        updates = {day: [(18.0, 425), (23.0, 930), (17.0, 1440)] for day in range(7)}
        profile = encode_week_profile(updates)
        parsed = parse_week_profile_text("\n".join(format_week_profile_lines(profile)))
        self.assertEqual(parsed, updates)
        self.assertEqual(encode_week_profile(parsed), profile)


if __name__ == "__main__":
    unittest.main()
