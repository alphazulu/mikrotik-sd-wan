"""Validate framed RouterOS /tool/profile replies before CPU attribution."""
import math
import re
import statistics


def percentile95(values):
    return sorted(values)[math.ceil(len(values) * .95) - 1]


def usage(value):
    if isinstance(value, str) and re.fullmatch(r'\d+(?:\.\d+)?%?', value):
        value = float(value.rstrip('%'))
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('Invalid single-CPU usage')
    return float(value)


def summarize_profile(record):
    """Initial total-only frames are warmup; later absent classifiers mean zero."""
    if record.get('pass') is not True or not isinstance(record.get('raw'), list):
        raise ValueError('Successful raw profile is required')
    start, end = record.get('started_monotonic'), record.get('finished_monotonic')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)) or end <= start:
        raise ValueError('Invalid profile window')
    frames = {}
    previous = -1
    for row in record['raw']:
        if not isinstance(row, dict):
            raise ValueError('Invalid profile row')
        section, name = row.get('.section'), row.get('name')
        if not isinstance(section, str) or not section.isascii() or not section.isdigit():
            raise ValueError('Missing API frame section')
        section = int(section)
        if section < previous or section > 100000:
            raise ValueError('Out-of-order API frame')
        previous = section
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name):
            raise ValueError('Invalid classifier name')
        frame = frames.setdefault(section, {})
        if name in frame:
            raise ValueError('Duplicate classifier in frame')
        frame[name] = usage(row.get('usage'))
    sections = list(frames)
    if not sections or sections != list(range(sections[0], sections[-1] + 1)):
        raise ValueError('Missing profile frame')
    if any('total' not in frame for frame in frames.values()):
        raise ValueError('Incomplete profile frame')
    complete = []
    skipped = 0
    for frame in frames.values():
        if not complete and set(frame) == {'total'}:
            skipped += 1
            continue
        complete.append(frame)
    if len(complete) < 2:
        raise ValueError('Insufficient classifier frames after warmup')
    names = set().union(*complete)
    classifiers = {}
    for name in sorted(names):
        values = [frame.get(name, 0.0) for frame in complete]
        classifiers[name] = {'mean_percent': statistics.mean(values),
                             'p95_percent': percentile95(values), 'max_percent': max(values)}
    return {'scope': 'RouterOS profiler classifiers, single vCPU; separate from resource cpu-load',
            'command_seconds': end - start, 'frames_received': len(frames),
            'warmup_frames_skipped': skipped, 'frames_used': len(complete),
            'classifiers': classifiers}
