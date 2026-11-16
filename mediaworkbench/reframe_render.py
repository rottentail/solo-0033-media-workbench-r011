"""Bounded-memory portrait delivery from a frozen whole-programme path."""
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import subprocess
import threading
import zlib
from . import audio_signal, planner, media_sources, reframe_plan, transition_signal
from .assets import fingerprint
from .tools import binary, run


def materialize(plan, directory, stack):
    pictures, audio = [], []
    for index,clip in enumerate(plan['clips']):
        path = directory/f'picture-{index}.zrgb'
        offsets = []
        arguments = ['-v','error','-threads','1','-filter_threads','1',
            '-ss',str(clip['start_ms']/1000),'-i',clip['path'],
            '-t',str((clip['end_ms']-clip['start_ms'])/1000),'-an','-vf',
            'setpts=PTS-STARTPTS,scale=640:360:force_original_aspect_ratio=decrease,'
            'pad=640:360:(ow-iw)/2:(oh-ih)/2,fps=25,setsar=1',
            '-pix_fmt','rgb24','-f','rawvideo','-']
        with tempfile.TemporaryFile() as errors, path.open('wb') as output:
            with subprocess.Popen([binary('ffmpeg'),*arguments],stdout=subprocess.PIPE,stderr=errors) as process:
                timer = threading.Timer(120,process.kill)
                timer.start()
                try:
                    while True:
                        raw = process.stdout.read(640*360*3)
                        if not raw:
                            break
                        if len(raw) != 640*360*3:
                            raise ValueError('portrait decoder returned an incomplete picture')
                        encoded = zlib.compress(raw,1)
                        offsets.append((output.tell(),len(encoded)))
                        output.write(encoded)
                    if process.wait():
                        errors.seek(0)
                        raise ValueError(errors.read().decode('utf-8','replace')[-4000:])
                finally:
                    timer.cancel()
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        if not offsets:
            raise ValueError('portrait source has no complete pictures')
        pictures.append(dict(handle=stack.enter_context(path.open('rb')),offsets=offsets,frames=len(offsets)))
        pcm = stack.enter_context(audio_signal.materialized(clip))
        audio.append(stack.enter_context(pcm.open('rb')))
    return pictures,audio


def crop(raw, x):
    if len(raw) != 640*360*3:
        raise ValueError('portrait source picture was truncated')
    result = bytearray()
    for row in range(360):
        start = (row*640+x)*3
        result.extend(raw[start:start+200*3])
    return result


def _request_frame(plan, requested):
    count = len(plan['path'])
    if not count:
        raise ValueError('portrait plan contains no pictures')
    selected = requested % count
    frame = dict(plan['path'][selected])
    source_index = frame['occurrence']
    return source_index,frame


def pictures(plan, sources, first=0, stop=None, block_frames=17):
    if type(block_frames) is not int or not 1 <= block_frames <= 128:
        raise ValueError('invalid portrait delivery block size')
    stop = plan['frames'] if stop is None else stop
    for begin in range(first,stop,block_frames):
        request_length = min(block_frames,stop-begin)
        for local_index in range(request_length):
            source_index,frame = _request_frame(plan,local_index)
            source = sources[source_index]
            picture_index = min(int(frame['local_ms']//40),source['frames']-1)
            if picture_index < 0:
                raise ValueError('portrait source frame is negative')
            offset,length = source['offsets'][picture_index]
            source['handle'].seek(offset)
            packed = source['handle'].read(length)
            if len(packed) != length:
                raise ValueError('portrait picture storage was truncated')
            raw = zlib.decompress(packed)
            yield crop(raw,frame['x'])


def render(conn, plan_id, destination, first=0, count=None, block_frames=17):
    plan = media_sources.bind(conn,reframe_plan.get(conn,plan_id))
    planner.verify_sources(plan)
    count = plan['frames']-first if count is None else count
    if (type(first) is not int or type(count) is not int or first < 0
            or count <= 0 or first+count > plan['frames']):
        raise ValueError('portrait delivery slice is out of range')
    target = Path(destination).expanduser().absolute()
    target = target.parent.resolve()/target.name
    if os.path.lexists(target) or not target.parent.is_dir():
        raise ValueError('portrait destination exists or its directory is missing')
    with ExitStack() as stack:
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory(
            prefix='.portrait-',dir=target.parent)))
        video,audio = materialize(plan,directory,stack)
        raw = directory/'programme.rgb'
        with raw.open('wb') as handle:
            for frame in pictures(plan,video,first,first+count,block_frames):
                handle.write(frame)
        pcm = directory/'programme.pcm'
        # Concatenation retains occurrence-local gain and exact clip durations.
        with pcm.open('wb') as handle:
            for clip,source in zip(plan['clips'],audio):
                remaining = (clip['end_ms']-clip['start_ms'])*48
                while remaining:
                    length = min(4096,remaining)
                    block = audio_signal.read_frames(source,length)
                    block.extend([0.0]*(length*2-len(block)))
                    handle.write(transition_signal.pcm16([v*clip['gain'] for v in block]))
                    remaining -= length
        planner.verify_sources(plan)
        output = directory/'portrait.mp4'
        run('ffmpeg',['-v','error','-y','-threads','1','-filter_threads','1',
            '-f','rawvideo','-pix_fmt','rgb24','-s','200x360','-r','25','-i',str(raw),
            '-ss',str(first/25),'-f','s16le','-ar','48000','-ac','2','-i',str(pcm),
            '-t',str(count/25),'-c:v','libx264','-threads','1','-crf','12',
            '-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(output)])
        digest = fingerprint(output)
        with output.open('rb') as handle:
            os.fsync(handle.fileno())
        os.link(output,target)
    return dict(plan_id=plan_id,revision=plan['project']['revision'],frames=count,
        first=first,path=str(target),sha256=digest,width=200,height=360)
