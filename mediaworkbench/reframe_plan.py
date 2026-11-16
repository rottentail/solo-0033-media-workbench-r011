"""Immutable source-aware portrait framing plans and offline previews."""
import hashlib
import json
from . import db, media_sources, planner, timeline, reframe_geometry, reframe_path


def create(conn, project_id, tracks, max_step=2, max_acceleration=1, motion_weight=1):
    snapshot = planner.prepare(media_sources.bind(conn,timeline.snapshot(conn,project_id)))
    frames,checked = reframe_geometry.project(snapshot['clips'],tracks)
    path,cost = reframe_path.programme(frames,max_step,max_acceleration,motion_weight)
    payload = dict(version=1,project=snapshot['project'],clips=snapshot['clips'],
        tracks=checked,path=path,cost=cost,width=640,height=360,
        output_width=200,output_height=360,fps=25,
        samples=sum((c['end_ms']-c['start_ms'])*48 for c in snapshot['clips']),
        frames=len(path),settings=dict(max_step=max_step,max_acceleration=max_acceleration,
            motion_weight=motion_weight))
    encoded = json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    with db.write(conn):
        cursor = conn.execute('INSERT INTO reframe_plans (project_id,payload,payload_sha256) '
            'VALUES (?,?,?)',(project_id,encoded,digest))
    return get(conn,cursor.lastrowid)


def get(conn, plan_id):
    row = conn.execute('SELECT * FROM reframe_plans WHERE id=?',(plan_id,)).fetchone()
    if row is None:
        raise ValueError('portrait plan not found')
    if hashlib.sha256(row['payload'].encode()).hexdigest() != row['payload_sha256']:
        raise ValueError('portrait plan checksum mismatch')
    result = json.loads(row['payload'])
    if result.get('version') != 1:
        raise ValueError('unsupported portrait plan version')
    result.update(id=plan_id,payload_sha256=row['payload_sha256'])
    return result


def preview(conn, plan_id, frame):
    plan = get(conn,plan_id)
    if type(frame) is not int or not 0 <= frame < plan['frames']:
        raise ValueError('portrait preview frame is out of range')
    return dict(plan_id=plan_id,revision=plan['project']['revision'],
        **plan['path'][frame],crop_width=200,crop_height=360,cost=plan['cost'])
