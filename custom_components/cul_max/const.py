"""Constants for the MAX! via CUL integration."""

from datetime import timedelta
import json
from pathlib import Path

from homeassistant.const import Platform

DOMAIN = "cul_max"
FRONTEND_URL_BASE = "/cul-max"

_MANIFEST_PATH = Path(__file__).parent / "manifest.json"
with _MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
    INTEGRATION_VERSION = json.load(manifest_file).get("version", "0.0.0")

FRONTEND_MODULES = [
    {
        "name": "CUL MAX Week Profile Card",
        "filename": "cul-max-week-profile-card.js",
        "version": INTEGRATION_VERSION,
        "legacy_paths": ["/local/cul-max-week-profile-card.js"],
    }
]

# TCP connection defaults (CULFW on MAX! Cube or CUNO)
DEFAULT_HOST = ""
DEFAULT_PORT = 2323

# CUL / CULFW commands
# Init sequence mirrors FHEM CUL.pm rfmode=MAX: "Zr"
CULFW_CMD_VERSION  = "V\n"
CULFW_CMD_MORITZ_RX = "Zr\n"   # Activate MAX!/Moritz RF receive mode
CULFW_CMD_SEND = "Zs"            # Prefix for sending a MAX! packet

# MAX! Message types (single hex byte)
MSG_PAIR_PING          = 0x00
MSG_PAIR_PONG          = 0x01
MSG_ACK                = 0x02
MSG_TIME_INFORMATION   = 0x03
MSG_CONFIG_WEEK_PROFILE = 0x10
MSG_CONFIG_TEMPERATURES = 0x11
MSG_CONFIG_VALVE       = 0x12
MSG_ADD_LINK_PARTNER   = 0x20
MSG_REMOVE_LINK_PARTNER = 0x21
MSG_SET_GROUP_ID       = 0x22
MSG_REMOVE_GROUP_ID    = 0x23
MSG_SHUTTER_CONTACT_STATE = 0x30
MSG_SET_TEMPERATURE    = 0x40
MSG_WALL_THERMOSTAT_CONTROL = 0x42
MSG_PUSH_BUTTON_STATE  = 0x50
MSG_THERMOSTAT_STATE   = 0x60
MSG_WALL_THERMOSTAT_STATE = 0x70
MSG_SET_COMFORT_TEMPERATURE = 0x43
MSG_RESET              = 0xF0
MSG_WAKE_UP            = 0xF1

# Device types
DEVICE_CUBE              = 0
DEVICE_HEATING_THERMOSTAT = 1
DEVICE_HEATING_THERMOSTAT_PLUS = 2
DEVICE_WALL_THERMOSTAT   = 3
DEVICE_SHUTTER_CONTACT   = 4
DEVICE_PUSH_BUTTON       = 5

DEVICE_TYPE_NAMES = {
    DEVICE_CUBE: "Cube",
    DEVICE_HEATING_THERMOSTAT: "HeatingThermostat",
    DEVICE_HEATING_THERMOSTAT_PLUS: "HeatingThermostatPlus",
    DEVICE_WALL_THERMOSTAT: "WallMountedThermostat",
    DEVICE_SHUTTER_CONTACT: "ShutterContact",
    DEVICE_PUSH_BUTTON: "PushButton",
}

# Control modes
MODE_AUTO     = 0
MODE_MANUAL   = 1
MODE_VACATION = 2
MODE_BOOST    = 3

MODE_NAMES = {
    MODE_AUTO: "auto",
    MODE_MANUAL: "manual",
    MODE_VACATION: "vacation",
    MODE_BOOST: "boost",
}

# Temperature limits
TEMP_MIN = 4.5
TEMP_MAX = 30.5
TEMP_OFF = 4.5
TEMP_ON  = 30.5

# MAX! week profile: 7 days * 13 control points * 2 bytes
# Matches FHEM's default profile representation.
DEFAULT_WEEK_PROFILE = (
    "4448550845204520452045204520452045204520452045204520"
    "4448550845204520452045204520452045204520452045204520"
    "4448546c44cc5514452045204520452045204520452045204520"
    "4448546c44cc5514452045204520452045204520452045204520"
    "4448546c44cc5514452045204520452045204520452045204520"
    "4448546c44cc5514452045204520452045204520452045204520"
    "4448546c44cc5514452045204520452045204520452045204520"
)

# Storage key for known devices
STORAGE_KEY = f"{DOMAIN}_devices"
STORAGE_VERSION = 1
STORAGE_SCHEMA_VERSION = 2

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_OWN_ADDRESS = "own_address"

# Default source address (used when sending commands)
DEFAULT_OWN_ADDRESS = 0x123456

# Pairing duration in seconds
PAIRING_DURATION = 60

# Device types that are climate entities
CLIMATE_DEVICE_TYPES = {
    DEVICE_HEATING_THERMOSTAT,
    DEVICE_HEATING_THERMOSTAT_PLUS,
    DEVICE_WALL_THERMOSTAT,
}

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.TEXT,
]

STALE_TIMEOUT_CLIMATE = timedelta(days=2)
STALE_TIMEOUT_SHUTTER_CONTACT = timedelta(days=10)
STALE_TIMEOUT_PUSH_BUTTON = timedelta(days=30)
STALE_TIMEOUT_CUBE = timedelta(days=1)
STALE_TIMEOUT_VIRTUAL = timedelta(days=30)
