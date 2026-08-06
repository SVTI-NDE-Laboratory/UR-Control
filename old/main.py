import socket
import time

ROBOT_IP = "192.168.1.10"

DASHBOARD_PORT = 29999
SCRIPT_PORT = 30002

TRIGGER_DO = 0
DONE_DI = 0

TARGET_FORCE = 30.0      # N
MAX_DEPTH = 0.050        # m

N_POINTS = 10

HOME = [0.000, 0.000, 0.500, 0, 3.14, 0]
POINT_A = [0.400, 0.000, 0.300, 0, 3.14, 0]
POINT_B = [0.800, 0.000, 0.300, 0, 3.14, 0]
OBSTACLE_CLEAR = [0.600, -0.300, 0.500, 0, 3.14, 0]


def pose(values):
    return "p[" + ",".join(f"{v:.6f}" for v in values) + "]"


def interpolate_pose(a, b, alpha):
    return [a[i] + alpha * (b[i] - a[i]) for i in range(6)]


def send_dashboard(cmd):
    with socket.create_connection((ROBOT_IP, DASHBOARD_PORT), timeout=5) as s:
        s.recv(4096)
        s.sendall((cmd + "\n").encode())
        return s.recv(4096).decode().strip()


def send_script(script):
    with socket.create_connection((ROBOT_IP, SCRIPT_PORT), timeout=5) as s:
        s.sendall(script.encode())


def move_to(target):
    script = f"""
def move_to_pose():
  movel({pose(target)}, a=0.3, v=0.1)
end
"""
    send_script(script)
    time.sleep(1.0)


def measure_at(target):
    script = f"""
def program():
  {MEASURE_FUNCTION}

  success = measure_at_pose(
    {pose(target)},
    {TARGET_FORCE},
    {MAX_DEPTH},
    {TRIGGER_DO},
    {DONE_DI}
  )

  if success == False:
    popup("Force not reached. Measurement stopped.", title="Measurement failed", blocking=True)
  end
end
"""
    send_script(script)
    time.sleep(1.0)


MEASURE_FUNCTION = """
def measure_at_pose(target_pose, target_force, max_depth, trigger_do, done_di):

  movel(target_pose, a=0.3, v=0.05)

  start_pose = target_pose
  step = 0.001
  moved = 0.0

  while moved < max_depth:

    force = norm(get_tcp_force())

    if force >= target_force:

      set_digital_out(trigger_do, True)
      sleep(0.1)
      set_digital_out(trigger_do, False)

      while get_digital_in(done_di) == False:
        sleep(0.02)
      end

      movel(start_pose, a=0.3, v=0.05)
      return True
    end

    target_pose = pose_trans(target_pose, p[0, 0, -step, 0, 0, 0])
    movel(target_pose, a=0.05, v=0.005)

    moved = moved + step
  end

  movel(start_pose, a=0.3, v=0.05)
  return False

end
"""


def main():
    print(send_dashboard("robotmode"))
    print(send_dashboard("safetymode"))

    move_to(HOME)

    for i in range(N_POINTS):
        alpha = i / (N_POINTS - 1)
        target = interpolate_pose(POINT_A, POINT_B, alpha)

        move_to(OBSTACLE_CLEAR)
        move_to(target)
        measure_at(target)

    move_to(HOME)
    print("All measurements complete.")


if __name__ == "__main__":
    main()