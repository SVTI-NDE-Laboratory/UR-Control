# Step-by-step moveJ test

`movej_step_by_step.py` reads waypoints from:

```text
Data/paths_Stefan.script
```

Default waypoint sequence:

```text
Home, Tmp1, Tmp2, p_start_h
```

Send to the robot:

```powershell
python Test\movej_step_by_step.py
```

Python sends one `movej` command to port `30002`, waits until the actual joints
match the target joints using RTDE, prints the actual TCP pose, then asks for
terminal confirmation before sending the next `movej`.

Install `ur_rtde` if needed:

```powershell
python -m pip install ur_rtde
```

Custom waypoint list:

```powershell
python Test\movej_step_by_step.py Home Tmp1 Tmp2
```

Tune motion:

```powershell
python Test\movej_step_by_step.py --a 0.5 --v 0.25
```

Tune completion detection:

```powershell
python Test\movej_step_by_step.py --tolerance 0.005 --timeout 45
```
