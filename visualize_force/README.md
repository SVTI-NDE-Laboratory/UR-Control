# Standalone force recording

This folder is independent of the existing apps and measurement workflow.
Set `ROBOT_IP` and `URP_PATH` at the top of `record.py`. By default it loads,
plays, and monitors that controller-side program through Dashboard. Set
`URP_PATH = None` to receive RTDE telemetry with manual program control.
It does not change registers, upload a script, or acknowledge force holds.

## Folder layout

- `scripts/`: UR robot `.script` sources.
- `plots/`: Python plotting and offline analysis tools.
- `recordings/`: raw CSV recordings, session metadata, and observation notes.

Recording utilities and offline tests stay at the top level.
Comparison figures retain their existing locations under `recordings/`.

## Run

For a URP using `scripts/apply_force_from_ur_settling.script`, use the separate
register recorder instead:

```powershell
.venv/Scripts/python.exe visualize_force/record_registers.py
```

Edit `ROBOT_IP`, `URP_PATH`, `TARGET_FORCE_N`, `MAX_DISTANCE_MM`, and
`SETTLING_TIME_S`, and `MEASUREMENT_DURATION_S` at the top of `record_registers.py`. Save the matching
URScript in the configured URP first. Defaults are 200 N, 50 mm, and a 3 s
measurement after the robot signals readiness (after its configured settling delay, default 1.5 s).
The recorder writes double registers 43/44/45 (distance/settling time/target force), clears input integer 42, and
releases via input 42 only after the measurement timer. It records output 42
and checks the ready/release/return sequence. Existing recordings are retained;
each run gets a new session folder.

`record.py` remains the recorder for URPs that do not require register writes.

From the project root in PowerShell, use the existing Python environment:

```powershell
.venv/Scripts/python.exe visualize_force/record.py
```

Edit the robot IP and URP path in `record.py` before running. With a URP path
configured, the recorder starts the program automatically. For manual recording,
set `URP_PATH = None`, start the recorder, then run your force cycle normally.
Press Ctrl+C after the robot has returned. For a fixed manual recording interval:

```powershell
.venv/Scripts/python.exe visualize_force/record.py --rate 100 --duration 30 --target-force 20
```

Each run creates a new timestamped directory under `visualize_force/recordings/`:

- `raw.csv`: native ur_rtde recording, written during acquisition.
- `force.csv`: raw columns plus elapsed time, sample interval, tool-frame force
  X/Y/Z [N], and absolute tool Z [N]. Generated when recording closes.
- `metadata.json`: requested rate, IP, optional manually supplied target,
  stop reason, errors, and conversion summary.

`force.csv` column order is: `timestamp`, `elapsed_s`, all six
`actual_TCP_pose_*` columns, all six `actual_TCP_force_*` columns, tool-frame
force X/Y/Z and absolute Z, then `sample_dt_s` and any optional status register.
All numeric values in `force.csv` have exactly three decimal places. Rotation
and elapsed-time calculations use the original precision before formatting.
`raw.csv` retains the native precision, including submillimetre pose changes
that rounding positions in metres to three decimals would hide.

The existing environment already has ur_rtde. For a separate environment,
install `visualize_force/requirements.txt`. Recording needs no plotting packages.

## Automatically run and record the URP

First save a new URP on the robot containing the Script node described below,
then set `URP_PATH` in `record.py` to its location. This is a **robot-side path**;
a local `.script` file cannot be passed as a `.urp`. The command does not create
or upload the URP. Set the intended start pose, TCP, payload, and force constants
before running it; the program begins force application from the current pose.

```powershell
.venv/Scripts/python.exe visualize_force/record.py --pre-roll 1 --post-roll 1 --cycle-timeout 60
```

The recorder starts native CSV capture, loads the URP, records one second before
`play`, observes the program running and stopping, records one second afterward,
then closes and converts the CSV automatically. Loading may add more baseline
time before the pre-roll. The defaults are one second before/after and a
60-second runtime timeout. `--duration` is only for manual recording and cannot
be used when `URP_PATH` is configured.

The robot must be in Remote Control, powered with brakes released, and have no
program running or paused. Those conditions are checked before loading and
playing. Safety stops, stale telemetry, pauses, missed starts, and timeouts
abort the run. Ctrl+C or an error after requesting play sends a Dashboard stop
before finalizing the CSV. Manual recording still does not send stop commands.

Automatic mode adds `safety_status_bits` at the end of the CSV. Dashboard
STOPPED means the program is no longer executing; it does not distinguish a
normal finish from an operator stop or certify that contact succeeded. The
post-roll covers the interval after program stop, including the script's return
to its initial pose before that stop. Use the self-timed script in this folder;
URPs requiring Python register acknowledgements need their normal controller.

