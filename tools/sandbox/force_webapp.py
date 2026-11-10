"""Read-only RTDE force monitor, served locally with the Python standard library."""

import argparse
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time


# Keep operator settings together. No RTDE input registers or control APIs are used.
ROBOT_IP = '192.168.3.10'
RATE_HZ = 100.0
PORT = 8085
STALE_SECONDS = 1.0
PEAK_SAVE_INTERVAL = 0.5
DIRECTORY = Path(__file__).resolve().parent


def state_message(index):
    return ('Verbindung wird hergestellt', 'Empfang aktiv', 'Keine aktuellen Messdaten', 'Verbindung unterbrochen', 'Beendet')[index]


def force_in_tool(force, rotation):
    """Rotate base-frame force into current TCP axes using inverse Rodrigues rotation."""
    angle = math.hypot(*rotation)
    if angle < 1e-12:
        return list(force)
    axis = [value / angle for value in rotation]
    x, y, z = axis
    fx, fy, fz = force
    cross = (y * fz - z * fy, z * fx - x * fz, x * fy - y * fx)
    dot = sum(a * f for a, f in zip(axis, force))
    c, s = math.cos(angle), math.sin(angle)
    return [c * f - s * k + (1 - c) * a * dot for f, k, a in zip(force, cross, axis)]


def replace_json(path, value, attempts=1):
    """Retry a locked Windows destination only when the caller can wait."""
    temporary = path.with_suffix('.tmp')
    for attempt in range(attempts):
        try:
            temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
            temporary.replace(path)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(0.05)


