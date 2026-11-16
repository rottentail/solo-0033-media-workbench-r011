"""Choose a whole-shot framing path with bounded speed and acceleration.

The path of the portrait aperture is planned for the whole shot at once:
a frame-by-frame greedy choice can hug the current subject centre and then
find itself unable to keep up when the subject moves off, or even declare a
perfectly feasible shot impossible. A dynamic program over (left edge,
velocity) states instead finds the minimum total composition cost over every
complete feasible path, subject to the per-frame speed and acceleration
limits.

A state at frame i is the aperture position p_i together with the velocity
v_i = p_i - p_{i-1} used to reach it. Frame zero starts from rest, so v_0 = 0.
A transition to frame i+1 with velocity v is feasible exactly when
``|v| <= max_step`` and ``|v - v_i| <= max_acceleration``; the first real
displacement therefore obeys the same acceleration limit relative to a
stationary virtual predecessor. Motion for each displacement is charged once.

Equal-cost paths resolve to the lexicographically smallest sequence of left
edges, so each state retains the smallest optimal prefix reaching it. Only
integer costs and short prefix lists are retained, never decoded pictures.
"""
from array import array

from .reframe_geometry import POSITIONS

GRID = 20
INF = -1  # array sentinel for an unreachable state


def solve(frames, max_step, max_acceleration, motion_weight):
    for value in (max_step, max_acceleration):
        if type(value) is not int or not 1 <= value <= 4:
            raise ValueError('motion limits must be one to four grid steps')
    if type(motion_weight) is not int or not 0 <= motion_weight <= 10000:
        raise ValueError('invalid portrait motion weight')
    if not frames:
        raise ValueError('empty portrait shot')
    # Position index per frame: allowed left edges are grid multiples that keep
    # the complete subject box inside the aperture. The state space spans the
    # full canvas grid; unreachable positions simply stay unvisited.
    allowed = [frozenset(x//GRID for x in frame['allowed']) for frame in frames]
    width = len(POSITIONS)
    velocities = tuple(range(-max_step, max_step+1))
    velocity_index = {velocity: i for i, velocity in enumerate(velocities)}
    velocity_count = len(velocities)
    states = width*velocity_count

    def slot(position, velocity):
        return position*velocity_count+velocity_index[velocity]

    if len(frames) == 1:
        # A one-frame shot is stationary by definition.
        x = min(frames[0]['allowed'],
                key=lambda edge: ((edge-frames[0]['ideal'])**2, edge))
        return [x], round((x-frames[0]['ideal'])**2*1000)

    # Frame zero opens from rest (velocity zero). Only position varies here;
    # the centering cost is the frame-zero bill with no entering motion.
    costs = array('q', [INF]*states)
    prefixes = [None]*states
    for position in allowed[0]:
        x = position*GRID
        state = slot(position, 0)
        costs[state] = round((x-frames[0]['ideal'])**2*1000)
        prefixes[state] = [x]

    for frame_number in range(1, len(frames)):
        next_costs = array('q', [INF]*states)
        next_prefixes = [None]*states
        for position in allowed[frame_number]:
            x = position*GRID
            centering = round((x-frames[frame_number]['ideal'])**2*1000)
            for velocity in velocities:
                if abs(velocity) > max_step:
                    continue
                predecessor = position-velocity
                if predecessor not in allowed[frame_number-1]:
                    continue
                motion = motion_weight*(velocity*GRID)**2*1000
                best_cost = INF
                best_prefix = None
                for previous_velocity in velocities:
                    if abs(velocity-previous_velocity) > max_acceleration:
                        continue
                    source = slot(predecessor, previous_velocity)
                    prefix_cost = costs[source]
                    if prefix_cost == INF:
                        continue
                    candidate_cost = prefix_cost+centering+motion
                    candidate_prefix = prefixes[source]
                    if (best_prefix is None
                            or candidate_cost < best_cost
                            or (candidate_cost == best_cost
                                and candidate_prefix < best_prefix)):
                        best_cost = candidate_cost
                        best_prefix = candidate_prefix
                if best_prefix is not None:
                    target = slot(position, velocity)
                    next_costs[target] = best_cost
                    next_prefixes[target] = best_prefix+[x]
        costs, prefixes = next_costs, next_prefixes

    optimum = None
    for position in allowed[-1]:
        for velocity in velocities:
            state = slot(position, velocity)
            value = costs[state]
            if value == INF:
                continue
            path = prefixes[state]
            if optimum is None or (value, path) < optimum:
                optimum = (value, path)
    if optimum is None:
        raise ValueError('subject motion exceeds the saved camera limits')
    score, path = optimum
    return path, score


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