## New robot script

Load `visualize_force/scripts/apply_force_visualize.script` into a **new PolyScope
Script node/program**. Run it from the intended starting pose with the intended
TCP and payload configured. No changes to an existing program are necessary.
The file calls its function once at the bottom.

Edit the constants in this new file before use:

| Setting | Default | Meaning |
| --- | --- | --- |
| `distance_max` | 0.050 m | Maximum approach displacement |
| `force_contact` | 15 N | Absolute current-tool Z contact threshold |
| `force_holding` | 20 N | Commanded force along starting TCP Z+ |
| `hold_duration` | 3 s | Hold duration after contact |
| `simulation` | False | If True, still moves but ignores measured contact |

The script zeros the force sensor, approaches, holds after contact, and returns
to the initial pose. It preserves the existing direct script's 10-second
approach timeout and movement settings. Failed approaches return without a
hold. Simulation stops force mode at the approach distance/time limit before
waiting out the simulated hold. PolyScope force variables refresh during both
approach and hold. No registers or PC acknowledgements are required.

In manual recording mode, stopping the recorder does not stop this robot program.

## Existing force programs

The recorder also works with existing programs without modifications. For the
register-based `apply_force_from_ur.script`, optionally add
`--status-register 42`. Its raw value is included in both CSV files:
0 = initialized/completed, 1 = force reached/waiting, 2 = approach failed.
These values do not distinguish every phase. The standalone script in this
folder does not publish register status; leave this option off when using it.
The recorder does not supply the acknowledgement needed by the existing
register-based program: keep its usual Python controller running.

## Plot offline (optional)

Install plotting support only if desired:

```powershell
.venv/Scripts/python.exe -m pip install -r visualize_force/requirements-plot.txt
.venv/Scripts/python.exe visualize_force/plots/plot.py visualize_force/recordings/<session>/force.csv
.venv/Scripts/python.exe visualize_force/plots/plot.py visualize_force/recordings/<session>/force.csv --save visualize_force/recordings/<session>/force.png --target-force 20
```

Replace `<session>` with the directory printed by the recorder. The graph shows
signed and absolute current-tool Z force against elapsed seconds. Exporting PNG
needs no window. Existing PNGs are never overwritten.

## Data interpretation and recovery

The native recorder captures force and TCP pose together, avoiding separate
Python getter calls for those quantities. `force.csv` rotates base-frame force
using the inverse of the recorded current TCP orientation, matching the
rotation in the UR helper. It does not shift torque origins or calculate a
second sensor measurement. Raw torque [Nm] and pose [m, rotation-vector rad]
remain available in the native columns.

Current-tool Z can differ from the starting-tool Z along which force is
commanded if the tool orientation changes. `--target-force` records a manual
reference; the recorder cannot discover the UR script constants automatically.
Sensor zeroing appears in the recording; do not interpret that transient as
contact. The time origin is the first recorded sample, not contact detection.

The default 100 Hz is requested, not guaranteed. The controller, network, or
recorder may skip or repeat samples. Conversion removes duplicate controller
timestamps; real intervals remain in `sample_dt_s`. No interpolation or force
filtering is applied. Connection loss or a stale timestamp ends recording with
an error and attempts conversion of the samples already written.

Ctrl+C finalizes native recording and converts it. A hard process termination
or power loss may lose buffered rows or leave an incomplete last row. The raw
CSV is retained even if conversion fails. To retry conversion into a fresh file:

```powershell
.venv/Scripts/python.exe visualize_force/force_frames.py visualize_force/recordings/<session>/raw.csv --output visualize_force/recordings/<session>/recovered_force.csv
```

Conversion refuses to overwrite existing outputs and rejects invalid telemetry
or a backwards controller timestamp. A failed conversion may leave a partial
derived CSV; the metadata reports the error. Keep the raw CSV for recovery.

## Checks

```powershell
.venv/Scripts/python.exe -m unittest discover -s visualize_force -p "test_*.py" -v
```

Tests use synthetic telemetry and mocked robot primitives. They do not validate
robot dynamics, force calibration, or parsing/execution on a real controller.

References: [ur_rtde native recording](https://sdurobotics.gitlab.io/ur_rtde/pages/examples/basic_motion/record_data_example.html),
[UR RTDE fields and behavior](https://docs.universal-robots.com/tutorials/communication-protocol-tutorials/rtde-guide.html),
[UR Dashboard commands](https://www.universal-robots.com/manuals/EN/HTML/SW5_26/Content/prod-dashboard/Dashboard_table.htm).
