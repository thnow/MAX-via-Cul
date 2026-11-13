"""User-facing errors with translation keys.

Raised anywhere in the integration (also in the HA-free protocol module). At
the boundary to Home Assistant (services, entity actions) they become a
HomeAssistantError with translation_key, so the UI shows them in the
language of the user. str() gives the English text for logs and tests.
The texts live in translations/*.json under "exceptions".
"""
from __future__ import annotations

# English text per key; must match translations/en.json "exceptions".
MESSAGES: dict[str, str] = {
    'unknown_device': 'Unknown MAX! device address {address}.',
    'unknown_partner': 'Unknown partner address {address}.',
    'unknown_partner_type_hint': 'Unknown partner address {address}. For a stale link to an unknown device, give partner_type.',
    'association_not_supported': 'This MAX! association is not supported: {source} -> {partner}. Allowed partners for {type}: {allowed}.',
    'not_paired': '{device} is only discovered, not paired. Pair the device properly before writing configuration or room links.',
    'external_sensor_wall_thermostat': 'An external room sensor is only possible for radiator thermostats (wall thermostats have their own sensor).',
    'sensor_not_found': 'Sensor {sensor} not found.',
    'sensor_not_temperature': 'Please choose a temperature sensor (sensor.*).',
    'wall_thermostat_link_rejected': 'The thermostat rejected the new virtual wall thermostat.',
    'no_thermostats_listed': 'Not paired MAX! thermostats: {addresses}',
    'no_thermostats': 'No paired MAX! thermostats found.',
    'summer_blocks_vacation': 'Summer mode is on – the heating is off anyway. End summer mode before starting a vacation.',
    'vacation_blocks_summer': 'Please end the vacation mode first.',
    'vacation_end_missing': 'Please set the vacation end (return) first.',
    'vacation_end_past': 'The vacation end (minus preheating) must be at least a few minutes in the future.',
    'return_in_future': 'The return must be in the future.',
    'summer_valve_invalid': 'Unknown valve position {valve} (closed or open).',
    'pairing_duration': 'The pairing duration must be at least 1 second.',
    'no_temperature_config': 'Device {address} has no temperature configuration.',
    'no_week_profile_support': 'Device {address} has no week profile.',
    'no_time_sync_support': 'Device {address} does not support time synchronisation.',
    'area_no_devices': 'There are no other MAX! devices in the chosen area.',
    'address_invalid': 'The address must be 6 hexadecimal digits.',
    'address_exists': 'Device address {address} already exists.',
    'not_virtual': 'Device {address} is not a virtual device.',
    'not_virtual_contact': 'Device {address} is not a virtual window contact.',
    'virtual_no_links': 'Virtual devices have no links stored on the device.',
    'partner_type_invalid': 'Unknown partner_type {type}.',
    'associate_two_devices': 'At least two devices are needed for an association.',
    'deassociate_two_devices': 'At least two devices are needed to remove an association.',
    'group_id_range': 'The group ID must be between 1 and 255.',
    'room_needs_climate': 'A room needs at least one climate device.',
    'room_two_devices': 'A room needs at least two devices.',
    'room_teardown_two_devices': 'Taking a room apart needs at least two devices.',
    'no_free_group': 'No free MAX! group ID left.',
    'no_free_virtual_address': 'No free virtual MAX! address left.',
    'topology_devices_list': "The topology JSON has no valid 'devices' list.",
    'topology_object': 'The topology must be a JSON object.',
    'topology_empty': 'The topology contains no devices.',
    'import_address_invalid': 'Invalid device address in the import: {address}',
    'import_address_duplicate': 'Duplicate device address in the import: {address}',
    'until_empty': 'Empty until value.',
    'until_format': 'Give until as ISO time or in the format DD.MM.YYYY HH:MM.',
    'until_half_hour': 'Until times must be at :00 or :30 for MAX!.',
    'until_future': 'The until time must be in the future.',
    'return_format': 'Give the return as ISO time or in the format DD.MM.YYYY HH:MM.',
    'gateway_none': 'No MAX! gateway loaded.',
    'gateway_unknown': 'Unknown MAX! gateway: {gateway}',
    'gateway_mixed': 'The devices of this call belong to different MAX! gateways.',
    'gateway_choose': 'Several MAX! gateways are set up – please choose one in the field "Gateway".',
    'thermostat_not_found': 'Thermostat not found.',
    'areas_no_thermostats': 'There are no MAX! thermostats in the chosen areas.',
    'temperature_needed_until': 'A temperature is needed together with until.',
    'temperature_needed_manual': 'Manual mode needs a temperature.',
    'temperature_or_mode': 'Give a temperature or an explicit mode.',
    'command_not_confirmed': '{device}: {command} was not confirmed ({error})',
    'profile_line_invalid': "Invalid line '{line}'. Expected: day and profile.",
    'day_unknown': "Unknown day '{day}'.",
    'day_twice': "Day '{day}' was given twice.",
    'profile_invalid': 'Invalid profile for {day}. Format: temp,HH:MM,temp,HH:MM,temp',
    'profile_times': 'Switching times for {day} must be strictly ascending and before 24:00.',
    'profile_too_many': 'Too many switching points for {day} (at most 13).',
    'profile_empty': 'No week profile given.',
    'temperature_invalid': "Invalid temperature '{value}'.",
    'temperature_range': "Temperature '{value}' is invalid. Allowed are 4.5 to 30.5 in steps of 0.5.",
    'offset_invalid': "Invalid temperature offset '{value}'.",
    'offset_range': "Offset '{value}' is invalid. Allowed are -3.5 to 3.5 in steps of 0.5.",
    'window_duration_invalid': "Invalid window-open duration '{value}'.",
    'window_duration_range': 'The window-open duration must be between 0 and 60 minutes.',
    'window_duration_step': 'The window-open duration must be given in steps of 5 minutes.',
    'time_invalid_format': "Invalid time '{value}'. Expected HH:MM.",
    'time_invalid': "Invalid time '{value}'.",
    'time_step': "Time '{value}' is invalid. MAX! uses steps of 5 minutes.",
    'weekday_range': 'The weekday must be between 0 (Saturday) and 6 (Friday).',
    'day_points': 'A day profile needs 1 to 13 switching points.',
    'day_end_2400': 'A day profile must end at 24:00.',
    'times_ascending': 'Switching times must be strictly ascending.',
    'times_range': 'Switching times must be between 00:00 and 24:00 in steps of 5 minutes.',
    'until_year': 'The until year must be between 2000 and 2063.',
    'until_time_half_hour': 'The until time must be at :00 or :30.',
}


class CulMaxError(ValueError):
    """A ValueError with a translation key and placeholders."""

    def __init__(self, key: str, **placeholders: object) -> None:
        self.key = key
        self.placeholders = {name: str(value) for name, value in placeholders.items()}
        super().__init__(MESSAGES.get(key, key).format(**self.placeholders))


def ha_error(err: Exception):
    """HomeAssistantError for the UI: translated for CulMaxError, plain otherwise."""
    from homeassistant.exceptions import HomeAssistantError

    from .const import DOMAIN

    if isinstance(err, CulMaxError):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=err.key,
            translation_placeholders=err.placeholders,
        )
    return HomeAssistantError(str(err))