class Monitor:
    def __init__(self, robot_ip, rate, output):
        self.robot_ip, self.rate, self.output = robot_ip, rate, output
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.latest = None
        self.updated = None
        self.status = state_message(0)
        self.error = None
        self.peak = 0.0
        self.peak_timestamp = None
        self.round = 1
        self.mode = 'idle'
        self.name = ''
        self.started_utc = None
        self.sample_count = 0
        self.results = []
        self.history = []
        self.first_timestamp = None
        self.peak_save_pending = False
        self.next_peak_save = 0.0
        self.storage_warning = None

    def snapshot(self):
        with self.lock:
            age = None if self.updated is None else time.monotonic() - self.updated
            fresh = self.status == state_message(1) and age is not None and age < STALE_SECONDS
            status = state_message(2) if self.status == state_message(1) and not fresh else self.status
            return dict(status=status, fresh=fresh, age_s=age, error=self.error,
                        warning=self.storage_warning,
                        robot_ip=self.robot_ip,
                        sample=self.latest if self.mode != 'idle' else None, peak_N=self.peak,
                        peak_timestamp=self.peak_timestamp, round=self.round, mode=self.mode,
                        history=list(self.history), started_utc=self.started_utc,
                        name=self.name, results=sorted(self.results, key=lambda row: -row['peak_abs_tool_z_N']))

    def save_peak(self, force=True):
        """Defer a locked peak summary without interrupting CSV acquisition."""
        self.peak_save_pending = True
        if not force and time.monotonic() < self.next_peak_save:
            return
        summary = dict(round=self.round, name=self.name, mode=self.mode,
                       started_utc=self.started_utc, samples=self.sample_count, peak_abs_tool_z_N=self.peak,
                       controller_timestamp_s=self.peak_timestamp, robot_ip=self.robot_ip,
                       updated_utc=datetime.now(timezone.utc).isoformat())
        try:
            replace_json(self.output / 'peak.json', summary)
        except PermissionError:
            self.storage_warning = ('Spitzenwert-Datei vorübergehend gesperrt. '
                                    'Messung und CSV-Aufzeichnung laufen weiter; Speicherung wird wiederholt.')
        else:
            self.peak_save_pending = False
            self.storage_warning = None
        self.next_peak_save = time.monotonic() + PEAK_SAVE_INTERVAL

    def action(self, action, name='', enabled=False):
        """Serialize UI actions and sampling so each attempt has exact recording boundaries."""
        with self.lock:
            if action == 'start':
                if self.mode != 'idle':
                    raise ValueError('Zuerst den aktuellen Modus beenden.')
                if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
                    raise ValueError('Bitte einen Namen mit 1 bis 80 Zeichen eingeben.')
                if self.status != state_message(1) or self.updated is None or time.monotonic() - self.updated >= STALE_SECONDS:
                    raise ValueError('Vor dem Start auf aktuelle Messdaten warten.')
                self.mode, self.name = 'attempt', name.strip()
                self.started_utc = datetime.now(timezone.utc).isoformat()
                self.peak, self.peak_timestamp, self.sample_count = 0.0, None, 0
                self.history = []
                self.first_timestamp = None
                self.latest = None
                self.save_peak()

            elif action == 'stop':
                if self.mode != 'attempt':
                    raise ValueError('Es ist kein Versuch aktiv.')
                # Persist the completed result before acknowledging Stop to the UI.
                result = dict(round=self.round, name=self.name, peak_abs_tool_z_N=self.peak,
                              started_utc=self.started_utc, stopped_utc=datetime.now(timezone.utc).isoformat(),
                              samples=self.sample_count)
                results = [*self.results, result]
                # Stop may wait briefly for a file scanner; failure keeps this attempt active.
                replace_json(self.output / 'results.json', results, attempts=5)
                self.results = results
                self.mode = 'idle'
                self.round += 1
                self.save_peak()

            elif action == 'free':
                if not isinstance(enabled, bool):
                    raise ValueError('Freies Spielen muss aktiviert oder deaktiviert sein.')
                if self.mode == 'attempt':
                    raise ValueError('Vor dem Moduswechsel den Versuch stoppen.')
                self.mode = 'free' if enabled else 'idle'
            else:
                raise ValueError('Unbekannte Aktion.')

    def record_sample(self, timestamp, tool, writer, stream):
        """Called under the lock; idle and free play never write attempt samples."""
        self.latest = dict(timestamp_s=timestamp, tool_z_abs_N=abs(tool[2]))
        self.updated = time.monotonic()
        self.status = state_message(1)
        if self.mode != 'attempt':
            if self.peak_save_pending:
                self.save_peak(force=False)
            return
        self.sample_count += 1
        # Preserve the full attempt, including samples between browser refreshes.
        if self.first_timestamp is None:
            self.first_timestamp = timestamp
        self.history.append([timestamp - self.first_timestamp, abs(tool[2])])
        new_peak = abs(tool[2]) > self.peak
        if new_peak:
            self.peak, self.peak_timestamp = abs(tool[2]), timestamp
        writer.writerow([datetime.now(timezone.utc).isoformat(), timestamp,
                         self.round, self.name, abs(tool[2]), self.peak])
        stream.flush()
        # Limit summary replacements to 2 Hz while retaining every CSV sample.
        if new_peak or self.sample_count == 1 or self.peak_save_pending:
            self.save_peak(force=False)

    def run(self):
        receiver = None
        try:
            from rtde_receive import RTDEReceiveInterface

            # Subscribe only to outputs. Never load a program or change robot state.
            variables = ['timestamp', 'actual_TCP_force', 'actual_TCP_pose']
            receiver = RTDEReceiveInterface(self.robot_ip, self.rate, variables)
            with (self.output / 'samples.csv').open('x', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(['utc', 'controller_timestamp_s', 'round', 'name',
                                 'abs_tool_z_N', 'peak_abs_tool_z_N'])
                stream.flush()

                # Duplicate controller timestamps do not count as new samples.
                previous = None
                while not self.stop.is_set():
                    if not receiver.isConnected():
                        raise RuntimeError('Verbindung unterbrochen. Bitte die Anwendung neu starten.')
                    timestamp = receiver.getTimestamp()
                    if previous is not None and timestamp < previous:
                        raise RuntimeError('Die Robotersteuerung wurde neu gestartet. Bitte die Anwendung neu starten.')

                    if timestamp != previous:
                        wrench = receiver.getActualTCPForce()
                        pose = receiver.getActualTCPPose()
                        if len(wrench) != 6 or len(pose) != 6 or not all(
                                math.isfinite(v) for v in [timestamp, *wrench, *pose]):
                            raise RuntimeError('Ung?ltige Kraft- oder Positionsmessdaten.')
                        tool = force_in_tool(wrench[:3], pose[3:])
                        with self.lock:
                            self.record_sample(timestamp, tool, writer, stream)
                        previous = timestamp

                    # Acquisition is independent of the slower browser refresh rate.
                    self.stop.wait(1 / self.rate)
        except Exception as error:
            with self.lock:
                self.status, self.error = state_message(3), str(error)
            print(f'Acquisition stopped: {error}', flush=True)
        finally:
            if receiver is not None:
                receiver.disconnect()


def make_handler(monitor):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/':
                self.respond(200, (DIRECTORY / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            elif self.path == '/api/force':
                self.respond(200, json.dumps(monitor.snapshot()).encode(), 'application/json')
            else:
                self.respond(404, b'Nicht gefunden', 'text/plain')

        def do_POST(self):
            # Accept local UI actions only from the server's own origin.
            expected = f'http://127.0.0.1:{self.server.server_port}'
            if self.headers.get('Origin') != expected:
                self.respond(403, b'Zugriff nicht erlaubt', 'text/plain')
            elif self.path == '/api/action':
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 2048:
                        raise ValueError('Ung?ltige Anfragegr?sse.')
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError('Ung?ltiges Anfrageformat.')
                    monitor.action(data.get('action'), data.get('name', ''), data.get('enabled', False))
                    self.respond(200, b'{}', 'application/json')
                except (ValueError, UnicodeDecodeError) as error:
                    self.respond(400, str(error).encode(), 'text/plain')
                except OSError as error:
                    self.respond(500, str(error).encode(), 'text/plain')
            else:
                self.respond(404, b'Nicht gefunden', 'text/plain')

        def log_message(self, *_args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-ip', default=ROBOT_IP)
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--rate', type=float, default=RATE_HZ, help='Requested acquisition Hz, 1 to 500')
    args = parser.parse_args()
    if not math.isfinite(args.rate) or not 1 <= args.rate <= 500:
        parser.error('--rate must be between 1 and 500 Hz')
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')

    # Each launch has a separate directory so previous measurements remain intact.
    output = DIRECTORY / 'recordings' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    monitor = Monitor(args.robot_ip, args.rate, output)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(monitor))
    output.mkdir(parents=True)
    monitor.save_peak()
    worker = threading.Thread(target=monitor.run, daemon=True)
    worker.start()
    print(f'Force monitor: http://127.0.0.1:{args.port}\nRecording: {output}\nCtrl+C closes the monitor.', flush=True)

    # Stopping this monitor never stops or otherwise changes the robot.
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop.set()
        server.server_close()
        worker.join(timeout=5)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
