Standard deviation only force cycle

New robot file: scripts/apply_force_std_settling.script
Load it into a NEW PolyScope Script node/program. It defines its helper and
cycle function, then calls the cycle once at the bottom. It does not modify
the original visualization or measurement scripts.

Defaults inside apply_force_std_settling():
  force_holding = 280.0 N
  max_approach_speed = 0.04 m/s (40 mm/s)
  std_window = 0.5 s
  std_percent = 2.0
  hold_duration = 3.0 s
  distance_max = 0.050 m
  approach_settle_timeout = 10.0 s
  use_python_release = False

Choose std_percent = 2.0 or 5.0:
  2%: population standard deviation <= 5.6 N for a 280 N request
  5%: population standard deviation <= 14.0 N for a 280 N request

Behavior:
  1. Zero the sensor and approach using continuous force mode.
  2. On the FIRST abs(current-tool Z force) >= force_holding, begin collecting
     a fresh window. No earlier samples are used. Subsequent dips below the
     request do not clear the window or re-arm detection.
  3. After a complete window, readiness depends ONLY on the population
     standard deviation. There is no mean-force band or slope requirement.
  4. When std <= selected limit, latch force_ready and contact_detected True.
     Start the hold once. Continue updating live force/std values, but never
     restart the timer or revoke readiness because they change later.
  5. Release after the local hold duration, end force mode, and return to the
     captured starting pose.

The percentage describes standard deviation relative to the requested force;
it is NOT a +/-2% or +/-5% band around the target. A steady lower force can
therefore qualify after the request has been touched once, as specified.

The window uses a fixed 251-element circular buffer and controller-step samples.
At 500 Hz, 251 points span 0.5 s; slower controllers use fewer points and round
the requested span upward to the next controller step. actual_window_span
shows the resulting span. A window needing more than 251 points is rejected
before motion. The running-sum computation has constant work per cycle.
The 100 Hz recorded curves and controller-step measurements can yield different
detection times because the controller samples the force more frequently.

Travel remains bounded during settling and the hold. Failure to reach AND
settle within approach_settle_timeout ends force mode and returns without a
successful hold. Live state_message and failure_message describe the result.

Optional existing Python timer/client-feedback integration:
  Set use_python_release = True.
  The script clears output integer register 42 to 0 and waits up to 5 s for
  input integer register 42 to be 0 before motion.
  It writes output 42 = 1 ONLY after std-based readiness. The existing Python
  controller can then run its configured timer or await client feedback.
  Writing input 42 = 1 releases the hold. The script uses a 60 s release
  timeout by default; adjust python_release_timeout to the intended workflow.
  Output 42 = 2 indicates failure; output 42 = 0 is written after return.
  Force, distance, std and speed settings come from this script's constants;
  it does not read Python's input float parameters.
  The standalone record.py recorder does not supply this acknowledgement;
  leave use_python_release False when using it on its own.

Set the intended TCP and payload, starting pose and constants before loading
the new program. The script starts from the current pose. There is no
simulation mode in this new file.

Example after saving a NEW controller-side URP containing this script:
  Set ROBOT_IP and URP_PATH in record.py, then run:
  .venv/Scripts/python.exe visualize_force/record.py

Mocked checks:
  .venv/Scripts/python.exe -m unittest discover -s visualize_force -p "test_*.py" -v

Checks exercise control flow, timing, statistics, latching and register release.
Real controller parsing and execution still need validation on the robot.
