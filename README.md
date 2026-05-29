# MAX! via CUL

Home Assistant custom integration for eQ-3 MAX! devices connected through a
CUL or CUNO running CULFW.

The integration talks directly to the CUL/CUNO over TCP and implements the
MAX!/MORITZ protocol locally. It is built for long-lived MAX! installations
where reliable local control, useful diagnostics and real on-device
associations matter more than cloud features.

[![Open your Home Assistant instance and add this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=thnow&repository=MAX-via-Cul&category=integration)

## Features

- Config flow setup for CUL/CUNO host, TCP port and local MAX! address
- Pairing for MAX! heating thermostats, wall thermostats and shutter contacts
- Climate entities for target temperature and HVAC mode
- Week profile editing with draft/save/discard workflow
- Comfort, eco, window-open and measurement-offset configuration entities
- Real MAX! group IDs and link partners written to the devices
- Virtual MAX! shutter contacts for external sensors such as Zigbee, Matter or IKEA
- Services for room association, topology export/import and repair workflows
- Diagnostics for last seen, last ACK, retries, stale state, pending config and profile validation
- Optional Lovelace card for compact week-profile editing

## Supported Devices

- MAX! heating thermostat
- MAX! heating thermostat+
- MAX! wall thermostat
- MAX! shutter contact
- Virtual MAX! shutter contacts created by this integration

## Requirements

- Home Assistant 2024.1 or newer
- A CUL or CUNO flashed with CULFW
- TCP access to the CUL/CUNO, commonly port `2323`
- MAX!/MORITZ mode available on the CULFW device

## Installation

### HACS

1. Open HACS.
2. Add this repository as a custom repository with category `Integration`.
3. Install `MAX! via CUL`.
4. Restart Home Assistant.
5. Add the integration from **Settings > Devices & services**.

### Manual

Copy `custom_components/cul_max` into your Home Assistant configuration under
`custom_components/cul_max`, then restart Home Assistant.

## Configuration

The integration is configured through the Home Assistant UI. The config flow
asks for:

- CUL/CUNO host name or IP address
- TCP port, default `2323`
- Own MAX! address of the integration, default `123456`

When replacing an existing MAX! Cube setup, reuse the old radio identity where
possible or pair the devices again cleanly.

## Services

The integration exposes services for everyday operation and repair workflows:

- `cul_max.start_pairing`
- `cul_max.set_device_name`
- `cul_max.wake_thermostats`
- `cul_max.sync_time`
- `cul_max.set_week_profile`
- `cul_max.set_week_profile_days`
- `cul_max.set_group_id`
- `cul_max.set_temperature_config`
- `cul_max.set_desired_temperature`
- `cul_max.remove_group_id`
- `cul_max.add_link_partner`
- `cul_max.remove_link_partner`
- `cul_max.associate_devices`
- `cul_max.deassociate_devices`
- `cul_max.create_virtual_shutter_contact`
- `cul_max.delete_virtual_device`
- `cul_max.send_virtual_shutter_contact_state`
- `cul_max.create_room_association`
- `cul_max.delete_room_association`
- `cul_max.rebuild_room_association`
- `cul_max.export_topology`
- `cul_max.import_topology`
- `cul_max.cleanup_superseded_devices`

The Home Assistant service UI includes field descriptions and selectors for
these services.

## Lovelace Card

The integration registers `cul-max-week-profile-card` as a frontend resource.
It can be used to display and edit MAX! week profiles in a compact card.

## Documentation

Detailed notes for device reset, pairing, entities, topology management and
week-profile handling are available in
[`custom_components/cul_max/README.md`](custom_components/cul_max/README.md).

## Development

Run the protocol regression tests from the repository root:

```sh
python3 -m unittest discover -s custom_components/cul_max/tests
```

The repository follows the HACS custom integration layout:

- `hacs.json` in the repository root
- `custom_components/cul_max/manifest.json` with `config_flow: true`
- integration code below `custom_components/cul_max`
- no generated Python caches committed

## License

See [`LICENSE`](LICENSE).
