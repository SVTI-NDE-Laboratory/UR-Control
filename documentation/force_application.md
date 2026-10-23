# Force application

## Tool-frame variants from UR

`src/measurement/polyscope_scripts/apply_force_from_ur.script` copies the
existing cycle and register protocol, but uses UR's supplied
`get_tcp_force_tool()` helper to rotate the measured force into the **current
actual TCP axes**. Contact compares `abs(tool_force_z)` with register 44;
`measured_force_z_signed` also exposes the signed projection in PolyScope.
Both signs count as contact, as in the original script.

The commanded force and approach displacement still use the **starting TCP
frame**, captured once. This differs from the helper's current frame if the
tool orientation changes during contact. The helper rotates torque axes too,
but does not shift the torque reference point; only force Z is used here.

Load this source into a separate PolyScope Script node/URP and select that URP
through the existing Python program-path configuration to use the new version.
The original `apply_force.script` and default program selection are unchanged.

`src/measurement/polyscope_scripts/apply_force_from_ur_direct.script` contains
the same tool-frame measurement with constants instead of any register I/O.
Load it into a PolyScope Script node to execute one cycle. Edit the constants
inside `apply_force_from_ur_direct()` to choose:

| Constant | Default | Meaning |
|---|---|---|
| `distance_max` | `0.050` m | Maximum approach displacement (50 mm) |
| `force_contact` | `15.0` N | Absolute measured tool Z contact threshold |
| `force_holding` | `20.0` N | Commanded force along starting TCP Z+ |
| `hold_duration` | `3.0` s | Hold duration starting after contact |
| `simulation` | `False` | If true, approach still moves but ignores contact |

The direct version times the hold locally using `sync()` and `get_steptime()`.
It retains the 10-second approach timeout, 20 mm/s approach speed limit, and
return to the starting pose. Failed approaches skip the hold and return.
Simulation stops force mode at its approach limit, then waits out the timer.
For calls after multiple waypoints, define both functions once, omit the final
`apply_force_from_ur_direct()` call in the definition node, and call that
function from each desired waypoint's Script node.

UR's explanation and helper source:
https://www.universal-robots.com/articles/ur/programming/get-force-and-torque-values-in-tool-coordinate-system/

## Original default version

The robot-side source is `src/measurement/polyscope_scripts/apply_force.script`.
Install it in `/Projects/BAM TTS/Programs/Apply_Force/apply_force.urp`. The original MIRA and server
sources remain historical references; the active script always uses feedback.

## Python selects when to release

`measurement.stop_method` accepts:

- `"timer"`: after real or simulated force success, Python waits for the
  configured `measurement.hold_duration` in seconds, checking safety and robot
  hold status throughout. It then acknowledges the hold.
- `"client_feedback"`: Python waits for the acquisition callback (normally the
  client's GO message), then acknowledges the hold. The duration is unused.

Both modes release identically: Python writes **input integer register 42 = 1**.
The script does not read a duration or mode register and has no normal hold
countdown or internal acknowledgement timeout. It does not switch tool voltage.
A callback error, client timeout or Python safety error requests a robot stop
instead of proceeding to another measurement. The script's force approach
limits remain active. The former time/feedback config names and data_server
boolean are accepted on read and saved as timer/client_feedback.

## Register protocol

| Register | Direction | Meaning |
|---|---|---|
| Integer 42 | Input | 0 before starting, 1 to release the force hold |
| Integer 46 | Input | 0 real, 1 simulation |
| Float 43 | Input | Maximum approach displacement in metres |
| Float 44 | Input | Measured contact threshold in newtons |
| Float 45 | Input | Commanded holding force in newtons |
| Integer 42 | Output | 0 initialized/completed, 1 force reached, 2 approach failed |

Python writes no register 47 and no float-register duration. This stays within
the installed RTDE upper integer range 42-46.

## Cycle

1. Python validates configuration, checks robot readiness and captures the
   pre-force TCP pose. It writes parameters, clears the acknowledgement to 0,
   and starts the URP.
2. The script zeros the sensor, then approaches along the captured TCP Z+
   direction using force_mode. Contact detection uses the absolute base-frame
   Z force (`abs(get_tcp_force()[2])`), matching the original feedback script.
3. Real contact sets output 42 to 1. The script maintains force while waiting
   for Python to write input 42 to 1.
4. Python waits for its timer or acquisition callback, then sends that release.
5. The script exits force mode, returns to its captured start pose, then sets
   output 42 to 0.
6. Python independently verifies the pre-force pose before the next movement.

The approach is bounded by maximum displacement and a 10-second deadline.
Failure reports status 2 and returns without waiting for acknowledgement.
The return-completion wait has a separate 30-second deadline and continuously
checks robot safety. It does not require observable motion to start within two
seconds: a small or simulated return may have no measurable displacement.
The Python timer finishes before this return deadline begins.

## Simulation

With simulation enabled, the script still performs the approach motion but
ignores measured contact. At maximum displacement or the two-second simulated
approach limit, it stops force mode and reports success. It then waits for the
same Python acknowledgement before returning. Python handles both timer and
client_feedback in simulation exactly as for real contact.

## Flexible commands

The flexible webapp uses a Python timer for its positive-duration holds.
The CLI's `force 3` also uses timer; `force manual` uses client_feedback with a
local callback that waits for `stop`. A zero-duration flexible command retains
immediate acknowledgement. All these paths use the same feedback-only script,
simulation flag, release register and verified return.
