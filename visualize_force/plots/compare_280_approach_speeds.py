"""Interactive time and force-displacement comparison of the three 280 N runs.

Run using a Python environment with matplotlib installed:
    python visualize_force/plots/compare_280_approach_speeds.py
"""

import argparse
import sys
import csv
from pathlib import Path

# Recording and coordinate helpers remain in the parent folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pickle

import matplotlib
from matplotlib.ticker import MultipleLocator

from force_frames import force_in_tool
from movement_start import movement_start_index


DATA = Path(__file__).resolve().parents[1] / 'recordings' / 'Fixed force 280 Diff Approach Speeds'


def load_run(folder):
    # Use original precision for both pose and orientation-based force rotation.
    source = folder / 'raw.csv'
    with source.open(newline='', encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    time, z, force = [], [], []
    first = float(rows[0]['timestamp'])
    previous = None
    for row in rows:
        stamp = float(row['timestamp'])
        if stamp == previous:
            continue
        if previous is not None and stamp < previous:
            raise ValueError(f'Backwards timestamp in {source}')
        time.append(stamp - first)
        z.append(float(row['actual_TCP_pose_2']) * 1000)
        base_force = [float(row[f'actual_TCP_force_{i}']) for i in range(3)]
        rotation = [float(row[f'actual_TCP_pose_{i}']) for i in range(3, 6)]
        force.append(force_in_tool(base_force, rotation)[2])
        previous = stamp
    start = movement_start_index(time, [value / 1000 for value in z])
    offset = time[start]
    return [value - offset for value in time[start:]], z[start:], [abs(value) for value in force[start:]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-show', action='store_true', help='Save without opening a window')
    parser.add_argument('--open-figure', action='store_true', help='Reopen the saved Matplotlib .fig')
    args = parser.parse_args()
    if args.no_show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output = DATA / 'comparison_figures'
    figure_path = output / 'force_280_time_and_displacement.fig'
    if args.open_figure:
        # This file is a Python-pickled Matplotlib Figure, not a MATLAB FIG.
        with figure_path.open('rb') as stream:
            fig = pickle.load(stream)
        if not args.no_show:
            plt.show()
        return
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'axes.titlesize': 12, 'axes.labelsize': 11,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42})
    fig = plt.figure(figsize=(13, 10))
    grid = fig.add_gridspec(2, 2, height_ratios=(1, 1.2))
    position_ax = fig.add_subplot(grid[0, 0])
    force_ax = fig.add_subplot(grid[0, 1], sharex=position_ax)
    displacement_ax = fig.add_subplot(grid[1, :])
    colors = ['#1673B8', '#D36514', '#16816A']
    styles = ['-', '--', '-.']
    maximum_time = 0
    for identifier, color, style in zip(('001', '002', '004'), colors, styles):
        time, z, force = load_run(DATA / f'force_280_approach_{identifier}')
        maximum_time = max(maximum_time, time[-1])
        label = f'Approach {identifier}'
        position_ax.plot(time, z, color=color, linestyle=style, linewidth=1.5, label=label)
        force_ax.plot(time, force, color=color, linestyle=style, linewidth=1.4, label=label)
        displacement = [value - z[0] for value in z]
        # Preserve acquisition order, including hold and return (no sorting by Z).
        displacement_ax.plot(displacement, force, color=color, linestyle=style,
                             linewidth=1.3, label=label)
        displacement_ax.plot(displacement[0], force[0], 'o', color=color, markersize=4)
        print(f'{label}: {len(time)} samples, {time[-1]:.3f} s, '
              f'Z {min(z):.3f} to {max(z):.3f} mm, '
              f'peak absolute tool Z force {max(force):.3f} N')

    position_ax.set_title('(a) TCP Z position in the robot base frame', loc='left', pad=12)
    position_ax.set_ylabel('TCP Z position [mm]')
    position_ax.set_xlabel('Time since movement started [s]')
    position_ax.yaxis.set_major_locator(MultipleLocator(10))
    force_ax.set_title('(b) Measured force along the current tool Z axis', loc='left', pad=12)
    force_ax.set_ylabel('Absolute tool Z force [N]')
    force_ax.set_xlabel('Time since movement started [s]')
    force_ax.axhline(280, color='#60656B', linestyle=(0, (4, 4)), linewidth=1, zorder=0)
    force_ax.yaxis.set_major_locator(MultipleLocator(100))
    force_ax.set_xlim(0, maximum_time + .15)
    force_ax.xaxis.set_major_locator(MultipleLocator(2))
    displacement_ax.set_title('(c) Tool Z force versus TCP Z displacement', loc='left', pad=12)
    displacement_ax.set_xlabel('Base-frame Z displacement from initial TCP position [mm]')
    displacement_ax.set_ylabel('Absolute tool Z force [N]')
    displacement_ax.axhline(280, color='#60656B', linestyle=(0, (4, 4)), linewidth=1,
                            label='280 N magnitude reference')
    displacement_ax.xaxis.set_major_locator(MultipleLocator(5))
    displacement_ax.yaxis.set_major_locator(MultipleLocator(100))
    displacement_ax.legend(loc='upper right', frameon=True, fontsize=9)
    for ax in (position_ax, force_ax, displacement_ax):
        ax.grid(True, color='#DCE1E6', linewidth=.7, alpha=.9)
        ax.set_axisbelow(True)
        ax.margins(y=.12)
    fig.suptitle('280 N force application: time and displacement',
                 x=.085, y=.97, ha='left', fontsize=17, fontweight='bold')
    handles, labels = position_ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper left', bbox_to_anchor=(.078, .935),
               ncol=3, frameon=False, handlelength=3)
    fig.text(.085, .027,
             't = 0: Z departs baseline by 0.10 mm for at least 0.10 s. Displacement = Z(t) - Z(movement start).\n'
             'Absolute tool Z force; full-precision raw data, no smoothing. Approach, hold and return remain in acquisition order.',
             fontsize=9, color='#555E68', va='bottom')
    fig.subplots_adjust(left=.085, right=.975, top=.845, bottom=.14, hspace=.45, wspace=.25)
    output.mkdir(parents=True, exist_ok=True)
    with figure_path.open('wb') as stream:
        pickle.dump(fig, stream, protocol=pickle.HIGHEST_PROTOCOL)
    print(figure_path)
    preview = output / 'force_280_time_and_displacement.png'
    with preview.open('wb') as stream:
        fig.savefig(stream, format='png', dpi=180, facecolor='white')
    print(preview)
    if not args.no_show:
        plt.show()
    plt.close(fig)


if __name__ == '__main__':
    main()
