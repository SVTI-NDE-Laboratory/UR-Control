"""Record one register-controlled force cycle; configure the constants below."""

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time

from force_frames import convert
from record import capture
from urp_runner import program_path, run_cycle


# Save scripts/apply_force_from_ur_settling.script in this controller-side URP.
ROBOT_IP = '192.168.3.10'
URP_PATH = '/programs/Users/JOBE/Tests Force/test_force_settling.urp'
TARGET_FORCE_N = 240.0  # Default requested force; the URP must read float register 45.
MAX_DISTANCE_MM = 50.0
SETTLING_TIME_S = 2.5  # Input float register 44; delay after first reaching target force.
MEASUREMENT_DURATION_S = 3.0  # Starts when the URP reports ready AFTER settling.
RATE_HZ = 100.0
PRE_ROLL_S = 1.0
POST_ROLL_S = 1.0
CYCLE_TIMEOUT_S = 60.0  # Includes approach, settling, measurement and return.
OUTPUT_DIR = Path(__file__).resolve().parent / 'recordings'


class ForceRegisters:
    """Write parameters once, observe initialization, then time and release the hold."""

    def __init__(self, robot_ip, target_force, max_distance_mm, measurement_duration,
                 io_factory=None, settling_time=1.5):
        self.robot_ip = robot_ip
        self.target_force = target_force
        self.max_distance_mm = max_distance_mm
        self.measurement_duration = measurement_duration
        if not math.isfinite(settling_time) or settling_time < 0:
            raise ValueError('Settling time must be nonnegative and finite')
        self.settling_time = settling_time
        self.io_factory = io_factory
        self.io = None
        self.initialized = False
        self.ready_at = None
        self.released_at = None
        self.ready_utc = None
        self.released_utc = None
        self.completed = False

    def prepare(self):
        """Called only after Dashboard preflight/load and immediately before play."""
        factory = self.io_factory
        if factory is None:
            from rtde_io import RTDEIOInterface
            factory = RTDEIOInterface
        self.io = factory(self.robot_ip, use_upper_range_registers=True)
        for register, value in ((43, self.max_distance_mm / 1000),
                                (44, self.settling_time), (45, self.target_force)):
            if not self.io.setInputDoubleRegister(register, value):
                raise RuntimeError(f'Could not write input double register {register}')
        if not self.io.setInputIntRegister(42, 0):
            raise RuntimeError('Could not clear release register 42')
        print(f'Parameters set: {self.target_force:g} N, {self.max_distance_mm:g} mm, '
              f'{self.settling_time:g} s settling. '
              'Waiting for target force and settling.', flush=True)

    def poll(self, receiver):
        """Reject failure/early release; send acknowledgement only after ready + duration."""
        status = receiver.getOutputIntRegister(42)
        if status in (2, 3, 4):
            raise RuntimeError(f'Force cycle failed: output register 42 = {status}')
        if status not in (0, 1):
            raise RuntimeError(f'Unexpected force status: {status}')
        if not self.initialized:
            self.initialized = status == 0
            return  # Do not mistake readiness left over from a previous run for this run.
        now = time.monotonic()
        if self.released_at is not None:
            self.completed = status == 0
            return
        if self.ready_at is None:
            if status == 1:
                self.ready_at = now
                self.ready_utc = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
                stamp = datetime.now().astimezone().isoformat(timespec='milliseconds')
                print(f'[{stamp}] Force ready. Measuring for {self.measurement_duration:g} s.', flush=True)
        else:
            if status != 1:
                raise RuntimeError('Force hold ended before measurement completed')
            if now - self.ready_at >= self.measurement_duration:
                if not self.io.setInputIntRegister(42, 1):
                    raise RuntimeError('Could not release force hold via input register 42')
                self.released_at = now
                self.released_utc = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
                stamp = datetime.now().astimezone().isoformat(timespec='milliseconds')
                print(f'[{stamp}] Measurement complete; released force hold. Waiting for return.', flush=True)

    def finish(self, receiver):
        """A stopped program is successful only after ready, release, and returned status."""
        if self.released_at is None or not self.completed:
            raise RuntimeError(
                'URP stopped without completing the ready/release/return handshake. '
                'Verify that the controller-side URP contains the current '
                'visualize_force/scripts/apply_force_from_ur_settling.script; '
                'a standalone URP can ignore the requested force registers.')

    def close(self):
        """Disconnect IO after success or after the runner has handled an error/stop."""
        if self.io is not None:
            self.io.disconnect()


