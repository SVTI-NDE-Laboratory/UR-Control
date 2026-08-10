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

`start`

Start of the obstacle zone measured along the line from the start point. Unit: `m`.

`end`

End of the obstacle zone measured along the line from the start point. Unit: `m`.

`high_low_distance`

Distance between the high safe plane and the low measurement plane. Unit: `m`.

`direction_high_low`

Direction from high position to low position. Unit: none. This is a tool-frame vector and is normalized by the program.

## measurement

`program_path`
URP path as seen by the robot Dashboard server. Example: `Benoit/apply_force.urp`.

`contact_threshold`
Force considered contact. Unit: `N`.

`holding_force`
Force maintained after contact. Unit: `N`.

`simulation`
When `true`, reaching maximum displacement is reported as force success.

`max_displacement`

Maximum probing displacement allowed while searching for contact. Unit: `m`.

`acceleration`

Acceleration used for measurement-related `movel` translations. Unit: `m/s^2`.

`speed`

Speed used for measurement-related `movel` translations. Unit: `m/s`.

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
