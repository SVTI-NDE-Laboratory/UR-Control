def measurement_scan():

  # -------- USER SETTINGS --------
  n_points = 10
  target_force = 30.0          # N
  max_probe_distance = 0.050   # m, max allowed Z approach
  probe_step = 0.001           # m
  probe_speed = 0.005          # m/s
  retract_distance = 0.030     # m

  trigger_do = 0               # digital output number
  ready_di = 0                 # digital input number

  # Taught poses
  home = p[0.000, 0.000, 0.500, 0, 3.14, 0]
  point_A = p[0.400, 0.000, 0.300, 0, 3.14, 0]
  point_B = p[0.800, 0.000, 0.300, 0, 3.14, 0]
  obstacle_clearance = p[0.600, -0.300, 0.500, 0, 3.14, 0]

  # -------- MOTION SETTINGS --------
  a_fast = 0.5
  v_fast = 0.15
  a_slow = 0.1
  v_slow = 0.03

  # -------- HELPERS --------
  def interp_pose(p1, p2, alpha):
    return p[
      p1[0] + alpha * (p2[0] - p1[0]),
      p1[1] + alpha * (p2[1] - p1[1]),
      p1[2] + alpha * (p2[2] - p1[2]),
      p1[3] + alpha * (p2[3] - p1[3]),
      p1[4] + alpha * (p2[4] - p1[4]),
      p1[5] + alpha * (p2[5] - p1[5])
    ]
  end

  def wait_for_measurement_done():
    while get_digital_in(ready_di) == False:
      sleep(0.02)
    end
  end

  def probe_until_force(start_pose):
    distance = 0.0
    current_pose = start_pose

    while distance < max_probe_distance:
      f = norm(get_tcp_force())

      if f >= target_force:
        return True
      end

      current_pose = pose_trans(current_pose, p[0, 0, -probe_step, 0, 0, 0])
      movel(current_pose, a=a_slow, v=probe_speed)

      distance = distance + probe_step
    end

    return False
  end

  def measure_at_pose(measure_pose):
    # Move above measurement point
    movel(measure_pose, a=a_fast, v=v_fast)

    # Probe toward specimen
    contact_found = probe_until_force(measure_pose)

    if contact_found == False:
      popup("Force was not reached. Returning to safe position.", title="Measurement failed", blocking=True)
      movel(measure_pose, a=a_fast, v=v_fast)
      return False
    end

    # Trigger measurement
    set_digital_out(trigger_do, True)
    sleep(0.1)
    set_digital_out(trigger_do, False)

    # Wait for measurement device to finish
    wait_for_measurement_done()

    # Retract back to measurement pose
    movel(measure_pose, a=a_fast, v=v_fast)

    return True
  end

  # -------- MAIN PROGRAM --------
  movej(home, a=a_fast, v=v_fast)

  i = 0
  while i < n_points:

    if n_points == 1:
      alpha = 0
    else:
      alpha = i / (n_points - 1)
    end

    target_pose = interp_pose(point_A, point_B, alpha)

    # Always go around obstacle before next measurement position
    movel(obstacle_clearance, a=a_fast, v=v_fast)
    movel(target_pose, a=a_fast, v=v_fast)

    success = measure_at_pose(target_pose)

    if success == False:
      popup("Program stopped. Measurement failed before reaching force.", title="Stopped", blocking=True)
      movej(home, a=a_fast, v=v_fast)
      halt
    end

    i = i + 1
  end

  movej(home, a=a_fast, v=v_fast)
  popup("All measurements completed.", title="Done", blocking=True)

end