"""Moving-window settling detector armed on first target crossing, then latched.

Run with Python + matplotlib. Default displays an interactive three-panel
diagnostic figure. --no-show saves a PNG and a pickled Matplotlib .fig only.
The robot scripts are not modified by this offline analysis.
"""

import argparse
import sys
from collections import deque
import csv
import math
from pathlib import Path

# Recording and coordinate helpers remain in the parent folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pickle

import matplotlib

from compare_force_xyz import DEFAULT_DATA, load_run


def rolling_detection(times, force, window=.5, target=280, mean_tolerance=.05,
                      std_max=5.6, slope_max=5.6):
    """Collect fresh history only after first force >= target; latch ready once."""
    history = deque()
    means, stds, slopes, ready = [], [], [], []
    detected = armed = None
    for i, (time, value) in enumerate(zip(times, force)):
        if armed is None:
            if value < target:
                means.append(math.nan)
                stds.append(math.nan)
                slopes.append(math.nan)
                ready.append(False)
                continue
            # Arm once. Subsequent dips below target do not restart the window.
            armed = i
        if i and time - times[i - 1] > .05:
            history.clear()
        history.append((time, value))
        cutoff = time - window
        # Keep one boundary sample at or just before the window start.
        while len(history) > 1 and history[1][0] <= cutoff + 1e-9:
            history.popleft()
        if time - history[0][0] < window - 1e-9:
            mean = std = slope = math.nan
        else:
            count = len(history)
            mean = sum(f for _, f in history) / count
            center = sum(t - time for t, _ in history) / count
            std = math.sqrt(sum((f - mean) ** 2 for _, f in history) / count)
            variance_t = sum((t - time - center) ** 2 for t, _ in history)
            slope = sum((t - time - center) * (f - mean) for t, f in history) / variance_t
            if (detected is None and abs(mean - target) <= mean_tolerance * target
                    and std <= std_max and abs(slope) <= slope_max):
                detected = i
        means.append(mean)
        stds.append(std)
        slopes.append(abs(slope))
        # Latch: later noise, drift, or unloading never resets readiness.
        ready.append(detected is not None)
    return {'mean': means, 'std': stds, 'abs_slope': slopes,
            'ready': ready, 'detected_index': detected, 'armed_index': armed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--window', type=float, default=.5)
    parser.add_argument('--target', type=float, default=280)
    parser.add_argument('--mean-tolerance', type=float, default=.05)
    parser.add_argument('--std-max', type=float, default=5.6)
    parser.add_argument('--slope-max', type=float, default=5.6)
    parser.add_argument('--no-show', action='store_true')
    parser.add_argument('--open-figure', action='store_true')
    args = parser.parse_args()
    for name in ('window', 'target', 'mean_tolerance', 'std_max', 'slope_max'):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            parser.error(f'{name} must be finite and positive')
    if args.no_show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output = args.data_dir / 'comparison_figures'
    output.mkdir(parents=True, exist_ok=True)
    figure_path = output / 'rolling_settling_detection.fig'
    if args.open_figure:
        with figure_path.open('rb') as source:
            fig = pickle.load(source)
        if not args.no_show:
            plt.show()
        return
    sources = sorted(args.data_dir.glob('*/raw.csv'))
    if not sources:
        parser.error('No raw.csv recordings found')
    fig, axes = plt.subplots(1, 3, figsize=(16, 6.4), sharex=True)
    colors = ['#1673B8', '#D36514', '#16816A']
    styles = ['-', '--', '-.']
    results = []
    latest_detection = 0
    for run_index, source in enumerate(sources):
        label, times, vectors = load_run(source)
        force = [value[2] for value in vectors]
        result = rolling_detection(times, force, args.window, args.target,
                                   args.mean_tolerance, args.std_max, args.slope_max)
        color, style = colors[run_index % 3], styles[run_index % 3]
        detected = result['detected_index']
        armed = result['armed_index']
        detection_time = times[detected] if detected is not None else None
        if detected is not None:
            latest_detection = max(latest_detection, detection_time)
        legend = f'{label}: {detection_time:.2f} s' if detected is not None else f'{label}: not detected'
        for axis, values in zip(axes, (force, result['std'], result['abs_slope'])):
            axis.plot(times, values, color=color, linestyle=style, linewidth=1.4, label=legend)
            if detected is not None:
                axis.axvline(detection_time, color=color, linestyle=':', linewidth=1.2, alpha=.8)
                axis.plot(detection_time, values[detected], 'o', color=color, markersize=5)
        if armed is not None:
            axes[0].plot(times[armed], force[armed], '^', color=color, markersize=7)
        row = {'run': label, 'window_s': args.window, 'target_N': args.target,
               'mean_tolerance_percent': args.mean_tolerance * 100,
               'std_limit_N': args.std_max, 'slope_limit_N_per_s': args.slope_max,
               'first_target_reached_movement_s': times[armed] if armed is not None else None,
               'latched_ready_movement_s': detection_time,
               'window_mean_N': result['mean'][detected] if detected is not None else None,
               'window_std_N': result['std'][detected] if detected is not None else None,
               'window_abs_slope_N_per_s': result['abs_slope'][detected] if detected is not None else None}
        results.append(row)
        print(row)
    axes[0].axhspan(args.target * (1 - args.mean_tolerance),
                   args.target * (1 + args.mean_tolerance), color='#7B9B79', alpha=.15)
    axes[0].axhline(args.target, color='#666666', linestyle=':', linewidth=1)
    axes[1].axhspan(0, args.std_max, color='#7B9B79', alpha=.15)
    axes[1].axhline(args.std_max, color='#666666', linestyle=':', linewidth=1)
    axes[2].axhspan(0, args.slope_max, color='#7B9B79', alpha=.15)
    axes[2].axhline(args.slope_max, color='#666666', linestyle=':', linewidth=1)
    for ax, title, ylabel, ymax in zip(
            axes, ('Absolute tool Z force', f'Moving standard deviation ({args.window:g} s)',
                   f'Absolute moving slope ({args.window:g} s)'),
            ('|Tool Fz| [N]', 'Population standard deviation [N]', '|Linear regression slope| [N/s]'),
            (360, 80, 450)):
        ax.set(title=title, xlabel='Time since movement started [s]', ylabel=ylabel)
        ax.set_xlim(0, latest_detection + 1 if latest_detection else 6)
        ax.set_ylim(0, ymax)
        ax.set_box_aspect(1)
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(True, alpha=.25)
    fig.suptitle('Reach target, evaluate settling, then latch readiness',
                 x=.065, y=.97, ha='left', fontsize=17, fontweight='bold')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper left', bbox_to_anchor=(.06, .925),
               ncol=len(sources), frameon=False, handlelength=3)
    fig.text(.065, .035,
             f'Triangle: first |Fz| >= {args.target:g} N. A fresh {args.window:g} s history starts there; later dips do not restart it.\n'
             f'Ready when window mean is within +/-{args.mean_tolerance * 100:g}% of {args.target:g} N, '
             f'std <= {args.std_max:g} N and |slope| <= {args.slope_max:g} N/s.\n'
             'Dots and vertical lines mark the first live decision. The hold timer starts there and is never reset by later fluctuations.',
             fontsize=10, color='#555E68')
    fig.subplots_adjust(left=.065, right=.985, top=.82, bottom=.2, wspace=.3)
    with figure_path.open('wb') as destination:
        pickle.dump(fig, destination, protocol=pickle.HIGHEST_PROTOCOL)
    fig.savefig(output / 'rolling_settling_detection.png', dpi=180, facecolor='white')
    with (output / 'rolling_settling_detection.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    print(figure_path)
    if not args.no_show:
        plt.show()
    plt.close(fig)


if __name__ == '__main__':
    main()
