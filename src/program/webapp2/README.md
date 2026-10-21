# RTM Cobot Studio

Run from the project root using the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe tools\webapp2.py
```

The launcher opens a local browser tab. The original `tools/webapp.py` and all
CLI tools remain available. Run only one
control application at a time: the shared worker lock belongs to this WebApp
process and cannot prevent a separately launched CLI or original app from
commanding the same robot.

## Installation profiles and local testing

RTM Cobot Studio uses `%LOCALAPPDATA%\RTM Cobot Studio\` by default. If the local data cannot
be found at startup, a native folder chooser asks the user to locate it. An
empty selected folder is initialized with the bundled defaults. Cancelling
leaves the data unchanged and exits. Startup then reads
`preferences.json`, resolves its `configuration_path`, validates that profile and
its referenced files, and only then loads the server. An invalid selected file
stops startup with an error instead of silently loading another installation.
Initialization and the configuration check do not contact the robot.

On upgrade, an existing default `UR15 WebApp` folder is copied and validated under
the new name before use; the original remains untouched as a backup. Internal
absolute paths are rebased to the new copy. Existing data under the new name is
never overwritten. A custom location previously selected in Settings is retained,
including a missing location that must be located again at startup. Explicit
`--data-dir` and locator overrides retain their supplied paths.

```text
RTM Cobot Studio/
  preferences.json
  profiles/default/
    app_config.json
    measurement_default.json
    acquisition.json
    routines/*.json
    routine_scripts/*.script
    robot_programs/*.script
  runtime/
  logs/
  results/                     created when automatic measurements are saved
```

Missing default files are copied from the bundled/source defaults; existing user
files are preserved. `app_config.json` selects the robot IP, routine file,
measurement defaults, acquisition settings, local robot-program directory, initial
results folder and manual/flexible form defaults (`ui_defaults`). Paths inside
it resolve against its own folder. Relative `configuration_path` values in
preferences resolve against the application data folder. Both JSON files use
`schema_version: 1`.

The **Settings** page has two panels: **Local data** and **Routine**. Only the
local data base folder is shown in full; app_config, measurement defaults,
results and the routine file use paths relative to that folder (a path on a
different Windows drive must be shown in full). Internal settings files are
not listed in the interface.

**Change folder** opens a native folder chooser. Selecting an existing WebApp
data folder validates and uses that installation on the next launch. Selecting
an empty folder copies the current data there, preserving the original folder.
Nonempty unrelated folders and overlapping source/destination folders are
rejected. Paths within copied configuration files are rebased when they refer
to files under the original data folder; external paths remain external.
Finish/stop any running action first, then close and relaunch the app to apply it.
The launch location is remembered in a small `location.json` at the original
AppData base (or the `--data-dir` base for local testing); the interface does not
display this internal file. If that saved data folder is later unavailable,
startup prompts to locate it rather than silently creating replacement data.

The **Routine** panel shows the selected routine filename. **Change file** opens
a list of JSON files in the routine directory. The selected file is checked for
valid motion targets and compatibility with the measurement defaults, then saved
to app_config. Close and relaunch RTM Cobot Studio to apply it; the running installation
and worker snapshots keep their current routine until then.

**Create a routine file** imports a PolyScope `.script` export using the existing
`create_routines_file` helper. **Choose script** uses a native file dialog starting
in `routine_scripts_directory`, a path in app_config relative to its own folder.
The initial `routine_scripts` folder contains bundled waypoint script exports;
older profiles acquire this setting on startup without replacing their other
values. A custom script directory is used without copying bundled files into it.
The Home-to-start and End-to-Home lists are prefilled from the active routine.
Edit the Home-to-start sequence (Home through
p_start_h), the End-to-Home sequence (p_end_h through Home), and joint speed,
acceleration and intermediate blend. The form creates home_to_start,
start_to_home, home_to_end and end_to_home, automatically reversing the two
sequences for the complementary routes. Each first/last step has zero blend.
Measurement waypoints follow the measurement defaults (p_start_l and p_end_l in
the seeded profile) and are read-only. Missing coordinates,
invalid targets and incompatible measurement geometry prevent saving. Creation
uses a new filename in the routine directory and never overwrites an existing
file or automatically changes the selected file. Use Change file to select the
result. Creation and file selection are blocked while a robot action is running.
Edit profile JSON files with a text editor and relaunch after editing. Workers
inherit the parent's active installation settings even after another profile is
selected. Some measurement/routine files are read afresh during operation;
do not edit these files while operating the robot.

To test the same startup flow entirely within the repository:

```powershell
.\.venv\Scripts\python.exe tools\webapp2.py --data-dir "temporary_data\RTM Cobot Studio" --check-config
.\.venv\Scripts\python.exe tools\webapp2.py --data-dir "temporary_data\RTM Cobot Studio"
```

The first command initializes and validates the files, then exits. The second
starts the interface using those files. `--no-browser` starts the server without
opening a tab. `UR15_WEBAPP_DATA_DIR` provides the same override through an
environment variable. Without an override, Python and a future executable use
the normal AppData location.

Local robot programs are reference/deployment copies. They are not uploaded to
the controller automatically. `measurement.program_path` in the measurement
defaults remains the path **on the robot**, separately from the local program
directory. This repository supplies `.script` files; add any `.urp` or
installation files required by the controller separately.

Manual and flexible files go into `runtime/<session-id>/`. Automatic state,
feedback, logs and measurement files remain in the selected results/session
folder. `results_directory` in the active app configuration is the base Results
folder. Automatic runs always create a new child folder: either a date/time name
generated on Start program, or an operator-entered name. The automatic field
shows a template until the run starts. Existing folders/files, paths and Windows
reserved names are rejected. Creation is atomic to prevent concurrent overwrites.

## Building and updating the Windows executable

Build utilities and their dependencies are grouped in `tools/build_webapp2/`:
`build.py` builds, checks and packages the release; `check_exe.py` checks an exe;
`package.py` refreshes release archives and manuals; `prepare_icon.py` regenerates
the icon. The same folder holds the PyInstaller spec and Windows version metadata.
Finished distribution files remain in `dist/`, while intermediate build files
remain in `temporary_data/webapp2-build/`. The local launcher is `tools/webapp2.py`.

Install the build dependencies into the existing project virtual environment once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r tools/build_webapp2/requirements.txt
```

Build and verify the executable after code or UI changes:

```powershell
.\.venv\Scripts\python.exe tools\build_webapp2\build.py
```

If the normal exe is running, verify a separate build without replacing it:

```powershell
.\.venv\Scripts\python.exe tools\build_webapp2\build.py --dist-dir temporary_data\webapp2-build\check-dist
```

The result is `dist/RTM Cobot Studio.exe`. Copy that single file to the target Windows
64-bit computer and launch it. Python and the robot communication libraries are
included. The app retains its console window for diagnostics and opens the
interface in the default browser. A first launch asks where to create or locate
local data; the normal AppData folder is the default search location.

The displayed product name is RTM Cobot Studio; internal script and archive names
remain unchanged. The default AppData folder is also named RTM Cobot Studio. The supplied SVTI logo is used in the header,
browser tab and Windows executable. Its checked-in icon can be regenerated from
the SVG with `python tools/build_webapp2/prepare_icon.py` after installing the build
dependencies. Windows product metadata is defined in `tools/build_webapp2/version_info.txt`.

The build also packages `dist/UR15WebApp2-release.zip`, containing the exe,
`README_FIRST.txt`, HTML and editable Word manuals, a clean default-data zip,
build metadata and checksums. The manual templates live in
`documentation/webapp2/`. They reserve space for approved robot startup,
Apply Force updates and WinSCP transfer examples. Save completed installation
manuals under a separate filename to preserve additions across package rebuilds.
The default archive is seeded from bundled source defaults, not from an operator's
working data, and contains no session logs or results. Its top-level folder is
`RTM Cobot Studio`; select that folder, which contains preferences.json, at first launch.

To regenerate documentation and release archives without rebuilding the exe:

```powershell
.\.venv\Scripts\python.exe tools\build_webapp2\package.py
```

Close the running app before replacing its exe with a newer build. Settings,
taught routines and results remain in the external local data folder. Editing
those user files does not require rebuilding. Changes to bundled initial defaults
do not overwrite existing user files on upgrade; update the selected local files
when changing an already-configured installation.

The build uses `tools/build_webapp2/webapp2.spec` and caches intermediates under
`temporary_data/webapp2-build/`. Local modules are bundled in their original
directory structure so reused modules can locate adjacent assets without edits
to the original webapp. `dist/UR15WebApp2-build.json` records build/check duration,
file size and SHA-256. Build output is excluded from Git.

Each build checks native RTDE imports, all three worker entry points, default
provisioning, HTTP pages, static assets and clean shutdown from a separate working
directory. It opens no browser or robot connection. To check an exe separately:

```powershell
.\.venv\Scripts\python.exe tools\build_webapp2\check_exe.py "dist\RTM Cobot Studio.exe"
```

These checks run on the build computer. A target-computer check is still needed
to verify the actual Windows environment, robot network and controller programs.

## Operator workflow

The **Manual** page provides direct waypoint moves and named routines. Lists come from the fixed routine
file. Linear speed/acceleration use mm/s and mm/s²; joint moves use rad/s and
rad/s². Manual linear speed defaults to 50 mm/s, with acceleration 100 mm/s².
Switching back to linear motion restores these defaults.
Manual waypoint moves allow 60 seconds per attempt; manual routines use the
same allowance per step. Motion-start and stall checks remain active.
Manual linear motion is capped at 150 mm/s and 150 mm/s²; manual joint motion is
capped at 0.5 rad/s and 0.5 rad/s². Routines use their taught parameters and
require the robot to be at the first waypoint before they can run.

**Go to waypoint** keeps the waypoint names unchanged and checks the route when
Go is clicked, using the actual robot position and selected motion type.
Home remains selectable at startup. Choosing a waypoint with only one supported
motion type selects that type automatically and restores its speed/acceleration
defaults; Home uses Joint mode because only its joint target is taught.
When a waypoint's taught connections consistently use one motion type, selecting
it also selects that type, even if both pose and joint coordinates exist.
This defaults home_to… and …to_home intermediate waypoints to Joint motion.
Manual Home and home_to…/…to_home waypoints are Joint-only. p_start_l and
p_end_l are Linear-only; p_start_h and p_end_h allow both taught motion types.
Unavailable choices are greyed out and rejected by the API and worker.
Consecutive routine neighbors are treated as supported direct moves in either
direction, using the motion type taught for that connection. Intermediate
steps are never silently skipped. The high/low pairs p_start_h ↔ p_start_l
and p_end_h ↔ p_end_l are also allowed linear moves in both directions when
both points exist. The worker checks
the actual robot position after waiting for it to settle, using the existing
movement helper's speed tolerance. Unknown or unsupported
paths pause for a confirmation popup, and Cancel makes no waypoint move.
Confirmation expires after two minutes and is tied to that worker. Before an
approved move, the worker rechecks safety and verifies that the pose and joints
have not changed. This inference does not certify clearance of a direct path.

The **Flexible measurement** tab reuses the geometry and entry/exit routines in
`src/program/commands/run_flexible_measurement.py`:

1. **Start program** requires the robot at Home, runs `home_to_start`, and
   descends to `p_start_l`.
2. **Move** goes linearly to the entered X/Y coordinates in the measurement
   frame. X runs from `p_start_l` towards `p_end_l`; Y follows the CLI's plane
   axis derived from the high/low direction. The configured range is X within
   the taught line length and Y within −400 to 0 mm. Values outside that range
   can be entered; Move warns about singularities and unexpected movement and
   defaults to No. Explicit confirmation permits that requested move in the
   taught plane. Moving back and returning Home remain available; force
   application still requires the configured range. The CLI's 100 mm/s and
   100 mm/s² limits apply.
3. **Apply force** uses the entered threshold, contact force, and local hold
   duration, then returns to the same pose. It never opens an acquisition server.
   The hold defaults to three seconds; the existing 0-to-8-second form range is
   retained. Python runs the hold timer and then releases the feedback-only
   robot script through integer register 42. A zero duration releases immediately.
   Select **Simulation** beside the force settings to run the controller's
   simulation mode with the same Apply force button. The force values are
   blurred and read-only while selected, and their values are preserved.
   If the contact threshold is not reached, a verified return to the measurement
   plane leaves the session Ready and reports the error in a popup. Adjust the
   position/settings and retry without restarting the session. Safety, return
   verification and other failures still terminate it. Automatic measurement
   failure handling is unchanged.
4. **End and return Home** returns to the entry endpoint, rises to the high
   endpoint, and runs `start_to_home`. **Stop current action** instead aborts
   the session and sends a robot stop; it does not initiate a return motion.
   Stop is available while the flexible session is Ready as well as during
   motion or force. It terminates the session and reports an error popup,
   including when no motion was taking place; acknowledge it to clear the LED.

The flexible session reserves the shared worker slot, including while waiting
for commands. Manual and automatic work cannot overlap it. RTDE disconnects
between actions; each command reconnects and verifies actual safety, stationary
TCP, plane position and tool orientation before commanding movement or force.
Plane verification allows 1 mm position error and 0.01 rad rotation error.

The **Automatic measurements** page embeds the original parameter form,
visualization, validation, data-folder selection and run controls. It uses the
same original sequence and operator/client start gates. Its routine selector
is disabled, and the backend rejects routine changes. Automatic measurements
retain their existing acquisition-server behavior.

Automatic measurements also provide a **Simulation** toggle, beside **With RTM
Program**, so forces do not need to be set to zero. Changing With RTM Program
preserves the measurement line settings. **Automatic Fit** defaults to on.
Configurations store line settings directly in `line`, without `method` or
`parameters`. `measurement.stop_method` selects `client_feedback` (With RTM Program on)
or `timer` (off), replacing `data_server`. `src/program/config/config_default.json`
is the shared initial default for automatic commands and the feedback preset.
Existing nested point-to-point configurations and their boolean `data_server`
are converted when loaded; saved configurations use the new schema. Optional
top-level obstacle settings remain unchanged.
Timer exposes **Hold Duration [s]** (`measurement.hold_duration`, default
0.5 seconds). Python handles this timer and always releases the robot through
input integer register 42. Client feedback uses the acquisition callback instead.
The script reads no mode/duration register, and register 47 is never written.
Integer 46 independently selects simulation.
At initialization and whenever re-enabled, it resets X Start to zero, X End
to the exact taught length and the lead variable to Step Size. Step Size lead
keeps the step and calculates `Count = floor((End - Start) / Increment) + 1`;
the last point may precede End. Editing Count instead calculates
`Increment = (End - Start) / (Count - 1)` and includes both ends (Count ≥ 2).
With fit off, Start, Increment and Count are independent; End is read-only and
calculated as `Start + (Count - 1) * Increment`.
X Start and X End (including the calculated End with fit off) may extend up to
100 mm beyond either taught endpoint. Starting an automatic program outside
the taught range requires an explicit confirmation with No focused by default;
the backend rejects an unconfirmed start before connecting to the robot.
The controls are labelled **Step Size [mm]** and **Nb. Points**. The visualization
updates on every edit and displays the current X range and Y offset.
Y Offset is a fixed perpendicular shift and never changes the X spacing.
Obstacle Start/End use the same taught X origin as X Start/End, including when
X Start is nonzero. Obstacles only mark existing samples as skipped; they
never change the sample coordinates or count. Preview and progress use that
same coordinate system. Plans include explicit X/Y coordinates in millimetres
alongside the existing distance-from-X-Start and TCP fields.
Automatic mode publishes live plane X/Y from the same taught frame as Flexible
mode, including confirmed positions beyond the line endpoints. Plane coordinates
are hidden during entry, obstacle detours, exit, or whenever the TCP is outside
the measurement plane. Status identifies Entry routine, Obstacle Avoidance,
Exit Routine, or the active Point number. The active point remains displayed
through acquisition and the verified return to its pre-force pose, even when
the acquisition protocol advances its next point counter. The visualization
advances immediately before travel to the next measurable point, skipping
obstacle points. Automatic feedback is polled every 200 ms while running.
State, feedback and measurement-plan JSON snapshots share an atomic writer
with a separate staging file for each write and a bounded 0.5-second retry for
Windows permission errors. Persistent failures remain errors; the previous
snapshot is retained and staging files are cleaned up.
An obstacle between the taught start and X Start also selects the existing
end-side entry route without changing the measurement grid.

The status panel remains visible beside all three tabs. Its Status field shows
one action or mode: Idle, Manual: Go to waypoint, Manual: Perform routine,
Flexible or Automatic.
Flexible status includes the active action: Entry routine, Exit Routine,
Move in plane or Apply force, and shows Ready between commands.
It reports the taught waypoint
(or —), TCP X/Y/Z, error, observed motion, force-program activity,
and acquisition client connection. The Indicators show grey labels with LEDs
only: Error is grey/red; Moving, Force mode and Acquisition are grey/green.
Force-program activity also turns Moving green during a stationary force hold.
The Webapp connection-status row is omitted.
Position values retain the last observation while idle; the cobot is not polled
while idle. The Feedback row is omitted. At first launch position is unknown.
The routine name appears without its .json suffix on one line to the left of
Close app in the header. Position rows omit unit labels and use — for unknown
or unavailable values.
The gear-shaped Settings button above Close app opens installation settings.
While a flexible session (including Ready) or automatic program is running,
navigation stays on its page. Other mode links and Settings are greyed out;
browser history and direct page URLs also return to the running program.
Navigation unlocks after the program finishes or is stopped.
Flexible measurements show measurement-frame X/Y only when the robot is in the
taught plane; entry and exit routines show — in both plane coordinate displays.
The panel remains
300 px wide across tabs, and scrollbar space is reserved so switching to a
longer page does not shift it. Tabs switch within the same page and preserve
the status panel and form values.

During Move in plane, TCP and plane coordinates refresh about every 200 ms;
plane coordinates still remain hidden during entry/exit and outside the plane.
JSON publishing retries brief Windows destination locks, uses a separate staging
file per writer, and keeps the feedback sampler alive if a publish fails.

Blocking request and worker errors open an acknowledgement popup. Dismissing
the popup clears the error indicator; an unchanged worker error does not reopen
it on each status poll. Worker state and logs retain the failure details.
TCP and plane coordinates appear as `(X, Y, Z)` and `(X, Y)` in millimetres.
The waypoint selector lists Home, p_start_h, p_start_l, p_end_h and p_end_l first
when present, followed by the other waypoints in routine-file order.

## Active installation settings

The seeded profile selects `routine_bam_at_svti.json` and robot IP `192.168.3.10`.
The routine selector within measurements stays locked to the active profile.
Use Settings to select another installation for the next launch. The threshold,
holding force and duration are set in the flexible form.
Flexible reads `measurement.program_path` and `max_displacement` from the active
measurement defaults before each force command; automatic modes use that same
program path. This URP must contain the
updated feedback-only Script node. The flexible CLI uses a Python timer for numeric
positive durations (`force 3`, `force 140 160 3`) and client-feedback mode for
`force manual`, released by typing `stop`. The script waits for Python's acknowledgement without its own hold timeout. Both paths use the shared force wrapper,
including its simulation flag, mode/duration registers and return verification.
Holding force must be positive and at least the threshold.

## Implementation and verification

- `server.py` adds the shell, manual/status/settings APIs, active-file enforcement and
  serialization of requests that change state. Original measurement routes are
  reused from `webapp.server`.
- `control.py` owns a single worker process, shared across all three modes,
  actions, and retains the existing stop API. A final robot stop is issued after
  process termination to prevent a subsequent routine step from surviving Stop.
- `manual_worker.py` calls existing motion and routine-start helpers.
- `flexible_worker.py` manages entry, movement, local force and exit using the
  existing flexible CLI helpers. Commands are handed to its process as atomic
  JSON files; only one command can be submitted while it is ready.
- `measurement_worker.py` wraps the original automatic command with observation
  hooks. It uses the sequence's existing RTDE connection rather than opening a
  monitoring connection.
- `feedback.py` samples position/movement while the action owns RTDE and tracks
  acquisition clients. JSON state and worker logs are written under the manual
  runtime directory in the application data folder or the automatic run's output folder.

Run the hardware-free tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The HTTP tests use `httpx`, which is already installed in this workspace's
virtual environment. On a new environment install it separately for testing;
RTM Cobot Studio itself uses only the project's existing runtime dependencies.

The tests exercise the HTTP routes, fixed-file enforcement, motion units,
routine start and plane checks, a complete simulated flexible session, command
exclusivity/stop ordering, automatic feedback connection reuse, and the real
local acquisition socket protocol.
They do not validate physical robot motion. Commission the manual moves,
local force cycle and automatic sequence on the actual installation before routine
operation. A browser rendering test also requires a local browser; no automated
browser driver is included in the existing environment.
