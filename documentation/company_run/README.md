# Company Run Package

This folder contains one self-contained CLI run setup:

- `config_server.json`: measurement configuration with the TCP acquisition server enabled
- `routine.json`: waypoint and routine definition used by the run
- `output\`: run output folder

## Start The Program

Install the project dependencies once:

```powershell
python -m pip install -r requirements.txt
```

From the project root, run:

```powershell
python src\program\main.py `
  --config documentation\company_run\config_server.json `
  --routines-file documentation\company_run\routine.json `
  --output-dir documentation\company_run\output
```

The program asks for terminal confirmation before it connects to the robot and
starts movement.

## Before Confirming

Check that:

- the robot is powered on and reachable
- the robot is at the `Home` waypoint from `routine.json`
- the force program from `config_server.json` exists on the robot
- the external acquisition client has connected and sent `ALIVE`

## Output Files

After a run, `output\` contains:

```text
program.log
config_used.json
state.json
measurement_plan.json
```

## TCP Client Notes

The acquisition client can send:

```text
ALIVE
ISREADY
GO
STATE
```

`ISREADY` returns `true` or `false` directly. `STATE` returns a 4-byte length
prefix followed by JSON, for example:

```json
{"X":1,"Y":11,"Point":1,"Moving":true,"Error":"ok"}
```
