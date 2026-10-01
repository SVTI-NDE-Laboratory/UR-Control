# Start The Program

Use this guide first:

```text
documentation\company_run\README.md
```

It explains everything needed to run the program:

1. install Python dependencies
2. check the robot network
3. prepare the robot
4. prepare the acquisition client
5. start the program
6. find the output files

Quick start command, after setup is complete:

```powershell
.\.venv\Scripts\python.exe src\program\main.py `
  --config documentation\company_run\config_server.json `
  --routines-file documentation\company_run\routine.json `
  --output-dir documentation\company_run\output
```
