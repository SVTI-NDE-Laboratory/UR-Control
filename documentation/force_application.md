# Force application

Webapp2 uses one target force and a settling delay, with separate real and
guarded travel simulation URPs. Python controls measurement completion in both.

## Controller programs

Install `src/measurement/polyscope_scripts/apply_force_from_ur_settling.script`
in the URP configured by `force.program_path`. The default path is
`/programs/Projects/BAM TTS/Programs/Apply_Force/apply_force_v2.urp`.
`apply_force.script` contains the same real cycle.

Install `src/measurement/polyscope_scripts/apply_force_simulation.script` in the
URP configured by `force.simulation_program_path`. The default path is
`/programs/Projects/BAM TTS/Programs/Apply_Force/apply_force_simulation_v2.urp`.
Saving sources locally does not update a controller-side URP; update the Script
node and save each program on the robot.

## Configuration

- `target_force`: positive target force in newtons; default 200 N.
- `settling_time`: nonnegative delay in seconds; default 1.5 s.
- `max_displacement`: positive approach displacement limit in millimetres.
- `simulation`: selects the guarded travel simulation URP when true.
- `stop_method`: `timer` or `client_feedback`.
- `hold_duration`: positive timer duration, starting after readiness.
- `program_path`: real controller-side force URP.
- `simulation_program_path`: guarded travel simulation URP.

Saved configurations are normalized to one target, preserving the configured
holding-force value when reading a two-force configuration. A zero/zero
configuration selects simulation with a 200 N stored target. Profiles retain
custom real paths, targets and other user settings during schema migration.

## Register protocol

| Register | Direction | Meaning |
|---|---|---|
| Float 43 | Python to robot | Maximum displacement [m] |
| Float 44 | Python to robot | Settling delay [s] |
| Float 45 | Python to robot | Target force [N] |
| Integer 42 | Python to robot | 0 before starting, 1 to release measurement |
| Integer 42 | Robot to Python | 0 initialized/completed, 1 ready, 2 approach/distance failure |

Additional failure statuses: 4 = invalid settings, 5 = simulation force guard,
6 = simulation motion timeout. Status 5 or 6 aborts without automatic return.

Python writes no simulation flag register. It chooses the correct URP before
starting and waits for readiness with a deadline that includes settling time.
Stationary settling does not count as stalled approach motion.

## Real cycle

1. Capture starting pose, zero the force sensor, and enter force mode once.
2. Approach along starting TCP Z+ until absolute current-tool Z force reaches
   the target. `force_reached` becomes true at that first crossing.
3. Maintain the target for `settling_time`. Force dips do not restart the delay.
   `force_ready` then becomes true and output 42 becomes 1. This timer-based
   readiness does not certify measured force stability.
4. Python starts its timer or acquisition callback. RTM/client completion and
   timer completion both write input 42 = 1.
5. End force mode, stop residual motion, return to the captured pose, and clear
   output 42 to 0. Python verifies the pre-force pose before proceeding.

Distance limits apply during approach, settling and measurement. The real
approach timeout is 10 s; the force-stage speed cap is 20 mm/s. Return speed and
acceleration are 40 mm/s and 100 mm/s^2. Both state messages and operator-facing
variables are visible in PolyScope.

## Moving simulation

The simulation reads floats 43/44/45. It travels the distance in register 43
along the starting TCP Z+ axis at up to 5 mm/s, tapering near the endpoint.
It does not enter force mode or apply the target in register 45. At the endpoint,
`force_reached` becomes true; after register 44's settling delay, `force_ready`
becomes true and output 42 = 1. Python releases through input 42 = 1, then the
script returns at up to 20 mm/s and clears output 42. Python's approach deadline
includes the configured travel time and settling delay.

After completion, Python observes the return for up to 2 seconds and requires
0.2 seconds continuously within 1 mm position error, 0.01 rad orientation
error, 2 mm/s linear speed and 0.01 rad/s angular speed. This passive check
allows pose/speed feedback to settle after the completion status arrives.
It sends no corrective movement. A failed verification reports all measured
errors and their limits, stops the program and leaves automatic correction disabled.

The resultant XYZ force is checked every control step during travel, settling,
measurement and return. At 40 N the script stops and latches status 5, without
an automatic return. The sensor is not zeroed, so existing contact is visible.
40 N leaves margin below 50 N, but this software guard cannot guarantee a 50 N
peak limit: sensing latency and stopping dynamics can cause overshoot. It does
not replace the controller's safety-rated force limits. Motion timeouts latch
status 6 and also stop in place.

## Offline verification

Tests cover the one-target schema, register units, real/simulation URP selection,
configurable settling, timer/client release, guarded simulation travel, and verified
return. Controller parsing and physical execution require robot-side validation.
