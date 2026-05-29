# MAX! via CUL

Home Assistant custom integration for eQ-3 MAX! devices connected through a
CUL or CUNO running CULFW.

This integration is for people who still have useful MAX! heating hardware and
want to run it locally in Home Assistant without a MAX! Cube cloud dependency.
It talks directly to the CUL/CUNO over TCP and implements the MAX!/MORITZ
protocol locally.

[![Open your Home Assistant instance and add this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=thnow&repository=MAX-via-Cul&category=integration)

## What You Get

- UI setup through Home Assistant config flow
- Pairing for MAX! heating thermostats, wall thermostats and shutter contacts
- `climate` entities for heating and wall thermostats
- Week profile editing with draft, save and discard workflow
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
- CULFW support for MAX!/MORITZ mode

Before installing the integration, make sure Home Assistant can reach the
CUL/CUNO host and port from inside your Home Assistant environment.

## Installation

### HACS

1. Open HACS.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add this repository URL:

   ```text
   https://github.com/thnow/MAX-via-Cul
   ```

4. Select category **Integration**.
5. Install **MAX! via CUL**.
6. Restart Home Assistant.
7. Add the integration from **Settings > Devices & services > Add integration**.

The My Home Assistant badge above opens the HACS custom repository dialog
directly when your Home Assistant instance supports it.

### Manual

1. Copy `custom_components/cul_max` into your Home Assistant configuration
   directory so the final path is `custom_components/cul_max`.
2. Restart Home Assistant.
3. Add **MAX! via CUL** from **Settings > Devices & services > Add integration**.

## First Setup

The config flow asks for three values:

- **Host**: IP address or host name of the CUL/CUNO
- **Port**: TCP port of the CUL/CUNO, usually `2323`
- **Own MAX! address**: 6-digit hex address used by this integration, default `123456`

If you are replacing an existing MAX! Cube setup, reuse the old radio identity
where possible or pair the devices again cleanly. MAX! devices remember their
paired controller, so moving between controllers can require a device reset.

## Pairing Your First Device

1. Add the integration and confirm it connects to the CUL/CUNO.
2. In Home Assistant, call the service `cul_max.start_pairing`.
3. Put the MAX! device into pairing mode.
4. Wait for the device to appear in Home Assistant.
5. Rename the device or assign groups/rooms as needed.

Common pairing actions:

- Heating thermostat: hold the Boost button for about 3 seconds.
- Shutter contact: hold the button until the LED starts blinking.
- Wall thermostat: reset or enter pairing mode from the device menu, depending on firmware.

The detailed device reset notes live in
[`custom_components/cul_max/README.md`](custom_components/cul_max/README.md).

## Common Workflows

### Create a MAX! room

Use `cul_max.create_room_association` to assign a shared MAX! group ID and
write direct link partners between thermostats and shutter contacts. This lets
the devices keep cooperating even when Home Assistant is temporarily down.

### Use a Zigbee or Matter contact as MAX! window contact

1. Create a virtual MAX! shutter contact with
   `cul_max.create_virtual_shutter_contact`.
2. Associate it with the room using `cul_max.create_room_association` or
   `cul_max.associate_devices`.
3. Call `cul_max.send_virtual_shutter_contact_state` from an automation when
   the external sensor opens or closes.

### Back up the MAX! topology

Use `cul_max.export_topology` after pairing and room setup. Keep the JSON file
somewhere safe. It contains known devices, groups, link partners, week profiles
and virtual contacts.

Use `cul_max.import_topology` to restore that structure later.

## Lovelace Card

The integration registers `cul-max-week-profile-card` as a frontend resource.
It can display and edit MAX! week profiles in a compact card.

Example:

```yaml
type: custom:cul-max-week-profile-card
entity: climate.living_room_radiator
```

## Services

The integration exposes these Home Assistant services:

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

The Home Assistant service UI includes selectors and descriptions for all
service fields.

## Troubleshooting

### Integration cannot connect

- Verify the CUL/CUNO IP address and TCP port.
- Check that the port is reachable from the Home Assistant host/container.
- Make sure no other application exclusively owns the CUL connection.

### Pairing does not finish

- Start `cul_max.start_pairing` before putting the device into pairing mode.
- Move the device closer to the CUL/CUNO for the first pairing attempt.
- Reset the MAX! device if it was previously paired with another controller.
- Check Home Assistant logs for `cul_max` messages.

### Device state looks old

MAX! devices are battery powered and do not all report continuously. The
integration exposes `last_seen`, `stale`, `last_ack`, retry and pending-config
diagnostics to make this visible.

### Week profile seems shifted

Use `cul_max.sync_time` for thermostats and wall thermostats. Then verify the
profile again.

## Known Limitations

- This is a local custom integration, not an official Home Assistant core integration.
- It is designed for direct CUL/CUNO TCP access.
- It intentionally avoids aggressive wake-up polling to reduce radio traffic and battery drain.
- MAX! radio is not perfectly reliable. Some radio messages can be missed or
  acknowledged late, and larger setup operations can take a while when many
  protocol messages have to be sent. This is a limitation of the MAX!/CUL radio
  design rather than a plugin bug. It normally has little impact on daily
  operation, but it can make initial setup, pairing and bulk configuration feel
  slow or occasionally flaky.
- If you already have a working MAX! Cube setup, plan migration carefully because paired devices remember their controller.

## More Documentation

The extended notes for reset procedures, entities, topology handling and
diagnostics are in
[`custom_components/cul_max/README.md`](custom_components/cul_max/README.md).

## Development

Run the protocol regression tests from the repository root:

```sh
python3 -m unittest discover -s custom_components/cul_max/tests
```

Repository layout:

- `hacs.json` in the repository root
- `custom_components/cul_max/manifest.json` with `config_flow: true`
- integration code below `custom_components/cul_max`
- no generated Python caches committed

## License

See [`LICENSE`](LICENSE).
