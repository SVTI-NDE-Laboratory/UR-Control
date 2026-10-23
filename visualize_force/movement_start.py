"""Estimate movement onset from full-precision TCP Z, independently of force."""

import csv
from statistics import median


def movement_start_index(times, positions_m, threshold_m=.0001, sustain_s=.1):
    """First >=0.10 mm departure from baseline sustained for >=0.10 seconds.

    Baseline is the median Z over the first 0.5 s of the recording. Recording
    must begin with the robot stationary; isolated excursions do not qualify.
    """
    baseline = median(z for t, z in zip(times, positions_m) if t - times[0] < .5)
    start = None
    for i, (time, position) in enumerate(zip(times, positions_m)):
        if i and time - times[i - 1] > .05:
            start = None
        if abs(position - baseline) < threshold_m:
            start = None
        else:
            if start is None:
                start = i
            if time - times[start] >= sustain_s - 1e-9:
                return start
    raise ValueError('No sustained Z movement detected')


def movement_start_recording_s(source):
    with source.open(newline='', encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    stamps = [float(row['timestamp']) for row in rows]
    times = [stamp - stamps[0] for stamp in stamps]
    positions = [float(row['actual_TCP_pose_2']) for row in rows]
    return times[movement_start_index(times, positions)]
