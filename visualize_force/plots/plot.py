"""Plot a recorded force.csv without connecting to the robot."""

import argparse
import sys
import csv
from pathlib import Path

# Recording and coordinate helpers remain in the parent folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv_file', type=Path)
    parser.add_argument('--save', type=Path, help='Export a PNG instead of opening a window')
    parser.add_argument('--target-force', type=float, help='Manually supplied absolute target [N]')
    args = parser.parse_args()
    try:
        import matplotlib
        if args.save:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        parser.exit(1, 'Install visualize_force/requirements-plot.txt for plotting.\n')
    try:
        with args.csv_file.open(newline='', encoding='utf-8') as source:
            rows = list(csv.DictReader(source))
        if not rows:
            raise ValueError('No samples')
        t = [float(row['elapsed_s']) for row in rows]
        fig, ax = plt.subplots(figsize=(10, 5))
        for key, label in [('force_tool_z_N', 'Signed tool Z'),
                           ('abs_force_tool_z_N', '|Tool Z|')]:
            ax.plot(t, [float(row[key]) for row in rows], label=label)
        if args.target_force is not None:
            ax.axhline(abs(args.target_force), linestyle='--', color='gray', label='Absolute target')
        ax.set(xlabel='Elapsed time [s]', ylabel='Force [N]', title=args.csv_file.parent.name)
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        if args.save:
            with args.save.open('xb') as destination:
                fig.savefig(destination, format='png', dpi=160)
            print(args.save)
        else:
            plt.show()
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'Plot failed: {error}\n')


if __name__ == '__main__':
    main()
