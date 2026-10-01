# Start The Program From The CLI

This starts the measurement program with:

- configuration: `documentation\company_run\config_server.json`
- routine file: `documentation\company_run\routine.json`
- output folder: `documentation\company_run\output`

## 1. Prepare The Files

Make sure these files exist before starting:

```text
documentation\company_run\config_server.json
documentation\company_run\routine.json
```

The robot must be powered on, reachable at the configured IP, and already at
the `Home` waypoint defined in the routine file.

## 2. Prepare Python

Install the project dependencies once:

```powershell
python -m pip install -r requirements.txt
```

## 3. Start From PowerShell

From the project root, run:

```powershell
python src\program\main.py `
  --config documentation\company_run\config_server.json `
  --routines-file documentation\company_run\routine.json `
  --output-dir documentation\company_run\output
```

The program asks for terminal confirmation before it connects to the robot and
starts movement.

## 4. Output Files

The output folder receives:

```text
documentation\company_run\output\program.log
documentation\company_run\output\config_used.json
documentation\company_run\output\state.json
documentation\company_run\output\measurement_plan.json
```

## 5. Acquisition Client

With `config_server.json`, the TCP acquisition server is enabled. Start or
connect the external acquisition client before confirming the robot run.

The client should send:

```text
ALIVE
ISREADY
GO
STATE
```

`ISREADY` returns `true` or `false`. `STATE` returns a length-prefixed JSON
payload.
