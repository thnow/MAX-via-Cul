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