def main():
    """Record, control and export one cycle without changing the ordinary recorder."""
    # Run-button consoles may pipe output instead of providing an interactive terminal.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(line_buffering=True, write_through=True)
    urp = program_path(URP_PATH)
    for name, value in {'TARGET_FORCE_N': TARGET_FORCE_N, 'MAX_DISTANCE_MM': MAX_DISTANCE_MM,
                        'MEASUREMENT_DURATION_S': MEASUREMENT_DURATION_S, 'RATE_HZ': RATE_HZ,
                        'PRE_ROLL_S': PRE_ROLL_S, 'POST_ROLL_S': POST_ROLL_S,
                        'CYCLE_TIMEOUT_S': CYCLE_TIMEOUT_S}.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be positive and finite')
    if RATE_HZ > 500:
        raise ValueError('RATE_HZ must be at most 500')
    if not math.isfinite(SETTLING_TIME_S) or SETTLING_TIME_S < 0:
        raise ValueError('SETTLING_TIME_S must be nonnegative and finite')
    if CYCLE_TIMEOUT_S <= MEASUREMENT_DURATION_S + SETTLING_TIME_S + 10:
        raise ValueError('Allow time for measurement + settling + 10 s approach, plus return')
    print(f'Recorder: {Path(__file__).resolve()}\nURP: {urp}\n'
          f'Requested force: {TARGET_FORCE_N:g} N (input double register 45).\n'
          'Requires the register-controlled apply_force_from_ur_settling.script in the URP.',
          flush=True)
    from rtde_receive import RTDEReceiveInterface

    controller = ForceRegisters(ROBOT_IP, TARGET_FORCE_N, MAX_DISTANCE_MM, MEASUREMENT_DURATION_S,
                                settling_time=SETTLING_TIME_S)
    session = OUTPUT_DIR / datetime.now().strftime('force_%Y%m%d_%H%M%S_%f')
    session.mkdir(parents=True)
    raw_path, force_path = session / 'raw.csv', session / 'force.csv'
    variables = ['timestamp', 'actual_TCP_force', 'actual_TCP_pose',
                 'output_int_register_42', 'safety_status_bits']
    metadata = {'started_utc': datetime.now(timezone.utc).isoformat(), 'robot_ip': ROBOT_IP,
                'urp': urp, 'target_force_N': TARGET_FORCE_N, 'max_distance_mm': MAX_DISTANCE_MM,
                'settling_time_s': SETTLING_TIME_S,
                'measurement_duration_s': MEASUREMENT_DURATION_S, 'requested_rate_hz': RATE_HZ,
                'pre_roll_s': PRE_ROLL_S, 'post_roll_s': POST_ROLL_S,
                'cycle_timeout_s': CYCLE_TIMEOUT_S, 'variables': variables,
                'force_frame': 'base in raw.csv; current TCP axes in force.csv',
                'outcome': 'recording'}
    metadata_path = session / 'metadata.json'
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    failed = False
    try:
        receiver = RTDEReceiveInterface(ROBOT_IP, RATE_HZ, variables, use_upper_range_registers=True)
        def cycle(receiver):
            return run_cycle(receiver, ROBOT_IP, urp, PRE_ROLL_S, POST_ROLL_S,
                             CYCLE_TIMEOUT_S, controller=controller)
        metadata['outcome'] = capture(receiver, raw_path, variables, None, cycle=cycle)
    except Exception as error:
        metadata.update(outcome='error', error=str(error))
        print(f'Recording error: {error}', file=sys.stderr)
        failed = True
    finally:
        metadata['force_ready_utc'] = controller.ready_utc
        metadata['measurement_released_utc'] = controller.released_utc
        try:
            controller.close()
        except Exception as error:
            metadata['io_disconnect_error'] = str(error)
            failed = True
        if raw_path.exists():
            try:
                metadata['summary'] = convert(raw_path, force_path)
                print(f'Tool-frame CSV: {force_path}', flush=True)
            except Exception as error:
                metadata['conversion_error'] = str(error)
                print(f'Conversion failed: {error}. Raw CSV retained at {raw_path}', file=sys.stderr)
                failed = True
        metadata['ended_utc'] = datetime.now(timezone.utc).isoformat()
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
