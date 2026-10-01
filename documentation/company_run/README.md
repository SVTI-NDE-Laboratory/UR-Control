# Start Here: Run The UR15 Cobot Program

This guide is written for a new Windows computer/operator. Follow the steps in
order. Do not start the robot program until every check passes.

## What This Folder Is

This folder is the run package:

```text
documentation\company_run\
  README.md
  config_server.json
  routine.json
  output\
```

The files mean:

- `config_server.json`: measurement settings and force-program settings
- `routine.json`: taught robot waypoints and movement routines
- `output\`: where logs and result files are written after a run

## What The Computer Needs

The computer must have:

- Windows PowerShell
- Python 3.12 or newer
- Git, if the repository must be cloned from GitHub
- network access to the UR cobot
- network access to the acquisition client, if it runs on another computer

During installation, the computer needs internet access to:

```text
github.com
pypi.org
files.pythonhosted.org
```

During robot operation, the computer must reach the robot at:

```text
192.168.3.10
```

The robot ports that must be reachable are:

| Port | Used For |
|---:|---|
| `29999` | robot status, load/play/stop URP program |
| `30002` | sending robot movement scripts |
| `30004` | RTDE live robot feedback |

## 1. Install Python And Git

Install Python 3.12 or newer from:

```text
https://www.python.org/downloads/
```

During Python installation, enable:

```text
Add python.exe to PATH
```

Install Git for Windows from:

```text
https://git-scm.com/download/win
```

Open PowerShell and check both tools:

```powershell
python --version
git --version
```

Both commands should print a version number.

## 2. Download The Repository

Choose a folder where the project should live, for example:

```powershell
cd $env:USERPROFILE\Documents
```

Clone the repository:

```powershell
git clone https://github.com/SVTI-NDE-Laboratory/UR-Control.git
```

Enter the repository:

```powershell
cd UR-Control
```

If the repository was provided as a ZIP file instead, extract it and open
PowerShell inside the extracted folder.

## 3. Open PowerShell In The Repository

Open PowerShell in the repository root folder, the folder that contains:

```text
requirements.txt
init.ps1
src\
documentation\
```

If you are not sure where you are, run:

```powershell
dir
```

You should see `requirements.txt` and `init.ps1`.

## 4. Install The Python Environment

Run this once:

```powershell
.\init.ps1
```

This creates a local `.venv` folder and installs the required Python libraries.

If PowerShell blocks the script, run this command once in the same PowerShell
window, then run `.\init.ps1` again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

At the end, the script should print:

```text
Import check OK
Setup complete.
```

## 5. Check The Robot Network

Run these checks:

```powershell
Test-Connection 192.168.3.10
Test-NetConnection 192.168.3.10 -Port 29999
Test-NetConnection 192.168.3.10 -Port 30002
Test-NetConnection 192.168.3.10 -Port 30004
```

For each `Test-NetConnection`, look for:

```text
TcpTestSucceeded : True
```

If one of them is `False`, stop here. The computer cannot control the robot
yet. Check the Ethernet cable, IP address, subnet, firewall, and robot network
settings.

## 6. Prepare The Robot

On the teach pendant:

1. Power on the robot.
2. Release the brakes.
3. Put the robot in Remote Control mode.
4. Move the robot to the taught `Home` position from `routine.json`.
5. Make sure the force program exists on the robot:

```text
Inspection/Programs/apply_force_with_server.urp
```

The Python program checks that the robot is at `Home` before it allows motion.
If the robot is not at `Home`, the run stops before movement starts.

## 7. Prepare The Acquisition Client

The Python program starts a TCP server for the acquisition client.

Current setting in `config_server.json`:

```text
127.0.0.1:5055
```

This means the acquisition client must run on the same computer as the Python
program.

If the acquisition client runs on another computer:

1. Find the control computer IP address on the robot/acquisition network.
2. Edit `config_server.json`.
3. Change `host` from `127.0.0.1` to that control computer IP address.
4. Allow inbound TCP port `5055` in the Windows firewall.
5. Configure the acquisition client to connect to that IP and port `5055`.

The acquisition client must send:

```text
ALIVE
ISREADY
GO
```

Optional state request:

```text
STATE
```

Response format:

| Command | Response |
|---|---|
| `ALIVE` | `OK` |
| `ISREADY` | `true` or `false` |
| `GO` | `ACK` |
| `STATE` | 4-byte length prefix, then JSON |

Example `STATE` JSON:

```json
{"X":1,"Y":11,"Point":1,"Moving":true,"Error":"ok"}
```

## 8. Start The Robot Program

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe src\program\main.py `
  --config documentation\company_run\config_server.json `
  --routines-file documentation\company_run\routine.json `
  --output-dir documentation\company_run\output
```

The program starts the acquisition TCP server first and waits for `ALIVE`.

When the terminal asks for confirmation, do not press Enter until:

- the robot is ready
- the acquisition client has connected
- the area around the robot is clear
- everyone nearby knows the robot is about to move

Then press Enter.

## 9. During The Run

The expected sequence is:

1. Python verifies the robot is at `Home`.
2. Python moves the robot to the measurement start position.
3. At each measurement point, the robot applies force.
4. When force is reached, `ISREADY` returns `true`.
5. The acquisition client records data.
6. The acquisition client sends `GO`.
7. The robot continues to the next point.
8. At the end, the robot returns to `Home`.

To stop manually, press:

```text
Ctrl+C
```

If the robot has a safety issue, use the robot safety stop.

## 10. After The Run

The output files are written here:

```text
documentation\company_run\output\
```

Important files:

| File | Meaning |
|---|---|
| `program.log` | full terminal log |
| `config_used.json` | exact config used for the run |
| `state.json` | latest program state |
| `measurement_plan.json` | measurement points and results |

## Common Problems

### `TcpTestSucceeded : False`

The computer cannot reach the robot port. Check cabling, IP settings, subnet,
firewall, and whether the robot is on.

### `Robot is not in Remote Control mode`

Switch the teach pendant to Remote Control mode.

### `Unsafe start prevented`

The robot is not at the taught `Home` position. Move it to `Home` and start
again.

### Program waits before asking for Enter

The Python server is waiting for the acquisition client to send `ALIVE`. Start
or fix the acquisition client connection.

### `ISREADY` stays `false`

This is normal until the robot is holding force at a measurement point. It only
returns `true` during that force-hold window.

### Python cannot import `rtde_io` or `rtde_receive`

Run:

```powershell
.\init.ps1
```

Then start the program with:

```powershell
.\.venv\Scripts\python.exe src\program\main.py `
  --config documentation\company_run\config_server.json `
  --routines-file documentation\company_run\routine.json `
  --output-dir documentation\company_run\output
```
