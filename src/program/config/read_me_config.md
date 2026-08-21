# Measurement Configuration

`config.json` remains the default for direct `main.py` runs. The web panel keeps
mode-specific defaults in `config_translation.json` and
`config_point_to_point.json`, then writes the validated selection to
`config_tmp.json` for a control-panel run.

## line

`method` selects `translation` or `point_to_point`. Parameters for the selected
method are stored in `line.parameters`.

### Translation parameters

`line_length` is the total line length in metres. `increment` is the distance
between measurements in metres. `direction_start_end` is the normalized
tool-frame direction from the start toward the end.

`high_low_distance` is the safe-plane clearance in metres and
`direction_high_low` is the normalized tool-frame direction from high to low.
Both are required for translation mode.

### Point-to-point parameters

Point-to-point web configurations always use the Cartesian waypoints
`p_start_l` and `p_end_l` from the routine file selected in the control panel.
`number_of_measurements` includes both endpoints and must be at least two.
`increment` is the corresponding distance between points; the web controls keep
the two values synchronized, so either can be edited.

The program interpolates all three base-frame position coordinates and keeps
the orientation taught at the start waypoint. The end waypoint orientation is
ignored. Safe clearance direction and distance are deduced from the full
three-dimensional position difference between `p_start_h` and the configured
start waypoint.

Example:

```json
"line": {
  "method": "point_to_point",
  "parameters": {
    "start_point": "p_start_l",
    "end_point": "p_end_l",
    "number_of_measurements": 5
  }
}
```

## obstacle

The complete `obstacle` object is optional. It may also be present without
`start` and `end`; both cases mean that every line point is measured. `start`
and `end` must always be supplied together.

`start`

Start of the obstacle zone measured along the line from the start point. Unit: `m`.

`end`

End of the obstacle zone measured along the line from the start point. Unit: `m`.

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

`data_server`
When `true`, the main program starts the Python data acquisition server and
acknowledges the robot-side force hold only after that server replies. This is
the default and keeps the existing external-acquisition workflow.

When `false`, no data acquisition server is started. Use this with a URP in
`program_path` that performs acquisition internally, for example by setting the
tool voltage to 12 V, waiting 0.5 s, setting it back to 0 V, then returning to
the initial measurement pose without waiting for Python acknowledgement.

`max_displacement`

Maximum probing displacement allowed while searching for contact. Unit: `m`.

`force_step_distance`

Optional step size used by the Python-stepped fallback force approach. Unit: `m`. If omitted, the fallback uses the smaller of `0.001 m` and `max_displacement`.

`force_direction`

Optional probing direction in the tool frame for the Python-stepped fallback. Unit: none.

## Force program

The Python force interface is `src/measurement/apply_force.py`. The readable
source corresponding to the controller-side URP is stored at:

```text
src/measurement/polyscope_scripts/apply_force_logic_2.script
```

The force approach speed, force-mode `stopl` deceleration, and return `movel`
speed and acceleration remain hardcoded in that script. Python sends only the
maximum distance, contact threshold, and holding force through input double
registers 43-45. After changing the local script, update the Script node in
`Benoit/apply_force.urp` on the robot controller.

The controller limits a real force approach to 10 seconds. Simulation uses a
2-second approach timeout and then reports `force_reached = True`. Python allows
a 5-second communication margin when waiting for that controller result and
waits at most 30 seconds for return completion. A host-side timeout requests a
robot stop and aborts the measurement sequence.

When `measurement.data_server` is `true`, after force is reached, the
controller waits up to 10 seconds for register 42 acknowledgement. Main
requests data acquisition during this hold and sends the acknowledgement only
after the acquisition server replies `data_acquired`.

The actual TCP pose is captured immediately before the URP is loaded. After the
URP reports return completion, Python verifies that pose within the Cartesian
motion tolerances. A mismatch is corrected with the bounded absolute-move retry
logic before the next line translation can begin.
