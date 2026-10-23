Register-controlled force cycle

UR source: scripts/apply_force_from_ur_settling.script
Recorder: record_registers.py

Save the UR source in a PolyScope Script node inside the controller-side URP.
Set ROBOT_IP and URP_PATH in record_registers.py to select the robot and URP.
The ordinary record.py captures telemetry without writing force registers.

Run from the project root:
  .venv/Scripts/python.exe visualize_force/record_registers.py

Recorder settings:
  TARGET_FORCE_N = 200.0
  MAX_DISTANCE_MM = 50.0
  SETTLING_TIME_S = 1.5
  MEASUREMENT_DURATION_S = 3.0
Settling time may be zero; force, distance and measurement duration are positive.
The recorder converts maximum displacement from millimetres to metres.

Input registers:
  Float 43: maximum displacement along starting TCP Z+ [m].
  Float 44: settling delay after first reaching the target [s].
  Float 45: target force [N], used for both command and detection.
  Integer 42: 0 before starting; 1 when measurement is complete.

Output integer 42:
  0: initialized or return completed.
  1: target reached and settling completed; ready for measurement.
  2: distance limit reached or target-acquisition timeout; cycle failed.

Cycle:
  1. Capture return pose, zero sensor, and enter force_mode once.
  2. Approach until abs(current-tool Fz) first reaches float 45, then latch
     force_reached = True and start the settling delay.
  3. Maintain force for the delay in float 44. Force dips do not restart it.
     Readiness indicates completion of this delay, not verified force stability.
  4. Set force_ready and output 42 = 1. Python starts the measurement timer.
     Force mode remains active until Python writes input 42 = 1.
  5. End force mode, stop residual motion, and return to the captured pose.
     Output 42 becomes 0 after the return move.

The force command and distance use the starting TCP frame. Measured force is
rotated into the current TCP axes. No smoothing is applied to the measurement.
Distance checks remain active during approach, settling, and measurement.

Motion settings in the UR script:
  max_approach_speed = 0.02 m/s
  approach_timeout = 10.0 s, until first target crossing
  return_speed = 0.04 m/s
  return_acceleration = 0.100 m/s^2

State messages are defined in force_state_message(index) at the top of the
UR script. The cycle selects messages by index instead of repeating strings.

The recorder checks readiness, release and completion, records output register
42, and stores the parameters and event times in metadata.json. Safety stops,
protocol errors and cycle timeouts request a Dashboard stop when play has been
requested. CSV capture is finalized on success, interruption or error.

Offline checks (no robot connection):
  .venv/Scripts/python.exe -m unittest discover -s visualize_force -p test_register_settling_script.py
  .venv/Scripts/python.exe -m unittest discover -s visualize_force -p test_record_registers.py
Tests cover control flow with mocked calls, not robot dynamics or UR parsing.
