"""Choose a whole-shot framing path with bounded speed and acceleration."""
def _candidates(frame, previous, velocity, max_step, max_acceleration, motion_weight):
    candidates = []
    for x in frame['allowed']:
        step = (x-previous)//20
        if abs(step) > max_step:
            continue
        if abs(step-velocity) > max_acceleration:
            continue
        error = round((x-frame['ideal'])**2*1000)
        motion = motion_weight*(x-previous)**2*1000
        candidates.append((error+motion,x,step))
    candidates.sort()
    return candidates


def solve(frames, max_step, max_acceleration, motion_weight):
    for value in (max_step,max_acceleration):
        if type(value) is not int or not 1 <= value <= 4:
            raise ValueError('motion limits must be one to four grid steps')
    if type(motion_weight) is not int or not 0 <= motion_weight <= 10000:
        raise ValueError('invalid portrait motion weight')
    if not frames:
        raise ValueError('empty portrait shot')
    first = min(frames[0]['allowed'],key=lambda x:((x-frames[0]['ideal'])**2,x))
    score = round((first-frames[0]['ideal'])**2*1000)
    path = [first]
    velocity = 0
    for frame in frames[1:]:
        candidates = _candidates(frame,path[-1],velocity,max_step,max_acceleration,motion_weight)
        if not candidates:
            raise ValueError('subject motion exceeds the saved camera limits')
        cost,x,velocity = candidates[0]
        path.append(x)
        score += cost
    return path,score


def programme(frames, max_step=2, max_acceleration=1, motion_weight=1):
    result = []
    score = 0
    begin = 0
    while begin < len(frames):
        end = begin+1
        while end < len(frames) and frames[end]['occurrence'] == frames[begin]['occurrence']:
            end += 1
        path,cost = solve(frames[begin:end],max_step,max_acceleration,motion_weight)
        result.extend(dict(frame,x=x) for frame,x in zip(frames[begin:end],path))
        score += cost
        begin = end
    return result,score
