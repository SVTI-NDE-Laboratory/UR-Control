"""Record force telemetry, optionally loading and playing a controller-side URP."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time

from force_frames import convert
from urp_runner import program_path, run_cycle


# Edit these controller settings before recording. Set URP_PATH = None for manual recording.
ROBOT_IP = '192.168.3.10'
URP_PATH = '/programs/Users/JOBE/Tests Force/test_force_settling.urp'


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be a finite positive number')
    return number


def capture(receiver, raw_path, variables, duration, stale_timeout=3.0, cycle=None):
    """Keep native recording open until deadline/Ctrl+C; always stop and disconnect."""
    started = False
    try:
        if not receiver.startFileRecording(str(raw_path), variables):
            raise RuntimeError('ur_rtde could not start file recording')
        started = True
        print(f'Recording: {raw_path}', flush=True)
        if cycle is not None:
            return cycle(receiver)
        print('Run the force cycle in PolyScope. Ctrl+C stops recording.', flush=True)
        begin = last_update = time.monotonic()
        last_timestamp = receiver.getTimestamp()
        while duration is None or time.monotonic() - begin < duration:
            time.sleep(0.05)
            if not receiver.isConnected():
                raise RuntimeError('RTDE connection lost')
            timestamp = receiver.getTimestamp()
            if timestamp != last_timestamp:
                last_update = time.monotonic()
                last_timestamp = timestamp
            elif time.monotonic() - last_update > stale_timeout:
                raise RuntimeError('No fresh controller timestamp for 3 seconds')
    except KeyboardInterrupt:
        print('\nStopping recording.')
        return 'user_stop'
    finally:
        try:
            if started and not receiver.stopFileRecording():
                raise RuntimeError('ur_rtde could not finalize recording')
        finally:
            receiver.disconnect()
    return 'duration_completed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rate', type=positive, default=100.0, help='Requested Hz (default: 100)')
    parser.add_argument('--duration', type=positive, help='Seconds; omit to stop with Ctrl+C')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'recordings')
    parser.add_argument('--status-register', type=int, choices=range(24, 48), metavar='24..47',
                        help='Optional output integer register; use 42 for existing register-based script')
    parser.add_argument('--target-force', type=positive, help='Optional manually supplied target in N')
    parser.add_argument('--pre-roll', type=positive, default=1.0, help='Recording seconds before play (default: 1)')
    parser.add_argument('--post-roll', type=positive, default=1.0, help='Recording seconds after program stops (default: 1)')
    parser.add_argument('--cycle-timeout', type=positive, default=60.0, help='Maximum URP runtime in seconds (default: 60)')
    args = parser.parse_args()
    urp = program_path(URP_PATH) if URP_PATH is not None else None
    if args.rate > 500:
        parser.error('--rate must be at most 500 Hz')
    if urp and args.duration is not None:
        parser.error('--duration requires URP_PATH = None; use --cycle-timeout for automatic recording')
    try:
        from rtde_receive import RTDEReceiveInterface
    except ImportError:
        parser.exit(1, 'Missing ur_rtde. Use the project .venv or install visualize_force/requirements.txt.\n')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session = args.output_dir / datetime.now().strftime('force_%Y%m%d_%H%M%S_%f')
    # A fresh session directory prevents native recording from overwriting a file.
    session.mkdir()
    raw_path, force_path = session / 'raw.csv', session / 'force.csv'
    variables = ['timestamp', 'actual_TCP_force', 'actual_TCP_pose']
    if args.status_register is not None:
        variables.append(f'output_int_register_{args.status_register}')
    if urp:
        variables.append('safety_status_bits')
    metadata = {'started_utc': datetime.now(timezone.utc).isoformat(),
                'robot_ip': ROBOT_IP, 'requested_rate_hz': args.rate,
                'requested_duration_s': args.duration, 'status_register': args.status_register,
                'target_force_N': args.target_force, 'variables': variables,
                'urp': urp, 'pre_roll_s': args.pre_roll, 'post_roll_s': args.post_roll,
                'cycle_timeout_s': args.cycle_timeout,
                'force_frame': 'base in raw.csv; current TCP axes in force.csv',
                'outcome': 'recording'}
    metadata_path = session / 'metadata.json'
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    failed = False
    try:
        receiver = RTDEReceiveInterface(ROBOT_IP, args.rate, variables,
                                        use_upper_range_registers=True)
        cycle = None
        if urp:
            cycle = lambda receiver: run_cycle(receiver, ROBOT_IP, urp,
                                               args.pre_roll, args.post_roll, args.cycle_timeout)
        metadata['outcome'] = capture(receiver, raw_path, variables, args.duration, cycle=cycle)
    except Exception as error:
        metadata.update(outcome='error', error=str(error))
        print(f'Recording error: {error}', file=sys.stderr)
        failed = True
    finally:
        if raw_path.exists():
            try:
                metadata['summary'] = convert(raw_path, force_path)
                print(f'Tool-frame CSV: {force_path}')
            except Exception as error:
                metadata['conversion_error'] = str(error)
                print(f'Conversion failed: {error}. Raw CSV retained at {raw_path}', file=sys.stderr)
                failed = True
        metadata['ended_utc'] = datetime.now(timezone.utc).isoformat()
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
