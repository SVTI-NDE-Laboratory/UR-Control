"""Compare position repeats with measured target, ready, and unloading events."""

import argparse
import csv
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from compare_force_xyz import load_run
from movement_start import movement_start_recording_s


DATA_DIR = (Path(__file__).resolve().parents[1] / 'recordings'
            / 'Force 240, 1.5s settling, 2s application')
COLORS = ['#1673B8', '#D36514', '#16816A']
EVENTS = [('target_s', 'Target reached', 'o'), ('settled_s', 'Settled / ready', 's'),
          ('stopped_s', 'Force stopped', 'v')]


def read_run(folder):
    """Use controller timestamps; detect unloading only after the ready signal."""
    match = re.fullmatch(r'force_240_x(-?\d+)_(\d+)', folder.name)
    position, repeat = map(int, match.groups())
    metadata = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
    source = folder / 'raw.csv'
    _, times, forces = load_run(source, time_origin='recording')
    movement = movement_start_recording_s(source)
    with source.open(newline='', encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    origin = float(rows[0]['timestamp'])
    ready = next(float(row['timestamp']) - origin for row in rows
                 if int(row['output_int_register_42']) == 1)
    target = metadata['target_force_N']
    target_time = next(t for t, force in zip(times, forces) if t >= movement and force[2] >= target)

    # Force cessation is a sustained low measured load, not a force-mode exit timestamp.
    low_start = None
    previous = None
    stopped = None
    for t, force in zip(times, forces):
        if t < ready:
            continue
        if previous is not None and t - previous > .05:
            low_start = None
        if force[2] <= .05 * target:
            if low_start is None:
                low_start = t
            if t - low_start >= .1 - 1e-9:
                stopped = low_start
                break
        else:
            low_start = None
        previous = t
    if stopped is None:
        raise ValueError(f'No sustained unloading detected in {folder.name}')

    # Retain only samples from detected physical movement onward.
    samples = [(t - movement, f) for t, f in zip(times, forces) if t >= movement]
    return {'folder': folder.name, 'position_mm': position, 'repeat': repeat,
            'target_N': target, 'settling_time_s': metadata['settling_time_s'],
            'measurement_duration_s': metadata['measurement_duration_s'],
            'fixed_y_mm': float(rows[0]['actual_TCP_pose_1']) * 1000,
            'target_s': target_time - movement, 'settled_s': ready - movement,
            'stopped_s': stopped - movement, 'times': [t for t, _ in samples],
            'forces': [f for _, f in samples]}


def create_figure(runs, output, combined=False):
    """Use shared scales and event markers, with exact per-repeat times below."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 9), sharex=True, sharey=True)
    end = max(run['times'][-1] for run in runs)
    for index, run in enumerate(runs):
        color = COLORS[(-1000, 0, 1000).index(run['position_mm'])] if combined else COLORS[index]
        label = f"X = {run['position_mm']} mm" if combined else f"Repeat {run['repeat']}"
        for component, ax in enumerate(axes):
            values = [force[component] for force in run['forces']]
            ax.plot(run['times'], values, color=color, linewidth=1.25, alpha=.75, label=label)
            for key, _, marker in EVENTS:
                i = min(range(len(values)), key=lambda i: abs(run['times'][i] - run[key]))
                ax.plot(run[key], values[i], marker=marker, color=color, markersize=5,
                        markeredgecolor='white', markeredgewidth=.5, linestyle='none')
    axes[2].axhline(runs[0]['target_N'], color='#48515B', linestyle='--', linewidth=1,
                    label=f"Target: {runs[0]['target_N']:g} N")
    for ax, name in zip(axes, ('X', 'Y', 'Z')):
        ax.set(title=f'Tool {name}', xlabel='Time since movement started [s]',
               ylabel=f'Absolute tool {name} force [N]', xlim=(0, end * 1.01), ylim=(0, 320))
        ax.tick_params(labelleft=True)
        ax.grid(True, color='#DCE1E6', linewidth=.7)
        ax.set_axisbelow(True)

    # Keep position/repeat colors separate from event marker meanings.
    handles, labels = axes[2].get_legend_handles_labels()
    legend = dict(zip(labels, handles))
    fig.legend(legend.values(), legend.keys(), loc='upper center', bbox_to_anchor=(.5, .88),
               ncol=len(legend), frameon=False)
    event_handles = [plt.Line2D([], [], color='#48515B', marker=marker, linestyle='none', label=label)
                     for _, label, marker in EVENTS]
    fig.legend(handles=event_handles, loc='upper center', bbox_to_anchor=(.5, .835), ncol=3, frameon=False)
    position = 'Comparison of X = -1000, 0 and 1000 mm' if combined else f"X = {runs[0]['position_mm']} mm"
    fig.suptitle(f'240 N | {position} | {len(runs)} runs\n'
                 'Fixed Y = -275 mm; positions referenced to the cobot base\n'
                 'Settling delay: 1.5 s; measurement: 2 s', fontsize=15, y=.98)
    fig.subplots_adjust(left=.06, right=.985, bottom=.43, top=.755, wspace=.25)

    # Each row reports that run's timing; no averaging hides repeat differences.
    table_ax = fig.add_axes([.2, .115, .6, .265])
    table_ax.axis('off')
    table_rows = [[str(run['position_mm']), str(run['repeat'])]
                  + [f'{run[key]:.2f}' for key, _, _ in EVENTS] for run in runs]
    table = table_ax.table(cellText=table_rows,
                           colLabels=['Robot X [mm]', 'Repeat', 'Target reached [s]',
                                      'Settled / ready [s]', 'Force stopped [s]'],
                           cellLoc='center', loc='upper center')
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.12)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor('#DCE1E6')
        if row == 0:
            cell.set_facecolor('#EEF2F5')
    fig.text(.06, .035,
             'Time zero: TCP Z moves ≥0.10 mm for ≥0.10 s. Target: first recorded |Fz| ≥240 N. '
             'Settled / ready: output register 42 becomes 1.\n'
             'Force stopped: first |Fz| ≤12 N sustained for ≥0.10 s after readiness; '
             'this is measured unloading, not the force-mode exit command.\n'
             'Readiness follows the configured delay; it does not certify force stability. '
             'Raw forces transformed into current tool axes; no smoothing. All force scales: 0–320 N.',
             fontsize=9, color='#555E68')
    fig.savefig(output, dpi=200, facecolor='white')
    plt.close(fig)
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DATA_DIR)
    args = parser.parse_args()
    runs = [read_run(folder) for folder in args.data_dir.glob('force_240_x*_*') if folder.is_dir()]
    runs.sort(key=lambda run: (run['position_mm'], run['repeat']))
    if len(runs) != 9 or any(sum(r['position_mm'] == x for r in runs) != 3 for x in (-1000, 0, 1000)):
        parser.error('Expected three repeats at each of X = -1000, 0 and 1000 mm')
    if any((r['target_N'], r['settling_time_s'], r['measurement_duration_s']) != (240, 1.5, 2)
           or abs(r['fixed_y_mm'] + 275) > 1 for r in runs):
        parser.error('Recordings must share 240 N, 1.5 s settling, 2 s measurement and Y = -275 mm')
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    output = args.data_dir / 'comparison_figures'
    output.mkdir(exist_ok=True)
    for x in (-1000, 0, 1000):
        create_figure([run for run in runs if run['position_mm'] == x],
                      output / f'force_240_x{x}_events_xyz.png')
    create_figure(runs, output / 'force_240_position_comparison_events_xyz.png', combined=True)
    fields = ['folder', 'position_mm', 'repeat', 'target_s', 'settled_s', 'stopped_s']
    with (output / 'force_event_times.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(runs)


if __name__ == '__main__':
    main()
