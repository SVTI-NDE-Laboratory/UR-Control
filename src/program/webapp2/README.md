# UR15 WebApp 2.0

Run from the project root using the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe tools\webapp2.py
```

The launcher opens a local browser tab. The original `tools/webapp.py` and all
CLI tools remain available; no existing source files were changed. Run only one
control application at a time: the shared worker lock belongs to this WebApp
process and cannot prevent a separately launched CLI or original app from
commanding the same robot.

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
   The hold defaults to three seconds and is limited to eight seconds because
   the shipped controller program times out its acknowledgement after ten.
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
The gear-shaped Settings button above Close app opens an empty Settings page.
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

## Fixed installation settings

`settings.py` hardcodes `routine_bam_at_svti.json` and robot IP `192.168.3.10`.
There is no browser API to select a different file. The flexible CLI's force
settings supply the force program path and maximum displacement; the threshold,
holding force and duration are set in the flexible form.
Holding force must be positive and at least the threshold.

## Implementation and verification

- `server.py` adds the shell, manual/status APIs, fixed-file enforcement and
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
  runtime directory `temporary_data/webapp2/` or the automatic run's output folder.

Run the hardware-free tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The HTTP tests use `httpx`, which is already installed in this workspace's
virtual environment. On a new environment install it separately for testing;
WebApp 2.0 itself uses only the project's existing runtime dependencies.

The tests exercise the HTTP routes, fixed-file enforcement, motion units,
routine start and plane checks, a complete simulated flexible session, command
exclusivity/stop ordering, automatic feedback connection reuse, and the real
local acquisition socket protocol.
They do not validate physical robot motion. Commission the manual moves,
local force cycle and automatic sequence on the actual installation before routine
operation. A browser rendering test also requires a local browser; no automated
browser driver is included in the existing environment.
