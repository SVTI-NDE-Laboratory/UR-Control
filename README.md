# UR Control

Python utilities for setting Universal Robots values from a PC and then starting a robot program.

## Concept

The main workflow is:

1. Python connects to the robot through RTDE.
2. Python writes values into RTDE input float registers.
3. The URP program reads those input registers into normal program variables.
4. Python connects to the Dashboard Server.
5. Python loads the selected `.urp` program and starts it after a confirmation prompt.

This lets the same robot program run with different parameters without editing the program on the teach pendant each time.

## Current RTDE Variables

The script in `Scripts/set_5_rtde_variables_and_start_program.py` defines these five values:

```python
avoid_start = 10.0
avoid_end = 20.0
avoid_gap = 30.0
line_incr = 40.0
line_length = 50.0
```

They are then assigned to RTDE input float registers:

```python
RTDE_FLOAT_VALUES = {
    18: avoid_start,
    19: avoid_end,
    20: avoid_gap,
    21: line_incr,
    22: line_length,
}
```

In the URP program, add a Script node near the start of the program, or in `BeforeStart`, to copy the RTDE register values into UR variables:

```urscript
avoid_start = read_input_float_register(18)
avoid_end = read_input_float_register(19)
avoid_gap = read_input_float_register(20)
line_incr = read_input_float_register(21)
line_length = read_input_float_register(22)
```

After that, the URP program can use `avoid_start`, `avoid_end`, `avoid_gap`, `line_incr`, and `line_length` like normal variables.

## Starting The Program

The Python script also uses the Dashboard Server on port `29999` to load and start the robot program:

```python
PROGRAM_NAME = "Benoit / Code Base/Benoit.urp"
```

If the Dashboard Server does not accept spaces around the folder separator, use:

```python
PROGRAM_NAME = "Benoit/Code Base/Benoit.urp"
```

## Requirements

Install the RTDE Python package:

```powershell
python -m pip install ur_rtde
```

The robot must have:

- Remote control enabled.
- Dashboard Server access available on port `29999`.
- RTDE access available.
- A URP program that reads the same RTDE registers used by the Python script.
