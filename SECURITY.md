# Security Policy

## Supported versions

Only the latest release of MAX! via CUL receives fixes. Please update to the
newest version before reporting a problem.

| Version | Supported |
| ------- | --------- |
| latest release (0.6.x) | yes |
| older releases | no |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report them privately via GitHub:
[Security → Report a vulnerability](https://github.com/thnow/MAX-via-Cul/security/advisories/new).

Helpful details:

- affected version and Home Assistant version
- connection type (CUL via USB, CUNO / flashed Cube via TCP)
- steps to reproduce, logs or a proof of concept (please remove addresses,
  hostnames and tokens)

You will get a first answer within a week. Fixes are released as a new
version and, where useful, published as a GitHub security advisory.

## Scope

In scope:

- the integration code in `custom_components/cul_max` (config flow,
  websocket API, services, diagnostics)
- the bundled dashboard cards in `custom_components/cul_max/frontend`

Out of scope:

- the MAX! radio protocol itself. It has no encryption and no real
  authentication; anyone in radio range with a CUL can send MAX! frames.
  The integration cannot fix this.
- culfw / a-culfw firmware and the network exposure of a CUNO or flashed
  Cube (keep its TCP port inside your local network)
- Home Assistant core
