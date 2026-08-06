# Program entry point

`main.py` runs the complete sequence:

```text
start routine -> measurements -> end routine
```

It reads:

```text
Configuration/routines.json
Configuration/measurement_config.json
```

It writes:

```text
Configuration/state.json
```

`main.py` automatically starts the simulated data acquisition server before the
robot sequence and stops it at the end.

The script asks for terminal confirmation before connecting and moving.

```powershell
python Code\Program\main.py
```
