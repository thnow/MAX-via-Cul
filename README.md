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
- Lovelace week profile card: coloured timeline per day, status, inline editing,
  one card for several thermostats of a room
- Optional external room sensor per radiator thermostat (virtual wall
  thermostat), e.g. a thermometer on the desk instead of the sensor behind the
  curtain
- Vacation mode: whole flat (or selected rooms) to e.g. 16 °C until your
  return; the thermostats switch back to their program on their own, with
  optional preheating and restore of manual settings
- Fast, confirmed commands: the CUL's real send budget, prioritized queue and
  device acknowledgements; detection of devices still paired with an old Cube

## Screenshots

| Week profile card | Editing a day |
|---|---|
| ![Week profile card with timeline, status and room sensor](https://raw.githubusercontent.com/thnow/MAX-via-Cul/main/docs/images/week-profile-card.png) | ![Inline day editor with copy to other days](https://raw.githubusercontent.com/thnow/MAX-via-Cul/main/docs/images/week-profile-editor.png) |

| Room sensor instead of the radiator sensor | One card for a room with two thermostats |
|---|---|
| ![Choosing an external room sensor](https://raw.githubusercontent.com/thnow/MAX-via-Cul/main/docs/images/room-sensor.png) | ![Shared card for two radiator thermostats](https://raw.githubusercontent.com/thnow/MAX-via-Cul/main/docs/images/shared-room-card.png) |

**Topology picture** (image entity on the CUL device: rooms, devices, links, problems)

![Topology overview](https://raw.githubusercontent.com/thnow/MAX-via-Cul/main/docs/images/topology.png)

## Supported Devices

- MAX! heating thermostat
- MAX! heating thermostat+
- MAX! wall thermostat
- MAX! shutter contact
- Virtual MAX! shutter contacts created by this integration

## Requirements

- Home Assistant 2026.11 or newer
- A CUL or CUNO flashed with CULFW (also a MAX! Cube flashed with a-culfw)
- Connected via TCP (commonly port `2323`) or as a USB stick (e.g. CUL,
  nanoCUL; typically 38400 baud)
- CULFW support for MAX!/MORITZ mode
- Several CULs are supported, each as its own integration entry

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
[the extended English guide](custom_components/cul_max/README.en.md)
or [the German guide](custom_components/cul_max/README.md).

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

### Lower the heating while you are away

Add the bundled `custom:cul-max-vacation-card` to a dashboard, enter the
return date and time, temperature and preheat and press "Urlaub starten"
(start vacation). The same settings exist as entities on the CUL device
("Vacation mode" switch and friends). Every thermostat
confirms the command and returns to its week program at the return time by
itself; switching it off ends the vacation early. For automations use
`cul_max.start_vacation` / `cul_max.end_vacation`.

### Back up the MAX! topology

Use `cul_max.export_topology` after pairing and room setup. Keep the JSON file
somewhere safe. It contains known devices, groups, link partners, week profiles
and virtual contacts.

Use `cul_max.import_topology` to restore that structure later.

## Lovelace Card

The integration registers `cul-max-week-profile-card` as a frontend resource.
It shows each day as a coloured 24 h timeline with a "now" marker, the next
switching point and status notices (window open, deviation from the schedule,
upload progress), and lets you edit a day directly in the card, including
copying it to other days.

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
- `cul_max.start_vacation`
- `cul_max.end_vacation`

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

### Commands take long to apply

Every packet to a sleeping thermostat uses a 1 s wake-up preamble, and the CUL
may only transmit 1 % of the time. The integration reads the real budget from
culfw, prioritizes target-temperature changes over background traffic and
shows progress in the climate attribute `command_status`
(`sending`/`confirmed`/`failed`). Log lines starting with `CUL credit pacing`
show when the budget is exhausted. Make sure no other program (FHEM, ioBroker)
is sending through the same CUL.

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
diagnostics are available in
[English](custom_components/cul_max/README.en.md) and
[German](custom_components/cul_max/README.md).

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

## Changelog

### 0.6.1

Thanks to [adampr1](https://github.com/adampr1/MAX-via-Cul) and
[XneddyX](https://github.com/XneddyX/MAX-via-Cul) for the ideas.

- Several CULs: every gateway now has its own device store. Before, all
  gateways shared one file and could overwrite each other's device lists.
  The old store moves to the first gateway automatically (with one CUL
  nothing changes; the old file stays as a backup).
- Setup proposes a free MAX! address for every further gateway (two
  addresses apart, because address + 1 is the virtual wall thermostat);
  virtual devices get addresses that are unique across all gateways.
- "Pairing" switch on every CUL device instead of the button: shows whether
  the pairing window is open and can close it early.
- "Delete device" works on MAX! device pages.
- TCP keepalive on the CUL connection in addition to the idle probe.
- Room sensor values are sent on changes of 0.5 °C (was 0.2 °C) and at most
  every 3 minutes (was 90 s with an extended send budget): every packet wakes
  the thermostat, and 0.5 °C is about the accuracy of most thermometers.

### 0.6.0

Ideas taken over from the fork by
[siebenbit](https://github.com/siebenbit/MAX-via-Cul) – thank you!

- Dead connections are detected: after 60 s without data from the CUL the
  integration asks for its send credit (no radio traffic) and reconnects if
  it gets no answer (Cube reboot, network glitch).
- Pairing ignores devices that still belong to another central (their pairing
  request is addressed to that central); answering would take them over.
  Important with several CULs. Reset such a device to pair it here.
- Week profiles are sent starting with today, so today's program applies
  first while the rest trickles out with the radio budget.
- No extra time sync after switching to auto if the thermostat's clock was
  set within the last 6 hours (saves one packet per switch).
- A newer temperature change for the same thermostat replaces an older one
  that is still waiting for radio time; the older one is neither sent nor
  retried any more.
- New sensor "Measured temperature" per thermostat, e.g. for area
  temperatures and history.
- Restarts no longer resend the time to every thermostat whose clock was set
  within the last 6 hours (about 1 s of radio time per device each restart).
- Home Assistant starts and stops quickly again: radio work that waits for
  send credit (room sensor values, config apply, vacation end) runs as
  background task instead of holding up startup ("Something is blocking Home
  Assistant from wrapping up the start up phase").
- Devices are linked to the CUL with `via_device_id` (the `via_device`
  parameter is deprecated and stops working in Home Assistant 2027.8).
- `ROADMAP.md` collects ideas for later (transmission queue card, pairing
  card with live results).

### 0.5.3

- External room sensor: values are accepted for up to 8 hours. Many
  sensors (e.g. Zigbee/ZHA thermometers) only report on change and stay
  silent for hours in a steady room; the old 30-minute limit made the
  thermostat fall back to its own sensor although the value was still valid.

### 0.5.2

- Faster week-profile and config uploads on CULs with a large send budget but
  standard recovery: user-initiated writes now keep only one packet in
  reserve (the large reserve applies to background traffic only). Uploads
  that used to send one packet every ~2 minutes now go out at once as long as
  the stored budget lasts.

### 0.5.1

- USB/serial CUL sticks: choose "USB stick / serial" when adding the
  integration (#1).
- Several CULs: every service is routed to the gateway that owns the device;
  `start_pairing` and the other installation-wide services accept a
  `gateway`, and each CUL device has a pairing control (#3).
- New sensor "Valve opening" (%) for every radiator thermostat (#3).

- Week profile card: rooms whose program was set elsewhere (e.g. with the old
  Cube) can be edited now. MAX! devices cannot report their program, so such
  days are shown as "unbekannt" (unknown) until they are set from Home
  Assistant; previously the card ignored all clicks in that case.
- Week profile editor: "+ Schaltpunkt" appends a switching point instead of
  splitting the longest period, so times already entered no longer jump.
- Card URLs carry a content hash, so browsers load updated cards right away
  instead of using a cached copy.

### 0.5.0

- Vacation mode using the thermostats' own vacation mode: switch, temperature,
  return time and preheat on the CUL device, services `start_vacation` and
  `end_vacation` (optionally per thermostat or area). Confirmed per device,
  retried, survives restarts; manual thermostats are restored afterwards.
- New Lovelace card `cul-max-vacation-card` to start, change and end the
  vacation for the whole flat; the week profile card shows "Urlaub bis …".
- Dark-mode logo and a readable integration icon.
- Device pages: every MAX! device is "connected via" the CUL device; entity
  names translated (de/en), pairing state values translated.
- Legacy per-day text editors and save/discard buttons disabled by default
  (once in existing installs); comfort/eco/window values apply automatically.
- Time-sync sensor only for thermostats.
- New image entity "Topology" on the CUL device: rooms, devices, links and
  problems (e.g. a device in the wrong area) at a glance.
- Diagnostics download for the integration and each device.

### 0.4.0

- Virtual window contacts now behave like real ones: the state is sent
  directly to each linked thermostat and must be acknowledged (with retries),
  quick open/close sequences are delivered in order, and the state is
  refreshed every 50 minutes and shortly after startup. Previously a single
  lost "closed" telegram could keep a thermostat at its window-open
  temperature indefinitely.
- `send_virtual_shutter_contact_state` returns `confirmed`.
- Week profile card redesigned: coloured 24 h timeline per day with "now"
  marker, next switching point, status notices (window open, deviation from
  the schedule, upload progress, unconfirmed commands) and an inline day
  editor with copy-to-days that uploads via `set_week_profile_days`. Renders
  in a shadow root and only when its entity changes. New option `editable`.
- Climate entities refresh their attributes on pending-queue progress.
- Week profile card: `entities:` shows several thermostats of one room in one
  card (one timeline when profiles match, per-thermostat timelines for
  differing days, edits go to all); notice when the weekly program is not
  active.
- `remove_link_partner` accepts `partner_type` to remove a link to a device
  the integration does not know.
- Detects devices still paired with another controller (e.g. an old MAX!
  Cube): repair issue, pairing state `paired_elsewhere`, notice in the week
  profile card. Such devices need a factory reset before pairing.
- Re-pairing a known device keeps its links, group, schedule and stored
  configuration (previously the record was replaced).
- Translations (de/en) for repair issues and the config flow.
- External room sensor per radiator thermostat (virtual wall thermostat):
  regulate on any Home Assistant temperature sensor instead of the sensor at
  the radiator; selectable in the week profile card or via
  `set_external_temperature_sensor`, off by default.

### 0.3.0

- Requires Home Assistant 2026.11 or newer. Uses the native climate
  temperature attributes and per-config-entry device lookups (removes the
  deprecation warnings that would break in 2027.8/2027.11).
- Adapts to the CUL's send budget: an `extended` send profile with faster and
  more retries is used when culfw reports a clearly larger budget or faster
  recovery; the recovery rate is measured. See the integration README, including
  the legal notice on modified firmware.
- New diagnostic sensor `Send Budget` on the `MAX! CUL` device.

### 0.2.0

- Read the CUL send budget from culfw (`X`) instead of a too conservative
  estimate; handle `LOVF`; detect firmware with a larger budget.
- Prioritized command queue: interactive changes overtake background traffic.
- Time synchronization uses one acknowledged packet instead of three blind ones.
- Enable culfw auto-ACK (`Za`) so wall thermostats and window contacts no
  longer repeat telegrams to the central.
- Apply the state carried in thermostat ACKs and wall-thermostat
  `SetTemperature` telegrams for fresher values; fix wall thermostats shown as
  `manual` while in `auto`.
- Climate entities: immediate display with `command_status`,
  `command_requested` and `command_error`, rollback on failure, `off` for
  manual 4.5 °C, preset `none` to leave boost.
- Debounced storage writes; time-information replies no longer block the
  receive loop.

## License

See [`LICENSE`](LICENSE).
