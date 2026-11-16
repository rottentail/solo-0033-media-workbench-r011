"""Project source-time subject tracks onto individual programme pictures."""
import bisect
import math

WIDTH = 640
HEIGHT = 360
CROP = 200
GRID = 20
POSITIONS = tuple(range(0, WIDTH-CROP+1, GRID))


def track(value, clip):
    if not isinstance(value, list) or not 2 <= len(value) <= 64:
        raise ValueError('a subject track needs two to 64 source-time observations')
    result = []
    for point in value:
        if not isinstance(point, dict) or set(point) != {'at_ms', 'left', 'right'}:
            raise ValueError('invalid subject observation')
        at, left, right = (point[k] for k in ('at_ms', 'left', 'right'))
        if (type(at) is not int or at < 0 or any(type(v) not in (int,float)
                or not math.isfinite(v) for v in (left,right)) or not 0 <= left < right <= WIDTH):
            raise ValueError('invalid source-time subject bounds')
        if result and at <= result[-1]['at_ms']:
            raise ValueError('subject observations must increase in source time')
        result.append(dict(at_ms=at, left=float(left), right=float(right)))
    if result[0]['at_ms'] > clip['start_ms'] or result[-1]['at_ms'] < clip['end_ms']:
        raise ValueError('subject track must cover the entire selected source interval')
    return result


def bounds(points, at_ms):
    """Linearly interpolate subject bounds at a source-time position."""
    times = [point['at_ms'] for point in points]
    index = min(len(points)-2, max(0, bisect.bisect_right(times, at_ms)-1))
    first, last = points[index:index+2]
    fraction = (at_ms-first['at_ms'])/(last['at_ms']-first['at_ms'])
    return tuple(first[key]+fraction*(last[key]-first[key]) for key in ('left','right'))


def _occurrences(clips, tracks):
    # Every timeline occurrence owns its own annotation, including repeated
    # cut-ins of the same asset with different trims, so each track is
    # validated against that occurrence's selected source interval.
    entries = []
    cursor = 0
    for clip, points in zip(clips, tracks):
        checked = track(points, clip)
        duration = clip['end_ms']-clip['start_ms']
        entry = dict(start=cursor,stop=cursor+duration,points=checked,
                     source_start=clip['start_ms'])
        entries.append(entry)
        cursor += duration
    return entries, cursor


def project(clips, tracks):
    if not isinstance(tracks,list) or len(tracks) != len(clips):
        raise ValueError('one subject track is required for each timeline occurrence')
    entries,duration = _occurrences(clips,tracks)
    if not 0 < duration <= 30000 or len(clips) > 8:
        raise ValueError('portrait programme supports up to 30 seconds and eight occurrences')
    frames = []
    occurrence = 0
    for index in range((duration+39)//40):
        programme_ms = min(index*40+20,duration-0.000001)
        while programme_ms >= entries[occurrence]['stop']:
            occurrence += 1
        entry = entries[occurrence]
        local_ms = programme_ms-entry['start']
        # Observations are drawn at source positions; interpolate them in
        # source time so each cut-in follows its own selected source segment.
        left,right = bounds(entry['points'], entry['source_start']+local_ms)
        choices = []
        for x in POSITIONS:
            outside_left = max(0,x-left)
            outside_right = max(0,right-x-CROP)
            if outside_left+outside_right == 0:
                choices.append(x)
        if not choices:
            raise ValueError('subject cannot fit the portrait aperture')
        frame = dict(index=index,occurrence=occurrence,
            source_ms=entry['source_start']+local_ms,local_ms=local_ms,
            left=left,right=right,ideal=(left+right-CROP)/2,allowed=choices)
        frames.append(frame)
    return frames,[entry['points'] for entry in entries]
