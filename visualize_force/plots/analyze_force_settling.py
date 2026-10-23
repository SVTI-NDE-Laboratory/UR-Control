"""Estimate settling of |tool Fz| using sustained tolerance-band membership.

Run: python visualize_force/plots/analyze_force_settling.py
The reported time is the START of the first continuously in-band interval of
at least one second; it can only be confirmed one second later in real time.
Primary report times are relative to detected TCP movement, not recording start.
"""

import argparse
import sys
import csv
from pathlib import Path

# Recording and coordinate helpers remain in the parent folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compare_force_xyz import DEFAULT_DATA, load_run
from movement_start import movement_start_recording_s


def sustained_intervals(times, inside, minimum_duration, max_gap=.05):
    """Return index pairs of contiguous valid intervals, rejecting telemetry gaps."""
    intervals = []
    start = None
    for i in range(len(times) + 1):
        valid = i < len(times) and inside[i]
        gap = i > 0 and i < len(times) and times[i] - times[i - 1] > max_gap
        if start is not None and (not valid or gap):
            if times[i - 1] - times[start] >= minimum_duration - 1e-9:
                intervals.append((start, i - 1))
            start = None
        if valid and start is None:
            start = i
    return intervals


def analyze(source, target=280.0, window=1.0):
    label, times, vectors = load_run(source, time_origin='recording')
    movement = movement_start_recording_s(source)
    force = [value[2] for value in vectors]
    # Exclude isolated baseline spikes: require 0.2 s continuously above 5% target.
    contacts = sustained_intervals(times, [value >= .05 * target for value in force], .2)
    contact = times[contacts[0][0]] if contacts else None
    results = []
    for tolerance in (.05, .02):
        intervals = sustained_intervals(times, [abs(value - target) <= tolerance * target
                                                for value in force], window)
        start, end = intervals[0] if intervals else (None, None)
        settled = times[start] if start is not None else None
        result = {'run': label, 'target_N': target, 'tolerance_percent': tolerance * 100,
                  'band_min_N': target * (1 - tolerance),
                  'band_max_N': target * (1 + tolerance), 'required_duration_s': window,
                  'force_onset_recording_s': contact,
                  'movement_start_recording_s': movement,
                  'settled_recording_s': settled,
                  'settled_after_movement_s': settled - movement if settled is not None else None,
                  'confirmed_after_movement_s': settled + window - movement if settled is not None else None,
                  'settled_after_onset_s': settled - contact if settled is not None and contact is not None else None,
                  'peak_abs_tool_z_N': max(force),
                  'overshoot_percent': (max(force) / target - 1) * 100,
                  'confirmed_recording_s': next((t for t in times[start:] if t >= settled + window - 1e-9), None)
                  if start is not None else None,
                  'first_stable_interval_end_s': times[end] if end is not None else None,
                  'qualifying_interval_count': len(intervals)}
        results.append(result)
        print(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    results = [row for path in sorted(args.data_dir.glob('*/raw.csv')) for row in analyze(path)]
    if not results:
        parser.error('No run folders containing raw.csv')
    output = args.data_dir / 'comparison_figures' / 'force_settling_summary.csv'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        for row in results:
            writer.writerow({key: f'{value:.3f}' if isinstance(value, float) else value
                             for key, value in row.items()})
    print(output)
    report_path = output.with_name('force_settling_report.txt')
    primary = [row for row in results if row['tolerance_percent'] == 5]
    tighter = {row['run']: row for row in results if row['tolerance_percent'] == 2}
    lines = [
        '280 N force application comparison',
        '',
        'Objective: reach a stable absolute tool Z force as quickly as possible after TCP movement begins.',
        '',
        'Method',
        'Use full-precision raw TCP pose and force, rotate force into current tool axes, and take absolute Z force.',
        'Time zero is the first Z departure of at least 0.10 mm from the median Z of the first 0.5 s,',
        'sustained for at least 0.10 s. This is an estimated physical motion onset, not a program command timestamp.',
        'Stable means every sample lies within 266-294 N (+/-5% of 280 N) for at least one continuous second.',
        'Reject telemetry gaps longer than 0.05 s. Also evaluate the tighter 274.4-285.6 N (+/-2%) band.',
        'Settling time is the beginning of the qualifying interval; online confirmation takes one additional second.',
        '',
        'Results: all settling times are seconds after movement onset',
        'Run            +/-5%     +/-2%     Peak |Fz|     Overshoot',
    ]
    for row in primary:
        lines.append(f"{row['run']:<15}{row['settled_after_movement_s']:>5.2f}     "
                     f"{tighter[row['run']]['settled_after_movement_s']:>5.2f}      "
                     f"{row['peak_abs_tool_z_N']:>6.1f} N      {row['overshoot_percent']:>4.1f}%")
    lines += [
        '',
        'Conclusion',
        'Approach 004 is the best of these three runs when the priority is shortest time from movement to stable force.',
        'It settles in 1.52 s at +/-5%, versus 1.80 s for 002 and 3.21 s for 001. It also wins at +/-2% (2.03 s).',
        'Compared with 002, its +/-5% advantage is only 0.28 s (about 16%), while its peak force rises from 296.5 N',
        'to 328.9 N. Choose 004 when that transient overshoot is acceptable; 002 is the better compromise if',
        'limiting the force peak matters. Approach 001 has the smallest peak but is substantially slower.',
        '',
        'Scope',
        'The ranking describes one recorded cycle per setting. Repeat trials to establish repeatability.',
        'A one-second criterion does not guarantee permanent containment: the +/-2% cases have later excursions.',
        'Labels 001, 002 and 004 identify the recorded settings; their physical speed values are not in the metadata.',
        'The baseline method assumes the recording begins with at least 0.5 s of stationary TCP pose.',
        'Updated Matplotlib figures use the same movement onset definition and absolute force values.',
    ]
    report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(report_path)


if __name__ == '__main__':
    main()
