# Daze Wallbox

[![Version](https://img.shields.io/github/v/tag/tarrinho/daze-addon?label=version&sort=semver&color=blue)](https://github.com/tarrinho/daze-addon/releases)
[![HA Community](https://img.shields.io/badge/Home%20Assistant-2025.x-41BDF5?logo=homeassistant)](https://www.home-assistant.io/)
[![HACS Validation](https://github.com/tarrinho/daze-addon/actions/workflows/validate.yaml/badge.svg)](https://github.com/tarrinho/daze-addon/actions/workflows/validate.yaml)
[![GitHub](https://img.shields.io/github/license/tarrinho/daze-addon)](LICENSE)

Home Assistant integration for **Daze WallBox EV chargers**. Monitor charging metrics in real time and control your wallbox directly from your HA dashboard — no separate app required.

Daze wallboxes are managed through the [Daze web portal](https://webportal.dazeservice.com). This integration bridges the gap, bringing your wallbox into Home Assistant alongside all your other smart home devices.

> **This is a fork.** The original integration was created by **Andrea Restello** ([@arest](https://github.com/arest)) at [arest/daze-addon](https://github.com/arest/daze-addon), and all of the original design and implementation is his work. This fork, maintained by **Pedro Tarrinho** ([@tarrinho](https://github.com/tarrinho)), adds fixes found while running it against a DT01 charger — see [Changes in this fork](#changes-in-this-fork).

---

## Features

- **Real-time monitoring** — Power (W), delivered energy (Wh), charging current per phase (mA), AC voltage per phase (V), board and case temperatures (°C)
- **EVSE status** — See whether the wallbox is charging, idle, paused, or in error
- **Charge control** — Start and stop charging from HA switches, automations, or dashboards
- **Charging limit** — Set it in amps or in watts. Both bounds come from the charger: its power floor at the measured voltage, and the installation rating
- **Operation mode** — Switch between eco, fast, scheduled, and other modes
- **Session history** — Track energy, duration, and cost per recharge session
- **Lifetime totals** — Total energy delivered and session count
- **Diagnostics** — Grid max power, photovoltaic presence, three-phase supply info
- **Fully UI-driven** — Set up entirely through the Home Assistant UI, no YAML editing required

---

## Installation

### Via HACS (recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance
2. Go to **HACS → Integrations**
3. Click the three dots in the top-right corner and select **Custom repositories**
4. Add this repository URL:
   ```
   https://github.com/tarrinho/daze-addon
   ```
5. Select **Integration** as the category and click **Add**
6. Close the dialog — the Daze Wallbox integration should now appear in HACS
7. Click **Install** on the Daze Wallbox card
8. Restart Home Assistant

### Manual installation

1. Copy the `custom_components/daze/` directory from this repository into your Home Assistant `custom_components/` directory
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Devices & services**
2. Click **Add integration** and search for **Daze Wallbox**
3. Enter your Daze **Access Token** and **Refresh Token**

   > **Where to find your tokens:** These are obtained from the Daze web portal ([webportal.dazeservice.com](https://webportal.dazeservice.com)) or the developer console. The integration uses a personal access token model — not email/password.

4. Click **Submit** — the integration validates your tokens
5. Select your **network** (installation location) from the list
6. Review the confirmation screen with your wallbox details
7. Click **Submit** to complete setup

The wallbox should now appear as a single device with all sensors and controls grouped under it.

### Re-authentication

If your tokens expire, the integration will automatically prompt you to re-enter them through the HA UI. You'll see a notification and a re-authentication flow.

### Minting tokens with `tools/get_tokens.py`

Copying tokens out of a browser is fiddly, so there is a script that
exchanges a Daze username and password for them:

```bash
python3 tools/get_tokens.py
```

**Run it on your own machine. Never install or run it on the Home
Assistant host.** This integration is deliberately built to hold tokens
and nothing else — Home Assistant never receives, and must never be
given, your Daze username or password. The script exists so that stays
true; running it on the HA host would defeat the point of it.

It prompts for the username and password on hidden stdin prompts, takes
no command-line arguments and reads no environment variables (either
would leave the password in `ps` output or shell history), writes
nothing to disk and logs nothing. Before printing anything it verifies
the tokens three ways — against Cognito, against a real Daze API call,
and against the token endpoint the integration later refreshes with — so
a token that would fail an hour after setup fails here instead. If any
check fails it says which and prints no tokens.

Paste the two tokens it prints into **Settings → Devices & services →
Daze**, through the re-authentication flow above. Clear your terminal
scrollback afterwards: a refresh token is a credential and outlives the
access token by a long way.

The script is kept out of what users install, by three separate
mechanisms, and `tests/test_release_excludes_tools.py` holds all three
in place. HACS installs `custom_components/daze` only, so nothing under
`tools/` reaches an HA host through it; `hacs.json` sets no
`zip_release` that would change this; and `.gitattributes` marks
`tools/` `export-ignore`, which keeps it out of the source archives
GitHub attaches to a release.

To be clear about what that last one does and does not buy:
`export-ignore` affects `git archive` only. The script remains in the
repository, remains visible on GitHub, and still arrives with a
`git clone`. It is not hidden and is not meant to be — it is simply
absent from the artefact people install from.

---

## Entities

### Sensors

| Entity ID | Name | Device Class | State Class | Unit |
|-----------|------|-------------|-------------|------|
| `sensor.daze_instant_power` | Instant Power | `power` | `measurement` | W |
| `sensor.daze_delivered_energy` | Delivered Energy | `energy` | `total_increasing` | Wh |
| `sensor.daze_charging_current_l1` | Charging Current L1 | `current` | `measurement` | mA |
| `sensor.daze_charging_current_l2` | Charging Current L2 | `current` | `measurement` | mA |
| `sensor.daze_charging_current_l3` | Charging Current L3 | `current` | `measurement` | mA |
| `sensor.daze_ac_voltage_l1` | AC Voltage L1 | `voltage` | `measurement` | V |
| `sensor.daze_ac_voltage_l2` | AC Voltage L2 | `voltage` | `measurement` | V |
| `sensor.daze_ac_voltage_l3` | AC Voltage L3 | `voltage` | `measurement` | V |
| `sensor.daze_board_temperature` | Board Temperature | `temperature` | `measurement` | °C |
| `sensor.daze_case_temperature` | Case Temperature | `temperature` | `measurement` | °C |
| `sensor.daze_evse_status` | EVSE Status | `enum` | — | idle / waiting_for_ev / charging / paused / error / offline |
| `sensor.daze_lifetime_energy` | Lifetime Energy | `energy` | `total_increasing` | Wh |
| `sensor.daze_total_sessions` | Total Sessions | — | `total_increasing` | sessions |
| `sensor.daze_solar_surplus` | Solar surplus | `power` | `measurement` | W |

#### Diagnostic sensors

| Entity ID | Name | Device Class | Category |
|-----------|------|-------------|----------|
| `sensor.daze_grid_max_power` | Grid Max Power | `power` | diagnostic |
| `sensor.daze_is_photovoltaic` | Photovoltaic Present | `enum` | diagnostic |
| `sensor.daze_is_three_phase` | Three-Phase Supply | `enum` | diagnostic |

### Controls

| Platform | Entity ID | Name | Purpose |
|----------|-----------|------|---------|
| Switch | `switch.daze_charge_control` | Charge Control | Start / stop charging |
| Number | `number.daze_max_charging_current` | Current | Charging current limit, bounded by the charger's own floor and the installation rating |
| Number | `number.daze_max_charging_power` | Power | The same limit in watts, bounded by the charger's 1.5 kW floor |
| Select | `select.daze_operation_mode` | Operation Mode | Switch between eco, fast, scheduled |
| Select | `select.daze_solar_control` | Solar control | `off` / `simulate` / `active` |
| Number | `number.daze_solar_reserve` | Solar reserve | Watts to leave for the house before the car gets any |

No entity in this integration sets an explicit name or translation
key, so none of the IDs above are guaranteed — they follow the device
name, and a renamed device changes the prefix. Confirm the real object
IDs for your own install under **Settings → Devices & services →
[your device] → entities** before using them in an automation.

---

## Services

These services are available for automations and scripts:

### `daze.start_charge`

Start charging on a Daze wallbox.

```yaml
service: daze.start_charge
```

### `daze.stop_charge`

Stop charging on a Daze wallbox.

```yaml
service: daze.stop_charge
```

### `daze.set_charging_current`

Set the maximum charging current.

| Field | Required | Description |
|-------|----------|-------------|
| `current` | Yes | Maximum charging current in milliamps (mA). Range: 6000–32000, step 100. |

```yaml
service: daze.set_charging_current
data:
  current: 16000
```

---

## Solar control

Charges the car from what the house would otherwise export, adjusting
the limit as production and load change, and stopping when there is not
enough surplus to charge at all.

The controller itself defaults to **off**, so nothing runs before the
entities exist. But the **Solar control** select lands on `simulate`
the first time it is added — a fresh install never actually shows
`off`. In `simulate` it decides and logs but sends nothing to the
charger; nothing reaches hardware until you pick `active` yourself.

1. In the integration's options, pick one **signed grid power** sensor and
   answer **grid supply**: single-phase or three-phase. Positive grid power
   means import; negative grid power means export. If your meter exposes
   separate positive import and export sensors, create a signed helper first
   as shown in `docs/solar-surplus-charging.md`. Grid supply is a declaration,
   not something the integration can detect — the Daze API does not report
   how many phases feed the house — and solar control refuses to arm until it
   is answered. If you are upgrading from an earlier version, select the new
   signed sensor here before arming solar control.
2. Leave **Solar control** on `simulate`. The select's attributes show
   the surplus it sees and what it would have done.
3. Leave it for a day, then work through the validation checklist
   below before switching to `active`.
4. If the decisions look right, set it to `active`.

### Choosing the grid power sensor

Pick an **instantaneous** net-grid power sensor in **watts (W)**.
Positive = importing (drawing from grid). Negative = exporting
(feeding back to grid). The integration will not accept energy totals
(kWh) or sensors in any unit other than W.

**Correct choices:**

- Your home grid meter / utility meter sensor.
- If your charger exposes net-grid power as an instantaneous reading
  in W, that works too.

**Do not use:**

- **PV / solar production alone.** PV output is never negative — it
  cannot represent export. Grid export happens only when PV exceeds
  total house draw.
- **House load alone.** House load is a positive consumption figure;
  it never goes negative to represent export.
- **Charger power.** That is the car's draw, not the grid exchange.
- **kWh totals.** The controller needs instantaneous W to compute
  surplus per tick.

**Adding charger draw back into the signal:** solar control computes
surplus as `car_draw - grid_power`, so when the car is charging the
charger's own draw gets subtracted from the grid power reading.
During a healthy solar charge the grid meter naturally settles near
zero W — that is expected.

**Battery homes — virtual signed-grid template:**

> A worked example of this, measured on a running installation with
> the arithmetic checked against real readings, is in
> [docs/solar-control-in-practice.md](docs/solar-control-in-practice.md).
> It also covers how to confirm your house-load figure includes the
> charger, which decides whether this template is correct or a
> feedback loop.

If your house has a battery, the physical grid meter may sit at or
near zero even when solar surplus exists, because the battery
absorbs it. Use a template that subtracts PV from house load so
solar control sees what would have hit the grid:

```yaml
value_template: >
  {% set pv = states('sensor.<pv_power>') | default(0) %}
  {% set house = states('sensor.<house_load_power>') | default(0) %}
  {{ (house | float) - (pv | float) }}
```

Replace `<pv_power>` and `<house_load_power>` with your actual
sensor IDs. House load **must include the charger** if you want the
template to reflect reality while the car is charging. Add an
`availability` guard so a dropped sensor does not silently appear as
full PV surplus:

```yaml
value_template: >
  {% set pv = states('sensor.<pv_power>') %}
  {% set house = states('sensor.<house_load_power>') %}
  {% if pv in ['unknown','unavailable'] or house in ['unknown','unavailable'] %}
    unavailable
  {% else %}
    {{ (house | float) - (pv | float) }}
  {% endif %}
```

**Verification before you trust it:**

- Does the value go to zero at night when the car is idle? If it
  does not, the sign convention is inverted.
- Does it rise (become more positive) when the car stops charging?
  Without the template above, the grid meter may stay flat because
  the battery is absorbing the change.
- At midday, with PV running and the car idle, does the value turn
  negative (export)? If it stays positive, the template is inverted
  or the PV sensor is reading energy rather than power.

**Optional smoothing:** a Statistics sensor with a 3–5 minute
`state_round` window averages out short spikes and can make the
surplus calculation more stable. Not required — pick one or the
other.

**Battery SoC floor:** a battery's minimum state-of-charge (SoC)
limit is a separate automation in Home Assistant. Solar control does
not know about SoC floors and should not be relied on to protect
them.

**The reserve** is watts to leave for the house before the car gets
any: set it to 500 and the car is only offered surplus above 500 W. It
is saved with the integration's settings and survives a restart.

It never imports to charge: the charger cannot run below 1500 W, so
when surplus falls below that it stops rather than topping up from the
grid.

Changing the charging limit yourself — from the dashboard, or from your
own automation — turns solar control off. Starting or stopping the
charge by hand does the same. It does not fight you.

### When the control is unavailable

Solar control refuses to arm rather than guess, and says why in the
log (`Solar control cannot run: …`). It is unavailable when:

- **The signed grid power sensor is not set.** It has nothing to measure.
- **The grid supply has not been declared.** The charger cannot tell
  the integration how many phases feed the house, so you have to say
  so yourself, and there is no default. A three-phase meter reports
  surplus added up across all three phases; a single-phase charger can
  only use one of them, so following that figure would load one phase
  with all three phases' surplus. For the same reason, a **three-phase
  supply with a single-phase charger is refused outright** — see the
  YAML guide below if that is your setup.
- **The charger's own eco mode is on, or it has a schedule set.**
  Something else is already deciding when the car charges, and two
  controllers fighting over one charger is worse than either alone.

### The reserve

**Solar reserve** is watts to leave for the house before the car gets
any: set it to 500 and the car is only offered surplus above 500 W. It
is saved with the integration's settings and survives a restart.

### Before you trust it

A day in `simulate` is only useful if you actually check it against
what happened. Before switching to `active`:

- **Does the surplus figure go to zero at night?** If it does not, a
  sensor's sign convention is inverted.
- **Does it rise when the car stops charging?** It should not — that
  means the car's own draw is being double-counted.
- **Set a schedule on the charger and confirm solar control refuses to
  arm, then clear it and confirm it arms again.** This is the one guard
  whose positive direction has never been confirmed on real hardware:
  it reads the charger's `nextScheduleInfo` field, and all that has
  actually been observed is that the field is null when no schedule is
  set.
- **Confirm a smart-tariff pause does not populate `nextScheduleInfo`**
  and so does not falsely refuse to arm.
- **Check the logged decisions against what actually happened** before
  switching to `active`.

For a version you build and tune yourself, see
[docs/solar-surplus-charging.md](docs/solar-surplus-charging.md).

---

## Automation Examples

For charging from solar surplus, see [docs/solar-surplus-charging.md](docs/solar-surplus-charging.md) — a worked setup that follows your export, respects the charger's 1.5 kW floor, and reads its bounds from the entity rather than hardcoding them.

If you run automations **alongside** solar control — a cheap-rate
window, a house-battery floor — read
[docs/automations-with-solar-control.md](docs/automations-with-solar-control.md)
first. Any automation that commands the charger turns solar control
off, nothing re-arms it, and the examples there include the re-arm that
closes the gap.

### Stop charging when energy price is high

```yaml
automation:
  - alias: "Stop Daze charging during peak hours"
    trigger:
      - platform: time
        at: "17:00:00"
    condition:
      - condition: state
        entity_id: switch.daze_charge_control
        state: "on"
    action:
      - service: daze.stop_charge
```

### Set charging current based on solar production

```yaml
automation:
  - alias: "Adjust Daze charging to solar surplus"
    trigger:
      - platform: numeric_state
        entity_id: sensor.solar_production
        above: 3000
    action:
      - service: daze.set_charging_current
        data:
          current: 16000
```

---

## Troubleshooting

### "Invalid tokens" during setup
Make sure you've copied the full access token and refresh token — they are long strings. Tokens must be active (not expired). Obtain fresh tokens from the Daze web portal.

### Integration shows "unavailable"
- Check your internet connection — the Daze API is cloud-based
- Verify your wallbox is online (check the Daze mobile app)
- The integration automatically retries; entities become available again once the API responds

### Re-authentication required
If your refresh token has expired, the integration will trigger a re-authentication flow. Follow the prompts in **Settings → Devices & services** to enter new tokens.

### No data or stale data
- The integration polls every 30 seconds by default
- If the Daze API returns errors, the coordinator retries automatically
- Check the Home Assistant logs for Daze-related error messages

### Sensors not updating after a control command
The integration automatically refreshes data after sending a start/stop/current command. If values don't update, wait for the next scheduled poll cycle.

### Some sensors never report a value
Not every charger populates every field the Daze API defines. On a
Dazebox C (device profile DB07), a user reported that voltage, the two
temperatures, lifetime energy and total sessions are never reported —
and the Daze web portal shows the same gaps, so the readings are
genuinely absent rather than lost on the way through.

Those entities stay unavailable rather than reading zero. That is
deliberate: a missing measurement is not a measurement of zero, and
publishing it as 0 V or 0 kWh would put a false value into your
history and, for the energy totals, record it as a meter reset.

To check whether a reading is missing at the source, open the same
charger in the Daze web portal. If the portal shows nothing or zero
there too, the charger is not reporting it and there is nothing the
integration can recover.

---

## Supported hardware

- Daze WallBox EV chargers accessible via the Daze REST API
- Tested against the DT01 device profile, and reported working on a
  Dazebox C (device profile DB07, firmware 14.0.0) by a user

Which readings you get depends on the charger. See the troubleshooting
note below on readings the API does not report.

---

## Data & privacy

- All data flows through the Daze cloud API — no local/offline control
- The integration stores only your access token and refresh token, in the Home Assistant config entry. As with every integration, that means plain text in `.storage/core.config_entries` — Home Assistant does not encrypt config entry storage. Treat your configuration directory and your backups as holding live credentials.
- The stored tokens are the ones you entered at setup, or at your last re-authentication. Refreshing an access token updates it in memory only and never writes it back, so what is on disk does not rotate on its own. Two things follow: an old backup can still hold a usable refresh token, and every restart begins again from the tokens stored at setup — which is why an integration that has been running for weeks can still ask you to re-authenticate after a restart.
- No data is sent to third parties beyond the Daze API

---

## Development

### CI/CD

The integration is validated with:
- [ruff](https://github.com/astral-sh/ruff) for linting
- [pyright](https://github.com/microsoft/pyright) for type checking
- `hassfest` for Home Assistant integration validation
- HACS validation

---

## Credits

This integration was created by **Andrea Restello** ([@arest](https://github.com/arest)).
The upstream project is [arest/daze-addon](https://github.com/arest/daze-addon).

Everything this fork does rests on his work: the integration architecture, the
config flow, the entity model, the sensor catalog and the API client were all
written upstream. He also reverse-engineered the Daze web API, which is not
publicly documented — that is the hard part, and none of what follows would
exist without it.

### Changes in this fork

Maintained by **Pedro Tarrinho** ([@tarrinho](https://github.com/tarrinho)).

Every change below was found by running the integration against a real DT01
wallbox and measuring the API's actual responses, rather than by reading the
code alone.

**Setup**

- Authenticate through the Cognito `GetUser` operation instead of
  `/oauth2/userInfo`. The Daze portal issues access tokens scoped
  `aws.cognito.signin.user.admin` without `openid`, which `userInfo` rejects,
  so setup previously failed for every user with `invalid_token`.

**Reading data**

- Read the live metrics from where the API actually returns them. Power,
  energy, currents and voltages arrive nested under `chargeSession`, not at the
  top level, so every sensor read `Unknown` with no error logged.
- Fetch the EVSE record as well as the socket state. Temperatures, the grid
  limit, eco mode and the configured current appear only there.
- Derive the charger status from the integer `evseState` plus the pause and
  error flags. The API never returns the status string the code expected.
- Report `waiting_for_ev`, the state the charger passes through after a start
  before the car begins drawing, and hold the charge switch on through it so it
  does not appear to snap back.

**Charge control**

- Send the serial number and the session ID with `playcharge` and `stopcharge`.
  An empty body is rejected with `ErrorWrongSessionID`, and the session ID alone
  is accepted but does nothing.
- Read the session ID from the charger at command time. It changes whenever a
  session ends, so a cached copy can name one that has already closed.
- Retry commands through the Daze RPC link, which fails intermittently with
  HTTP 500 code 101. Delays grow from 1.5s to 6s across eight attempts, roughly
  33 seconds in total, because a tight burst of retries does not outlast the
  outage.
- Re-read the charger at 3, 8, 15 and 30 seconds after a command, so a start or
  pause shows up promptly instead of waiting for the next poll.

**Robustness and diagnostics**

- Treat HTTP 404 from the recharge-session endpoint as a durable condition.
  It was retried every 30 seconds and logged a warning each time.
- Throttle the session history fetch to once every five minutes instead of
  requesting up to 1000 records twice a minute.
- Log retried failures at debug and report a single warning only when a command
  genuinely gives up, instead of one warning per attempt.
- Add diagnostic tools under `tools/` for reproducing each API call outside
  Home Assistant, and tests that use captured API responses as fixtures.

These are bug fixes to someone else's design, not a redesign. If the upstream
project adopts them, this fork becomes unnecessary.

### License

This project is licensed under the [MIT License](LICENSE), Copyright (c) 2025
Andrea Restello, carried over unchanged from the upstream project.
