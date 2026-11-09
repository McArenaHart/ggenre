"""Bounded, local video/audio composition. Never accepts remote input URLs."""
import math
import re
import subprocess
from pathlib import Path

from django.core.exceptions import ValidationError

MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_SECONDS = 300


def run_ffmpeg(arguments, timeout=120):
    try:
        import imageio_ffmpeg
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-y", *arguments],
            capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (ImportError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise ValidationError("Video processing is unavailable or took too long. Please try again.") from exc
    if result.returncode:
        raise ValidationError("This video could not be processed. Use an uploaded MP4 with an audio track.")
    return result.stderr.decode("utf-8", errors="replace")


def copy_source(content, destination):
    source = content.video_collaboration.video if hasattr(content, "video_collaboration") else content.file
    if not source or source.size > MAX_VIDEO_BYTES:
        raise ValidationError("Collaboration videos must be under 50 MB.")
    with source.open("rb") as stream, open(destination, "wb") as output:
        total = 0
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_VIDEO_BYTES:
                raise ValidationError("Collaboration videos must be under 50 MB.")
            output.write(chunk)


def inspect_video(path):
    info = run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(path), "-t", "0", "-f", "null", "-"], timeout=20)
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info)
    duration = sum(float(value) * factor for value, factor in zip(match.groups(), (3600, 60, 1))) if match else 0
    if not 0 < duration <= MAX_SECONDS or "Video:" not in info or "Audio:" not in info:
        raise ValidationError("Choose a video with sound, no longer than five minutes.")
    return duration


def extract_audio(source, output):
    inspect_video(source)
    run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "44100", "-t", "300", str(output)])


def render_video(source, vocal, output, original_gain=1, vocal_gain=1, shift_ms=0):
    duration = inspect_video(source)
    if not all(math.isfinite(value) for value in (original_gain, vocal_gain, shift_ms)) or not 0 <= original_gain <= 2 or not 0 <= vocal_gain <= 2 or not -1000 <= shift_ms <= 1000:
        raise ValidationError("Check volumes and vocal alignment.")
    shift = f"adelay={int(shift_ms)}:all=1" if shift_ms >= 0 else f"atrim=start={-shift_ms / 1000},asetpts=PTS-STARTPTS"
    filters = f"[0:a:0]volume={original_gain}[base];[1:a:0]{shift},volume={vocal_gain}[voice];[base][voice]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95:latency=1[mix]"
    run_ffmpeg([
        "-protocol_whitelist", "file,pipe", "-i", str(source), "-protocol_whitelist", "file,pipe", "-i", str(vocal),
        "-filter_complex", filters, "-map", "0:v:0", "-map", "[mix]", "-vf", "scale='min(1280,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "2",
        "-map_metadata", "-1", "-map_chapters", "-1", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-t", str(duration), "-movflags", "+faststart", str(output),
    ])
    if Path(output).stat().st_size > MAX_VIDEO_BYTES:
        raise ValidationError("The combined video is too large. Try a shorter source video.")
