# Local TCP force monitor

Run from the repository root using the existing Python environment:

```powershell
.\.venv\Scripts\python.exe tools\sandbox\force_webapp.py --robot-ip 192.168.3.10
```

Open <http://127.0.0.1:8085>. Use `--port 8086` if the port is occupied.
The only external Python dependency is `ur_rtde`, already listed in the root
requirements. If your environment lacks it, install `ur_rtde==1.6.5` there.

The PC must be able to reach the controller's RTDE service (TCP port 30004).
Enable that service in the controller's security settings if required. Configure
the actual tool/TCP, payload and centre of gravity correctly on the controller.
The app does not power on the robot, release brakes, change operating mode,
load/start programs, issue movement commands, enable force mode, or tare the sensor.
Prepare the robot in PolyScope yourself according to the validated application.
Force validity depends on the controller state and configuration; a live timestamp
alone does not establish that a force reading is physically valid.

## Controller script

`read_force.script` is optional: RTDE outputs are available without a measurement
program. If you want a continuously running monitor in PolyScope, insert its
contents as a Script file node in a robot program and start it manually. It updates
the global `measured_wrench_base` variable. The web app uses native RTDE outputs,
not that variable. The script never commands motion, but running it does not
establish a safe interaction. Stop it manually in PolyScope.

## Values and recordings

- The display and graph show only **absolute tool Z force** in newtons, rotated
  from base axes into the current configured TCP orientation.
- The interface is in German. The ranking stays on the right on desktop screens.
  On narrow screens it appears below the graph. The graph shows the entire named
  attempt from the first sample, with elapsed seconds, and remains after Stop.
  The server retains the complete current/last attempt history across page reloads;
  starting the next attempt clears that graph. Free play shows a 20-second window.
- Enter a participant name and press **Start** to display and record an attempt.
  The same button becomes **Stop**. Stop saves the name and maximum to the ranking,
  sorted highest first; ties retain completion order. Each attempt has its own row,
  including repeated names. Names are fixed during an attempt.
- Tick **Free play** for continuous live display without recording samples or
  adding ranking entries. Untick it to return to named attempts. Stop an active
  attempt before switching modes. While idle, live force is hidden and not recorded.
  The RTDE connection remains open to check freshness before starting.
- Peak is the maximum **absolute tool Z force** among the samples collected by
  Python, without smoothing, software zero, or a threshold. It counts both push
  directions. Noise, gravity-compensation error and impacts can affect the peak.
- Acquisition defaults to 100 Hz (`--rate 1` through `--rate 500`). Browser updates
  are about 10 Hz. RTDE getters return cached values separately; force and pose are
  not an atomic snapshot. Use this monitor for a stationary tool. Brief peaks may
  be missed; this is not calibrated peak-hold instrumentation.
- Each launch creates `tools/sandbox/recordings/<timestamp>/samples.csv` and
  `peak.json`; stopping an attempt also saves `results.json`. CSV rows contain the
  name, attempt number, controller time, absolute tool Z force and running peak.
  Only named attempts write samples. CSV is flushed per sample; the peak summary
  is updated at most twice per second during recording and immediately on Start
  and Stop. A temporarily locked peak file shows a warning and is retried without
  stopping CSV acquisition. Windows file scanners or an open file can prevent
  replacement; the app cannot identify the process holding the file.
  Saving results on Stop retries a permission error briefly. If it still fails,
  the attempt remains active so you can try Stop again after releasing the file.
  File flushing does not guarantee survival of power loss.
- The ranking survives browser refreshes while the server runs. Restarting the app
  creates a new session with an empty ranking; previous results remain on disk.
  An unfinished attempt is not added to the ranking if the app closes, but its
  samples and peak summary remain on disk. Stop the attempt before closing.
- After one second without a new controller timestamp, live numbers become
  unavailable. A disconnect or recording error stops acquisition; restart the app
  to reconnect. Stop is still available to save a partial attempt after telemetry
  fails. The recorded peak remains visible. Ctrl+C closes the Python app without
  changing robot state. Start and Stop control recording only, not robot motion.

This is read-only measurement software, not a safety function or approval for
children to contact the robot. A Python threshold cannot provide a safety stop.

References: [UR RTDE guide](https://docs.universal-robots.com/tutorials/communication-protocol-tutorials/rtde-guide.html),
[UR force coordinate frames](https://www.universal-robots.com/articles/ur/programming/get-force-and-torque-values-in-tool-coordinate-system/),
[ur_rtde receive interface](https://sdurobotics.gitlab.io/ur_rtde/pages/getting_started/quick_start.html).
