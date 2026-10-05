# Force Application Flow

This document explains how one force cycle is applied by the Python program and
the robot-side URScript program.

The important distinction is:

- Python configures and supervises the force cycle.
- The physical force is applied inside the URP by URScript's built-in
  `force_mode(...)` function.

## Main Files

The Python wrapper is:

```text
src/measurement/apply_force.py
```

The robot-side URScript sources are:

```text
src/measurement/polyscope_scripts/apply_force_with_server.script
src/measurement/polyscope_scripts/apply_force_mira.script
```

The server script waits for Python to release the force hold. The MIRA script
performs the acquisition pulse on the robot by switching tool voltage.

## Python Side

The Python entry point is:

```python
apply_force(
    robot_ip,
    program_path,
    max_distance,
    contact_threshold,
    holding_force,
    simulation=False,
    acquire_data=None,
    acquisition_context=None,
    acknowledge_force_hold=True,
)
```

`max_distance` is passed to Python in millimetres. Python converts it to metres
before writing it to the robot.

Before starting the URP, Python writes the force parameters into RTDE input
registers:

| Register | Written by Python | Meaning |
|---|---:|---|
| Integer 42 | `0` initially, later `1` | Force-hold acknowledgement |
| Double 43 | `max_distance` in metres | Maximum approach distance |
| Double 44 | `contact_threshold` in newtons | Force value that means contact has been reached |
| Double 45 | `holding_force` in newtons | Force command used by `force_mode(...)` |
| Integer 46 | `0` or `1` | Simulation flag |

Then Python starts the selected URP:

```python
load_and_play_urp(robot_ip, program_path)
```

After that, Python waits for the robot program to report a status through robot
output integer register 42:

| Robot output register 42 | Meaning |
|---:|---|
| `0` | Initialized or completed |
| `1` | Force reached; robot is in the force hold |
| `2` | Maximum distance or approach timeout reached without contact |
| `3` | Robot timed out waiting for Python acknowledgement |

If the robot reports status `1`, Python starts the acquisition callback. In
server mode, that callback waits for the external client to send `GO`. In the
flexible local command, that callback can simply wait for a number of seconds or
until the operator types `stop`.

When acquisition is complete, Python writes input integer register 42 to `1`.
That tells the URScript program to leave the force hold and return to the
pre-force pose.

Finally, Python waits until the robot reports status `0` again, then verifies
that the TCP returned to the captured pre-force pose.

## URScript Side

At the start of the URScript program, the robot reads the parameters that Python
wrote:

```python
global distance_max = read_input_float_register(43)
global force_contact = read_input_float_register(44)
global force_holding = read_input_float_register(45)
global simulation = read_input_integer_register(46) == 1
```

Then it captures the current TCP pose:

```python
start_pose = get_actual_tcp_pose()
force_frame = start_pose
```

This is important. The force frame is the TCP pose at the moment the force cycle
starts. The robot applies force along the Z axis of this frame.

The force sensor is zeroed:

```python
zero_ftsensor()
sleep(0.2)
```

## The `force_mode(...)` Call

The actual physical force is applied by this URScript call:

```python
force_mode(
    force_frame,
    [0, 0, 1, 0, 0, 0],
    [0, 0, force_holding, 0, 0, 0],
    2,
    [0.010, 0.010, max_approach_speed, 0.10, 0.10, 0.10]
)
```

Parameter by parameter:

| Parameter | Value in this project | Meaning |
|---|---|---|
| Task frame | `force_frame` | The captured start TCP pose |
| Selection vector | `[0, 0, 1, 0, 0, 0]` | Only TCP Z translation is force-controlled |
| Wrench | `[0, 0, force_holding, 0, 0, 0]` | Apply `force_holding` newtons along TCP Z+ |
| Type | `2` | UR force mode frame behavior |
| Limits | `[0.010, 0.010, max_approach_speed, 0.10, 0.10, 0.10]` | Motion/force limits, with Z speed capped |

`max_approach_speed` is currently:

```python
max_approach_speed = 0.02
```

So the force approach speed is limited to `0.02 m/s`.

The force mode call is repeated inside a loop. During that loop, the robot keeps
checking measured force and travelled distance:

```python
current_pose = get_actual_tcp_pose()
relative_pose = pose_trans(pose_inv(start_pose), current_pose)
travelled_z = relative_pose[2]

measured_force = force()

if (simulation == False) and (measured_force >= force_contact):
    contact_detected = True
elif travelled_z >= distance_max:
    distance_reached = True
end
```

So the two force values have different jobs:

| Value | Job |
|---|---|
| `contact_threshold` / `force_contact` | The measured force required to say contact was reached |
| `holding_force` / `force_holding` | The commanded force used by `force_mode(...)` |

`holding_force` must be greater than or equal to `contact_threshold`.

## Contact Reached

When the measured force reaches the contact threshold, the script sets:

```python
force_reached = True
write_output_integer_register(register, 1)
```

Python sees output register 42 become `1`. That means the robot is now in the
force hold.

In `apply_force_with_server.script`, the robot continues calling
`force_mode(...)` while it waits for Python acknowledgement:

```python
while (acknowledged == False) and (timed_out == False):
    if contact_detected:
        force_mode(...)
    end

    if read_input_integer_register(register) == 1:
        acknowledged = True
    end

    sync()
end
```

In `apply_force_mira.script`, the force approach is the same, but contact
triggers a tool-voltage acquisition pulse instead:

```python
set_tool_voltage(12)
```

After the configured acquisition duration, the MIRA script turns tool voltage
off again:

```python
set_tool_voltage(0)
```

## End Of Force Cycle

After acquisition or acknowledgement, the script exits force mode:

```python
end_force_mode()
stopl(1.0)
sleep(0.1)
```

Then the robot moves back to the pose captured before the force approach:

```python
movel(
    start_pose,
    a=return_acceleration,
    v=return_speed
)
```

At the end, the robot writes output register 42 back to `0`:

```python
write_output_integer_register(register, 0)
```

Python waits for this `0`, then verifies that the actual TCP pose matches the
pre-force pose.

## Simulation

When both force values are set to zero, Python enables simulation. In simulation,
the URScript does not use measured force to detect contact. Instead, the script
waits until the short simulation timeout or maximum distance condition, then
reports force reached.

This allows the Python workflow, acquisition handshake, and return verification
to be tested without applying physical force.

## Practical Summary

The robot applies force only in the URScript `force_mode(...)` loops.

Python controls:

- which URP is started,
- the maximum travel,
- the contact threshold,
- the holding force,
- simulation mode,
- and when the force hold is released.

URScript controls:

- the force direction,
- the actual `force_mode(...)` calls,
- contact detection,
- holding force while waiting,
- exiting force mode,
- and returning to the original TCP pose.
