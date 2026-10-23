"""Interactive |tool Fx|, |tool Fy|, |tool Fz| comparisons in three square panels.

Run: python visualize_force/plots/compare_force_xyz.py
Use the toolbar magnifier and drag a rectangle to zoom; Home restores the view.
Both time and force limits are shared, so all three panels zoom together.
"""

import argparse
import sys
import csv
import math
from pathlib import Path

# Recording and coordinate helpers remain in the parent folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pickle

import matplotlib

from force_frames import force_in_tool
from movement_start import movement_start_index


DEFAULT_DATA = (Path(__file__).resolve().parents[1] / 'recordings'
                / 'Fixed force 280 Diff Approach Speeds')


def load_run(source, time_origin='movement'):
    """Use raw precision; align time to detected motion unless recording is requested."""
    times, forces, positions = [], [], []
    first = previous = None
    with source.open(newline='', encoding='utf-8-sig') as stream:
        for row in csv.DictReader(stream):
            stamp = float(row['timestamp'])
            if previous is not None:
                if stamp == previous:
                    continue
                if stamp < previous:
                    raise ValueError(f'Controller timestamp moved backwards in {source}')
            base = [float(row[f'actual_TCP_force_{i}']) for i in range(3)]
            rotation = [float(row[f'actual_TCP_pose_{i}']) for i in range(3, 6)]
            if not all(math.isfinite(value) for value in [stamp, *base, *rotation]):
                raise ValueError(f'Nonfinite telemetry in {source}')
            if first is None:
                first = stamp
            times.append(stamp - first)
            forces.append(tuple(abs(value) for value in force_in_tool(base, rotation)))
            positions.append(float(row['actual_TCP_pose_2']))
            previous = stamp
    if not times:
        raise ValueError(f'No samples in {source}')
    label = source.parent.name.replace('force_280_approach_', 'Approach ')
    if time_origin == 'movement':
        start = movement_start_index(times, positions)
        offset = times[start]
        times = [time - offset for time in times[start:]]
        forces = forces[start:]
    return label, times, forces


def create_figure(runs):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'toolbar': 'toolbar2', 'axes.spines.top': False,
                         'axes.spines.right': False})
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 6.2), sharex=True, sharey=True)
    colors = ['#1673B8', '#D36514', '#16816A', '#9456A1', '#C84545']
    styles = ['-', '--', '-.']
    z_peak = max(force[2] for _, _, forces in runs for force in forces)
    # Round the upper limit upward for readable ticks; derive it only from |Fz|.
    ymax = max(1.0, math.ceil(z_peak * 1.08 / 10) * 10)
    end = max(times[-1] for _, times, _ in runs)
    for index, (label, times, forces) in enumerate(runs):
        for component, ax in enumerate(axes):
            ax.plot(times, [force[component] for force in forces], label=label,
                    color=colors[index % len(colors)], linestyle=styles[index % len(styles)],
                    linewidth=1.35)
    for axis, component in zip(axes, ('X', 'Y', 'Z')):
        axis.set_title(f'|Tool force {component}|', pad=12)
        axis.set_xlabel('Time since movement started [s]')
        axis.set_ylabel('Absolute force [N]')
        axis.set_box_aspect(1)
        axis.set_xlim(0, end * 1.01 if end else 1)
        axis.set_ylim(0, ymax)
        axis.tick_params(labelleft=True)
        axis.yaxis.set_major_locator(MaxNLocator(nbins=5))
        axis.grid(True, color='#DCE1E6', linewidth=.7)
        axis.set_axisbelow(True)
    fig.suptitle('Absolute tool-frame force versus time from movement start',
                 x=.065, y=.97, ha='left', fontsize=17, fontweight='bold')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper left', bbox_to_anchor=(.06, .925),
               ncol=min(len(runs), 5), frameon=False, handlelength=3)
    fig.text(.065, .05,
             'Zoom: toolbar magnifier, then drag a rectangle. Home resets. All three panels share time and force limits.\n'
             't = 0: Z departs baseline by 0.10 mm for at least 0.10 s. Shared Y limits are based on the largest |Fz|.',
             fontsize=9, color='#555E68', va='bottom')
    fig.subplots_adjust(left=.065, right=.985, bottom=.19, top=.82, wspace=.27)
    for label, _, forces in runs:
        print(f'{label}: peak absolute tool forces '
              + ', '.join(f'{component}={max(f[i] for f in forces):.3f} N'
                          for i, component in enumerate(('X', 'Y', 'Z'))))
    print(f'Shared Y limits: 0 to {ymax:g} N')
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--no-show', action='store_true', help='Save without opening a GUI')
    parser.add_argument('--open-figure', action='store_true', help='Reopen the saved Matplotlib .fig')
    args = parser.parse_args()
    if args.no_show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder = args.data_dir / 'comparison_figures'
    figure_path = folder / 'absolute_force_xyz_vs_time.fig'
    try:
        if args.open_figure:
            # Python-pickled Matplotlib Figure, not a MATLAB FIG file.
            with figure_path.open('rb') as source:
                fig = pickle.load(source)
        else:
            sources = sorted(args.data_dir.glob('*/raw.csv'))
            if not sources:
                parser.error(f'No run folders containing raw.csv in {args.data_dir}')
            fig = create_figure([load_run(source) for source in sources])
            folder.mkdir(parents=True, exist_ok=True)
            with figure_path.open('wb') as target:
                pickle.dump(fig, target, protocol=pickle.HIGHEST_PROTOCOL)
            fig.savefig(folder / 'absolute_force_xyz_vs_time.png', dpi=180, facecolor='white')
            print(f'Saved Matplotlib figure: {figure_path}')
        if not args.no_show:
            plt.show()
        plt.close(fig)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'Could not create/open comparison: {error}\n')


if __name__ == '__main__':
    main()
