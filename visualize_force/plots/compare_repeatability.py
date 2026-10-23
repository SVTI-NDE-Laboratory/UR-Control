"""Overlay absolute tool X, Y, Z forces from movement onset for repeated measurements.

Run without arguments for the five 280 N repeats at x = -1000 mm.
Exports a PNG without connecting to a robot. All three panels share a force scale.
"""

import argparse
import sys
from pathlib import Path

# Recording and coordinate helpers remain in the parent folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import re

import matplotlib

from compare_force_xyz import load_run


DATA_DIR = Path(__file__).resolve().parents[1] / 'recordings' / 'Repeatability'
RUN_PATTERN = 'force_280_x-1000_*'


def main():
    """Read full-precision telemetry and align repeats using sustained Z movement."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DATA_DIR)
    parser.add_argument('--pattern', default=RUN_PATTERN, help='Run folder pattern for one position')
    parser.add_argument('--compare-positions', action='store_true',
                        help='Overlay all repeats at X = -1000, 0, and 1000 mm; color by position')
    parser.add_argument('--y-max', type=float, default=320, help='Shared force upper limit in N (default: 320)')
    parser.add_argument('--fixed-y', type=float, default=-275, help='Robot Y position in mm, referenced to the cobot base')
    parser.add_argument('--note', help='Operator observation displayed on this figure')
    args = parser.parse_args()
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    positions = (-1000, 0, 1000)
    if args.compare_positions:
        sources = []
        for position in positions:
            prefix = f'force_280_x{position}'
            if args.fixed_y != -275:
                prefix += f'_y{args.fixed_y:g}'
            group = sorted(args.data_dir.glob(f'{prefix}_*/raw.csv'))
            group = [source for source in group
                     if re.fullmatch(re.escape(prefix) + r'_\d+', source.parent.name)]
            if not group:
                parser.error(f'No recordings at X = {position} mm')
            sources.extend(group)
    else:
        sources = sorted(args.data_dir.glob(f'{args.pattern}/raw.csv'))
    if not sources:
        parser.error('No matching raw.csv recordings')
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 3, figsize=(16, 6), sharex=True, sharey=True)
    colors = ['#1673B8', '#D36514', '#16816A', '#9456A1', '#C84545']
    end = 0
    for index, source in enumerate(sources):
        _, times, forces = load_run(source, time_origin='movement')
        repeat = source.parent.name.rsplit('_', 1)[-1]
        color = colors[index % len(colors)]
        label = f'Repeat {repeat}'
        if args.compare_positions:
            position = int(source.parent.name.split('_x', 1)[1].split('_', 1)[0])
            color = colors[positions.index(position)]
            label = f'Robot X = {position} mm'
        for component, ax in enumerate(axes):
            ax.plot(times, [force[component] for force in forces], label=label,
                    color=color, linewidth=1.3, alpha=.7 if args.compare_positions else .85)
        end = max(end, times[-1])
        print(f'{source.parent.name}: {len(times)} samples; '
              f'{times[-1]:.3f} s after movement onset; peak absolute forces: '
              + ', '.join(f'{name} = {max(force[i] for force in forces):.3f} N'
                          for i, name in enumerate(('X', 'Y', 'Z'))))
    axes[2].axhline(280, color='#48515B', linestyle='--', linewidth=1.2, label='Target: 280 N')
    position = sources[0].parent.name.rsplit('_', 1)[0].replace('force_280_', '')
    x_position = position.split('_y', 1)[0].removeprefix('x')
    title = (f'Influence of robot X position — 280 N — {len(sources)} runs'
             if args.compare_positions else
             f'280 N repeatability — X = {x_position} mm — {len(sources)} repeats')
    title += f'\nFixed Y = {args.fixed_y:g} mm; positions referenced to the cobot base'
    fig.suptitle(title, fontsize=17)
    for ax, name in zip(axes, ('X', 'Y', 'Z')):
        ax.set(title=f'Tool {name}', xlabel='Time since movement started [s]',
               ylabel=f'Absolute tool {name} force |F{name.lower()}| [N]',
               xlim=(0, end * 1.01), ylim=(0, args.y_max))
        ax.tick_params(labelleft=True)
        ax.grid(True, color='#DCE1E6', linewidth=.7)
        ax.set_axisbelow(True)
    handles, labels = axes[2].get_legend_handles_labels()
    legend = dict(zip(labels, handles))
    fig.legend(legend.values(), legend.keys(), loc='upper center', bbox_to_anchor=(.5, .865),
               ncol=len(legend), frameon=False)
    if args.note:
        fig.text(.5, .77, f'Operator observation: {args.note}', ha='center', va='top',
                 fontsize=10, color='#923B25',
                 bbox=dict(facecolor='#FFF3E9', edgecolor='#E5B59D', boxstyle='round,pad=.5'))
    fig.text(.05, .035,
             'Each repeat starts at sustained TCP Z movement: ≥0.10 mm from baseline for ≥0.10 s.\n'
             'Full-precision raw telemetry transformed to current tool axes; no smoothing. '
             'All panels use the same force scale.',
             fontsize=9, color='#555E68')
    fig.tight_layout(rect=(0, .1, 1, .72 if args.note else .80))
    folder = args.data_dir / 'comparison_figures'
    folder.mkdir(parents=True, exist_ok=True)
    comparison_name = ('position_comparison_abs_force_xyz' if args.fixed_y == -275 else
                       f'position_comparison_y{args.fixed_y:g}_abs_force_xyz')
    stem = folder / (comparison_name if args.compare_positions else
                     f'repeatability_{position}_abs_force_xyz')
    fig.savefig(stem.with_suffix('.png'), dpi=200, facecolor='white')
    plt.close(fig)
    print(f'Saved: {stem.with_suffix(".png")}')


if __name__ == '__main__':
    main()
