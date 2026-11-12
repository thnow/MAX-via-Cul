# Ideas for later

Features that are worth building but not scheduled yet. Several come from the
fork by [siebenbit](https://github.com/siebenbit/MAX-via-Cul), which solved
them in its own architecture; here they would be rebuilt on top of the current
coordinator.

## Transmission queue card

A Lovelace card that shows what is waiting for radio time. With the 1 % duty
cycle (36 s per hour, about one second of preamble per MAX! packet), larger
changes – week profiles, vacation for the whole flat, several room sensors –
trickle out over minutes. The card would make that visible instead of leaving
the user guessing.

- one row per queued command: device (current HA name), what it does
  (week profile day, set temperature, time sync, …), priority, attempt and
  waiting reason (credit, ACK, retry backoff)
- send budget: current credit, recovery per second, estimated time until the
  queue is empty
- actions: remove a queued command, clear everything for a device
- read-only data via a websocket subscription or a sensor with attributes;
  no extra radio traffic

Fork reference: `frontend/cul-max-queue-card.js`, `queue.py`.

## Pairing card with live results and name suggestions

A card that guides pairing instead of a button plus a binary sensor.

- start pairing on a chosen gateway (several CULs), countdown
- live list of devices that answered in this session: type, serial, whether
  already known, and devices that were rejected because they still belong to
  another central (with the hint to factory-reset them)
- suggested name from device type and area ("Thermostat Bad",
  "Fensterkontakt Küche links"), editable before saving; area selection
- after pairing: offer to add the device to the room (links, group) and to
  sync the time

Fork reference: `frontend/cul-max-pairing-card.js`, `pairing.py`,
`pairing_api.py`.

## Temporary change until the next switching point (week profile card)

"A bit warmer / cooler until the program switches next" directly in the week
profile card, so the normal thermostat card is not needed for that (and can be
hidden). Especially useful for cards with several thermostats and no wall
thermostat (e.g. kitchen: links + rechts), where one tap should change all of
them.

How MAX! does it: the thermostat stays in **auto** and gets `SetTemperature`
with mode auto and the new temperature (`async_set_temperature(addr, temp,
mode=MODE_AUTO)`, same as `climate.set_temperature` while in auto). It keeps
that target until its next switching point and then follows the week program
again – nothing has to be reset afterwards.

Card UI:

- next to the target chip a compact `−` / `+` (0.5 °C steps), or tapping the
  target chip opens a small stepper; changes are debounced locally (~1 s) so
  several taps become one radio packet per thermostat
- status line while active: "19,5 °C bis 22:00 (danach 18 °C laut Plan)",
  computed from the profile (`expected_week_profile_temperature`, next switch
  point – the card already has `_nextSwitch`)
- "zurück zum Plan" resets right away (auto with temperature 0 → the
  thermostat takes the profile value)
- several thermostats in the card: one change is sent to all of them (one
  `climate.set_temperature` per entity, they queue one after the other); the
  status shows the common value or "unterschiedlich"
- a room with a wall thermostat: the card's entity is the wall thermostat; it
  passes the new target on to its radiator thermostats itself

Things to respect:

- only offered while the thermostat is in auto (in manual the card keeps
  showing "Wochenprogramm nicht aktiv")
- vacation and boost: hide the stepper
- external room sensor: `_intended_target` already keeps a target that was
  changed after the current segment began and returns to the profile value at
  the next segment – no extra work, but test it
- the profile mismatch warning ("Weicht vom Plan ab") must not fire for such a
  deliberate temporary change: show the temporary-change status instead
  (e.g. track `last_target_change_at` ≥ segment start as "temporary")
- unknown profile days (program set elsewhere): no "bis …" time, just the value
