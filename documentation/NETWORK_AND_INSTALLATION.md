# Network And Installation Notes

For the complete step-by-step operator guide, read:

```text
documentation\company_run\README.md
```

This file is the shorter technical reference.

## Internet Access For Installation

The computer needs HTTPS access to:

```text
github.com:443
pypi.org:443
files.pythonhosted.org:443
```

## Robot Access For Operation

Robot IP:

```text
192.168.3.10
```

Required outbound TCP access from the control computer to the robot:

| Destination | Port | Purpose |
|---|---:|---|
| `192.168.3.10` | `29999` | UR Dashboard server |
| `192.168.3.10` | `30002` | URScript command socket |
| `192.168.3.10` | `30004` | RTDE feedback |

Windows checks:

```powershell
Test-Connection 192.168.3.10
Test-NetConnection 192.168.3.10 -Port 29999
Test-NetConnection 192.168.3.10 -Port 30002
Test-NetConnection 192.168.3.10 -Port 30004
```

Each TCP check should show:

```text
TcpTestSucceeded : True
```

## Acquisition Client Access

Default acquisition TCP server:

```text
127.0.0.1:5055
```

With this setting, the acquisition client must run on the same computer.

For a remote acquisition client, edit:

```text
documentation\company_run\config_server.json
```

Change `host` from `127.0.0.1` to the control computer LAN IP, then allow
inbound TCP port `5055` on the control computer firewall.

## Install Python Dependencies

From the repository root:

```powershell
.\init.ps1
```
