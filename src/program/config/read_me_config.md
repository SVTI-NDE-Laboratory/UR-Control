# Measurement Configuration

`config.json` contains the parameters used for the measurement line.

## line

`length`

Total measurement line length. Unit: `m`.

`increment`

Distance between two consecutive measurement positions. Unit: `m`.

`direction_start_end`

Direction of motion from the start of the line to the end of the line. Unit: none. This is a tool-frame vector and is normalized by the program.

## obstacle

The complete `obstacle` object is optional. It may also be present without
`start` and `end`; both cases mean that every line point is measured. `start`
and `end` must always be supplied together.

`start`

Start of the obstacle zone measured along the line from the start point. Unit: `m`.

`end`

End of the obstacle zone measured along the line from the start point. Unit: `m`.

`high_low_distance`

Distance between the high safe plane and the low measurement plane. Unit: `m`.

`direction_high_low`

Direction from high position to low position. Unit: none. This is a tool-frame vector and is normalized by the program.

`high_low_distance` and `direction_high_low` are also optional and must be
supplied together. They are required whenever `start` and `end` define an
obstacle, because the robot must rise to the safe plane before crossing it.

Obstacle avoidance considers the entire path between consecutive measurement
points. An obstacle is therefore crossed at the high level even when it falls
exactly between two points and contains no measurement position.

## motion

One general motion dictionary is used for measurement traversal: high/low
travel, line travel, obstacle jumps, and failure recovery. It does not alter
motion inside the controller-side force program.

`type`

Motion type. This must currently be `l` because all measurement traversal is
linear Cartesian motion.

`acceleration`

Acceleration for measurement-related `movel` commands. Unit: `m/s^2`.

`speed`

Speed for measurement-related `movel` commands. Unit: `m/s`.

## measurement

`program_path`
URP path as seen by the robot Dashboard server. Example: `Benoit/apply_force.urp`.

`contact_threshold`
Force considered contact. Unit: `N`. It must be positive for a real
measurement. Setting both force values to zero selects zero-force simulation.

`holding_force`
Force maintained after contact. Unit: `N`. It must be greater than or equal to
`contact_threshold`. Setting only one force value to zero is invalid.

`simulation`
When `true`, reaching maximum displacement is reported as force success. The
program sets this automatically when contact and holding force are both zero;
that zero-force simulation skips the controller-side force cycle.

`max_displacement`

Maximum probing displacement allowed while searching for contact. Unit: `m`.

`force_step_distance`

Optional step size used by the Python-stepped fallback force approach. Unit: `m`. If omitted, the fallback uses the smaller of `0.001 m` and `max_displacement`.

`force_direction`

Optional probing direction in the tool frame for the Python-stepped fallback. Unit: none. If omitted, the fallback uses `obstacle.direction_high_low`.

## Force program

The Python force interface is `src/measurement/apply_force.py`. The readable
source corresponding to the controller-side URP is stored at:

```text
src/measurement/polyscope_scripts/apply_force_logic.script
```

The force approach speed, force-mode `stopl` deceleration, and return `movel`
speed and acceleration remain hardcoded in that script. Python sends only the
maximum distance, contact threshold, and holding force through input double
registers 43-45. After changing the local script, update the Script node in
`Benoit/apply_force.urp` on the robot controller.
