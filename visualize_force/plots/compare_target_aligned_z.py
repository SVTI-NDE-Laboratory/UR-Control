"""Plot Z repeats aligned to target force, with measured unloading onset times."""

import argparse
import csv
import math
from pathlib import Path
from statistics import median

from compare_force_events import COLORS, DATA_DIR, read_run

import matplotlib.pyplot as plt


def drop_start(run):
    """First drop below 98% of target sustained for 0.10 s after readiness."""
    start = None
    previous = None
    for time, force in zip(run['times'], run['forces']):
        if time < run['settled_s']:
            continue
        if previous is not None and time - previous > .05:
            start = None
        if force[2] < .98 * run['target_N']:
            if start is None:
                start = time
            if time - start >= .1 - 1e-9:
                return start
        else:
            start = None
        previous = time
    raise ValueError(f"No sustained force drop in {run['folder']}")


def create_figure(runs, output, time_limits):
    """Show two event lines and retain individual drop times as markers and a table."""
    fig, ax = plt.subplots(figsize=(11, 7))
    intervals = []
    for color, run in zip(COLORS, runs):
        times = [time - run['target_s'] for time in run['times']]
        forces = [force[2] for force in run['forces']]
        interval = run['drop_start_s'] - run['target_s']
        intervals.append(interval)
        ax.plot(times, forces, color=color, linewidth=1.4, alpha=.85,
                label=f"Repeat {run['repeat']}")
        index = min(range(len(times)), key=lambda i: abs(times[i] - interval))
        ax.plot(interval, forces[index], 'o', color=color, markersize=6,
                markeredgecolor='white', markeredgewidth=.5)

    # Exactly two vertical lines: aligned target crossing and median drop onset.
    middle = median(intervals)
    ax.axvline(0, color='#454C54', linestyle='--', linewidth=1.2)
    ax.axvline(middle, color='#454C54', linestyle='-.', linewidth=1.2)
    ax.axhline(240, color='#7D8790', linestyle=':', linewidth=1)
    ax.text(.07, 283, 'Target reached\nt = 0.00 s', fontsize=10, va='top')
    ax.text(middle + .07, 283, f'Drop starts\nmedian: {middle:.2f} s', fontsize=10, va='top')
    ax.annotate('', xy=(middle, 302), xytext=(0, 302),
                arrowprops=dict(arrowstyle='<->', color='#454C54'))
    ax.text(middle / 2, 308, f'Median interval: {middle:.2f} s', ha='center', fontsize=10)
    ax.set(xlabel='Time relative to first reaching 240 N [s]', ylabel='Absolute tool Z force |Fz| [N]',
           xlim=time_limits, ylim=(0, 320))
    ax.grid(True, color='#DCE1E6', linewidth=.7)
    ax.set_axisbelow(True)
    ax.legend(loc='lower left', framealpha=.95)
    position = runs[0]['position_mm']
    fixed_y = round(runs[0]['fixed_y_mm'])
    settling = runs[0]['settling_time_s']
    measurement = runs[0]['measurement_duration_s']
    fig.suptitle(f'Absolute tool Z force | X = {position} mm, fixed Y = {fixed_y} mm (cobot base)\n'
                 f'240 N target; {settling:g} s settling; {measurement:g} s measurement; '
                 'target-aligned repeats', fontsize=13)
    fig.subplots_adjust(left=.09, right=.98, bottom=.31, top=.86)

    # List each repeat's target-to-drop interval; colored markers locate those events.
    table_ax = fig.add_axes([.29, .12, .42, .13])
    table_ax.axis('off')
    rows = [[f"Repeat {run['repeat']}", f'{interval:.2f} s'] for run, interval in zip(runs, intervals)]
    table = table_ax.table(cellText=rows, colLabels=['Repeat', 'Target reached -> drop starts'],
                           cellLoc='center', loc='upper center')
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.15)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor('#DCE1E6')
        if row == 0:
            cell.set_facecolor('#EEF2F5')
    fig.text(.09, .035,
             'Target: first recorded |Fz| ≥240 N. Drop onset: |Fz| <235.2 N for ≥0.10 s after readiness.\n'
             'The second vertical line shows the median onset; colored dots mark each repeat. '
             'Measured force, no smoothing. Shared scale: 0–320 N.', fontsize=8.5, color='#555E68')
    fig.savefig(output, dpi=200, facecolor='white')
    plt.close(fig)
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DATA_DIR)
    args = parser.parse_args()
    runs = [read_run(folder) for folder in args.data_dir.glob('force_240_x*_*') if folder.is_dir()]
    runs.sort(key=lambda run: (run['position_mm'], run['repeat']))
    if not runs:
        parser.error('No position repeats found')
    conditions = {(run['target_N'], run['settling_time_s'], run['measurement_duration_s'],
                   round(run['fixed_y_mm'])) for run in runs}
    if len(conditions) != 1:
        parser.error('Runs must share target, settling time, measurement duration and Y position')
    for run in runs:
        run['drop_start_s'] = drop_start(run)
    time_limits = (math.floor(min(run['times'][0] - run['target_s'] for run in runs)),
                   math.ceil(max(run['times'][-1] - run['target_s'] for run in runs)))
    output = args.data_dir / 'comparison_figures'
    output.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    for position in sorted({run['position_mm'] for run in runs}):
        group = [run for run in runs if run['position_mm'] == position]
        if len(group) != 3:
            parser.error(f'Expected three repeats at X = {position} mm')
        create_figure(group, output / f'force_240_x{position}_target_aligned_z.png', time_limits)
    with (output / 'target_to_drop_intervals.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['run', 'position_mm', 'repeat', 'target_to_drop_s'])
        for run in runs:
            writer.writerow([run['folder'], run['position_mm'], run['repeat'],
                             f"{run['drop_start_s'] - run['target_s']:.3f}"])


if __name__ == '__main__':
    main()
