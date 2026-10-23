"""Offline conversion of ur_rtde's native CSV into force in current TCP axes."""

import argparse
import csv
import math
from pathlib import Path


def force_in_tool(force, rotation_vector):
    """Apply inverse axis-angle rotation; no translation or torque origin shift."""
    angle = math.hypot(*rotation_vector)
    if angle < 1e-12:
        return tuple(force)
    x, y, z = (value / angle for value in rotation_vector)
    fx, fy, fz = force
    c, s = math.cos(angle), math.sin(angle)
    dot = x * fx + y * fy + z * fz
    cross = (y * fz - z * fy, z * fx - x * fz, x * fy - y * fx)
    return tuple(c * f - s * k + (1 - c) * axis * dot
                 for f, k, axis in zip(force, cross, (x, y, z)))


def convert(raw_path, output_path):
    """Order columns as timestamps, poses, forces, then remaining telemetry."""
    count = duplicates = 0
    first = previous = None
    with Path(raw_path).open(newline='', encoding='utf-8-sig') as source:
        sample = source.read(8192)
        source.seek(0)
        if not sample.strip():
            raise ValueError('Raw CSV is empty')
        # ur_rtde versions may use commas or semicolons.
        delimiter = ';' if ';' in sample.splitlines()[0] else ','
        reader = csv.DictReader(source, delimiter=delimiter)
        required = ['timestamp'] + [f'actual_TCP_{name}_{i}'
                                   for name in ('force', 'pose') for i in range(6)]
        if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
            raise ValueError('Raw CSV must contain timestamp and all six actual_TCP_force/pose components')
        added = ['elapsed_s', 'sample_dt_s', 'force_tool_x_N', 'force_tool_y_N',
                 'force_tool_z_N', 'abs_force_tool_z_N']
        columns = (['timestamp', 'elapsed_s']
                   + [f'actual_TCP_pose_{i}' for i in range(6)]
                   + [f'actual_TCP_force_{i}' for i in range(6)]
                   + added[2:] + ['sample_dt_s'])
        columns += [name for name in reader.fieldnames if name not in columns]
        with Path(output_path).open('x', newline='', encoding='utf-8') as target:
            writer = csv.DictWriter(target, fieldnames=columns)
            writer.writeheader()
            for row in reader:
                values = [float(row[key]) for key in required]
                if not all(math.isfinite(value) for value in values):
                    raise ValueError('Nonfinite telemetry value in raw CSV')
                timestamp = values[0]
                if previous is not None and timestamp == previous:
                    duplicates += 1
                    continue
                if previous is not None and timestamp < previous:
                    raise ValueError('Controller timestamp moved backwards; recording spans a restart')
                if first is None:
                    first = timestamp
                tool = force_in_tool(values[1:4], values[10:13])
                dt = 0 if previous is None else timestamp - previous
                row.update(zip(added, [timestamp - first, dt, *tool, abs(tool[2])]))
                writer.writerow({name: f'{float(row[name]):.3f}' for name in columns})
                previous = timestamp
                count += 1
    if not count:
        raise ValueError('No telemetry samples recorded')
    return {'samples': count, 'duplicate_timestamps_removed': duplicates,
            'elapsed_s': previous - first}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw_csv', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or args.raw_csv.with_name(args.raw_csv.stem + '_force.csv')
    try:
        print(convert(args.raw_csv, output))
        print(output)
    except (OSError, ValueError, IndexError, TypeError) as error:
        parser.exit(1, f'Conversion failed: {error}\nRaw CSV retained.\n')


if __name__ == '__main__':
    main()
