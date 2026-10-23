"""Run a controller-side URP while the caller keeps native recording open."""

import socket
import sys
import time


def dashboard_command(robot_ip, command):
    with socket.create_connection((robot_ip, 29999), timeout=5) as connection:
        with connection.makefile('rb') as stream:
            if not stream.readline(8192):
                raise RuntimeError('Dashboard disconnected before greeting')
            connection.sendall((command + '\n').encode('utf-8'))
            reply = stream.readline(8192)
            if not reply:
                raise RuntimeError('Dashboard disconnected before response')
            return reply.decode('utf-8', errors='replace').strip()


def program_path(value):
    value = value.strip()
    if not value.lower().endswith('.urp') or any(c in value for c in '\r\n\x00"'):
        raise ValueError('Supply a controller-side .urp path without quotes or control characters')
    return value


def run_cycle(receiver, robot_ip, urp, pre_roll=1.0, post_roll=1.0,
              cycle_timeout=60.0, command=None, controller=None):
    """Observe start then stop; stop our requested program on timeout/error/Ctrl+C."""
    command = command or (lambda value: dashboard_command(robot_ip, value))
    urp = program_path(urp)
    last_timestamp = receiver.getTimestamp()
    last_update = time.monotonic()
    play_requested = False

    def health():
        nonlocal last_timestamp, last_update
        if not receiver.isConnected():
            raise RuntimeError('RTDE connection lost')
        timestamp = receiver.getTimestamp()
        if timestamp != last_timestamp:
            last_update = time.monotonic()
            last_timestamp = timestamp
        elif time.monotonic() - last_update > 3:
            raise RuntimeError('No fresh controller timestamp for 3 seconds')
        # Normal and reduced operation are allowed; stop conditions are not.
        bits = receiver.getSafetyStatusBits()
        if bits & sum(1 << bit for bit in (2, 4, 5, 6, 7, 8, 9, 10)):
            raise RuntimeError(f'Robot safety stop (status bits: {bits})')

    def wait(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            health()
            time.sleep(min(.05, max(0, end - time.monotonic())))

    def state():
        reply = command('programState')
        value = reply.split()[0].upper() if reply else ''
        if value not in ('PLAYING', 'STOPPED', 'PAUSED'):
            raise RuntimeError(f'Unexpected program state: {reply}')
        return value

    def ready():
        health()
        if command('is in remote control').lower() != 'true':
            raise RuntimeError('Switch the robot to Remote Control before automatic recording')
        if command('robotmode').rsplit(':', 1)[-1].strip().upper() != 'RUNNING':
            raise RuntimeError('Robot must be powered on with brakes released')
        if state() != 'STOPPED':
            raise RuntimeError('Another program is running or paused; no program was replaced')

    try:
        ready()
        reply = command(f'load {urp}')
        first_reply = reply
        if 'could not understand' in reply.lower() and any(c.isspace() for c in urp):
            reply = command(f'load "{urp}"')
        if not reply.lower().startswith('loading program:'):
            detail = reply
            if reply != first_reply:
                detail = f'Unquoted path: {first_reply}. Quoted path: {reply}'
            if 'could not understand' in detail.lower():
                detail += ('. Verify URP_PATH in record.py. If the controller rejects spaces, '
                           'rename the folder on the robot without spaces and update URP_PATH.')
            raise RuntimeError(f'URP load failed: {detail}')
        # Loading also loads the installation: recheck before asking for motion.
        ready()
        print(f'URP loaded: {urp}. Recording {pre_roll:g} s before play.', flush=True)
        wait(pre_roll)
        ready()
        if controller is not None:
            controller.prepare()
        play_requested = True  # Also stop if play reached the robot but its reply was lost.
        reply = command('play')
        if reply.lower() != 'starting program':
            raise RuntimeError(f'URP play failed: {reply}')
        begin = time.monotonic()
        observed_running = False
        while True:
            health()
            current = state()
            elapsed = time.monotonic() - begin
            if current == 'PAUSED':
                raise RuntimeError('URP paused before completion')
            if controller is not None:
                controller.poll(receiver)
            if current == 'PLAYING':
                observed_running = True
            elif observed_running:
                if controller is not None:
                    controller.finish(receiver)
                break
            if not observed_running and elapsed >= 5:
                raise RuntimeError('URP start was not observed within 5 seconds')
            if elapsed >= cycle_timeout:
                raise RuntimeError('URP exceeded --cycle-timeout')
            time.sleep(.05)
        print(f'URP stopped. Recording {post_roll:g} s after stop.', flush=True)
        wait(post_roll)
        health()
        play_requested = False
        return 'program_stopped'
    finally:
        if play_requested:
            try:
                reply = command('stop')
                if reply.lower() != 'stopped':
                    raise RuntimeError(reply)
            except Exception as error:
                print(f'Could not confirm robot stop: {error}', file=sys.stderr)
                raise RuntimeError(f'Could not confirm robot stop: {error}') from error

