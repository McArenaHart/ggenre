# Studio audio tools

Import a local file in the recording inspector. Select **Solo vocal** for isolated voices or **Instrumental / complete song** for backing. Acapella remains vocal-only. Imports use the timeline cursor and retain the filename. The browser uploads the original compressed file once, without decoding it or expanding it into WAV. The server converts compressed imports to private 44.1 kHz PCM WAV before taking a project database lock; existing valid PCM recordings bypass conversion. Protected, malformed, oversized and over-six-minute inputs are rejected. Original external files on the artist's device are never modified.

A three-minute 44.1 kHz stereo 16-bit WAV is about 31.8 MB, regardless of whether its original MP3 was 2 MB or 7 MB. Sending the original file avoids that upload expansion and avoids the old conversion-download-reupload fallback. Editable audio is still stored as PCM, and the editor downloads it for waveform editing. WAV validation reads bounded blocks instead of duplicating the entire audio in memory. Slow uploads remain locked until the server answers, so a late successful response finishes the import instead of being discarded after two minutes.

Deploy the updated backend and static JavaScript together, run `python manage.py collectstatic --noinput`, and restart the web workers. No database migration is required for this import change. The server needs the existing `imageio-ffmpeg` dependency. A browser still using the older JavaScript will continue sending WAV until its assets refresh.

Open **Audio tools** on a track. Reduce steady hiss, low rumble and optional 50/60 Hz electrical hum; start gently. This cannot reliably erase overlapping speech, loud transients, reverb or distortion. Choose the rumble cutoff carefully for bass voices.

Pitch correction is available for vocal tracks in all three categories. Set the song's key and major/natural-minor/chromatic scale, correction amount and retune speed. It processes a solo voice after recording/import; it is unsuitable for choir mixtures, vocal percussion or live monitoring. WORLD analysis/resynthesis preserves the spectral envelope but can change vocal timbre. Listen before applying, particularly near chunk boundaries on long recordings.

Instrumental extraction is available in Gospel and Secular sessions. It separates the backing from the vocal using Demucs. Confirm permission to reuse the source recording. Preview the output, then use it in this session or save it to the instrumental library. Extracted audio is reused as an audio recording, not an editable piano-roll composition. The stored BPM is the session's declared tempo; it is not automatic tempo/key detection. Vocal bleed and separation artifacts are possible.

### Extraction on a small CPU Droplet

Extraction analyzes decoded audio samples, so a small MP3 does not imply a small processing job. CPU deployments default to a fast profile: two-second model windows, 10% overlap and no random-shift augmentation. The engine processes long songs in bounded 30-second windows with one-second crossfades and spools the combined backing to temporary disk. It no longer retains all four stems of an entire song in RAM. Default CPU threads are capped at four and follow the detected CPU count below that cap. Repeated requests for an already queued/running extraction return that job instead of adding duplicate work.

For the current single-vCPU Droplet, use these optional `.env` settings and restart the existing audio worker:

```dotenv
STUDIO_EXTRACTION_DEVICE=cpu
STUDIO_EXTRACTION_PROFILE=fast
STUDIO_EXTRACTION_THREADS=1
```

Fast mode trades analysis context and overlap for reduced CPU/RAM requirements; listen for separation artifacts before relying on it for finished music. `STUDIO_EXTRACTION_PROFILE=balanced` keeps the former per-model analysis context, 25% overlap and one random shift, with the streaming memory bound still applied. A 1 GB machine can still be constrained by the model plus web/database processes. Do not add more workers to speed up a single CPU; that can increase contention and memory pressure.

`STUDIO_EXTRACTION_DEVICE=auto` (the default) uses CUDA when available and CPU otherwise. GPU hosts require a CUDA-enabled PyTorch installation. No paid resources or external audio transfer are configured by this change. The worker logs engine/device/profile/thread count, audio duration, engine runtime, total subprocess runtime and Linux process peak memory. Use these measurements on real songs to assess the Droplet; local short-clip timings do not predict full-song latency or quality. The existing 30-minute job timeout still applies.

Preview with the result player and compare with the original track player. Save existing edits and keep/discard pending takes before applying. Applying adds a separate track with matching timeline/trim/gain and mutes the source, so Save mix, publishing and exports use the processed audio. Unmute the source and mute/remove the processed track to undo. Save mix again after applying. Processing does not publish or consume export allowances.

## Instrumental downloads and trial allowance

Instrumental-only downloads use the same account allowance as Studio mix exports: two trials by default, including downloads before any vocals are layered. This covers composed, extracted and three-part arranged instrumentals. In the library, **Prepare download · uses one trial** creates a downloadable snapshot and spends one remaining trial, just as preparing a Studio export does. The refreshed page shows the remaining shared allowance and its **Download instrumental** link. Downloads of that same saved version do not spend another trial. Saving a changed version gives it a new immutable audio filename and its first download request counts again.

Once the allowance is exhausted, the next version is pending until admin payment approval. Existing allowance overrides, resets and unlimited exports apply to both mixes and instrumentals. Admin review pages and totals include both. Previous approved/free snapshots remain downloadable from the library download history after further edits. Playback, editing and copying an instrumental into a vocal session do not spend trials.

Apply migration `0010_export_instrumental_alter_export_project_and_more` and restart web/audio workers during deployment. Exports now reference exactly one project or instrumental, and file cleanup protects either type of exported snapshot.

## Intro, middle and outro editing

When extraction is ready, choose **Edit intro / middle / outro** in Audio tools. Saved extracted instrumentals also have that action in the instrumental library. Load the waveform, then choose a source range for each of the three parts by dragging its handles or entering precise times. Each part has volume and audition controls. Source ranges can repeat or come from different places; the output always plays intro → middle → outro.

**Preview all three joined** renders a continuous preview with no inserted silence. Select a join crossfade from 0–500 ms (20 ms by default). Crossfades overlap the ends, shortening the total duration slightly and smoothing clicks. Listen and place cuts on matching beats: a crossfade cannot guarantee musical/beat alignment or remove silence already inside a selected range. Each part must be at least 0.1 seconds; the combined result must stay within six minutes.

**Save joined instrumental** sends only range/volume settings to the server, which renders one WAV without rerunning extraction or uploading a browser-generated WAV. The first save creates a library copy. Reopening that copy lets the artist revise all three parts against the preserved original; subsequent saves update the copy with a new immutable audio filename. Existing Studio tracks and exports keep their earlier saved audio. Use the saved instrumental in Studio as one backing track. The retained source is protected from automatic cleanup even after the temporary extraction job expires.

Deploy migration `0009_instrumental_source_audio`, collect static assets and restart both the web workers and the existing audio worker. Stop the old audio worker before deploying so its cleanup cannot overlook the new source-file references. No extra worker is required for arrangement saves. Automated checks exercise real FFmpeg joins, source preservation, owner isolation, revision conflicts and library reuse. The synthetic browser fixture `python scripts/browser-tests/studio-extract-arrange-qa.py` serves only on 127.0.0.1:8765 and never writes to the application database; it verifies handles, volume, preview and persisted UI settings with generated audio.

## Deployment

For local Windows development, install both requirements files in `.venv`, then use `scripts/start_local.ps1`. The launcher uses the project virtual environment for both Django and the audio worker, checks that the audio engines are installed, and runs the worker for the lifetime of the server. Starting Django alone with `runserver` still requires a separate worker using the same Python executable.

Apply `python manage.py migrate studio`, install `requirements-audio.txt` in the Python environment used by the worker and web process, and run `python manage.py process_studio_audio` as a supervised background service alongside Django. FFmpeg comes from the existing imageio-ffmpeg dependency. PyWORLD needs NumPy/SciPy. Demucs also installs PyTorch/Torchaudio and downloads its model on first use; allow time, disk, memory and model-download access. CPU processing works but can be slow. Missing optional engines return a setup error instead of accepting unusable jobs.

For a batch run use `python manage.py process_studio_audio --once`. If a worker is killed, stop all audio workers before running `--retry-interrupted` to requeue interrupted jobs. Atomic status claiming prevents two workers from intentionally taking the same queued task. Each artist can have two queued/running jobs. Source snapshots/results stay in private Studio storage and require owner authentication. Status polling reconnects after reopening the project and pauses in hidden tabs. Failed jobs can be submitted again.

Private audio uses immutable UUID filenames. Processing tasks reference the original track, and applied tracks/library entries reference the processed result; these steps no longer make additional full WAV copies. Database references protect shared files when any one owner record is deleted. The separation subprocess has a 30-minute limit; use process-level memory/time limits on the supervised worker for production. No public audio hosting or external audio API is used.

## Storage cleanup

Preview the cleanup plan (no files or database records change):

```bash
python manage.py cleanup_studio_audio
```

Run cleanup after reviewing the preview:

```bash
python manage.py cleanup_studio_audio --apply
```

Default retention:

- Remove generated WAV files unreferenced by any database file field in private storage, after a seven-day file-age grace period. This reclaims removed-track audio, old unexported/unpublished mixes and abandoned writes.
- Clear temporary source/result references of applied or failed processing tasks older than seven days. Shared audio survives whenever a track, project, instrumental, export, release or another task still uses it.
- Expire unused ready processing results after 30 days. Newly produced results from old/retried tasks get their own grace based on modification time. Artists can regenerate an expired result from the original track.
- Never expire queued/running jobs, active project tracks, current mixes, saved library items, published releases or export snapshots. Do not delete projects based solely on inactivity. Source audio still needed for editing remains stored.

Flags `--orphan-days`, `--job-days`, and `--preview-days` customize those periods; all must be at least one day. A dry run is the default; `--dry-run` is also accepted. `--apply` is required for any mutation. The command only considers generated UUID WAVs directly under `studio_private/audio`, rejects symlinked audio directories, skips symlink files and unknown filenames, and checks database references again before deletion. It reports file count and MiB reclaimed.

### Automatic scheduling inside GGenre

The existing continuous `python manage.py process_studio_audio` worker runs cleanup automatically. No separate cleanup timer, cron entry or installer is required. Apply migration 0008 and restart the existing audio worker during deployment:

```bash
python manage.py migrate studio --noinput
```

On its first startup the worker checks for overdue cleanup immediately. After a successful run, the next cleanup is due at 01:00 UTC (03:00 Africa/Harare). It checks at most once per minute between audio jobs; a long-running extraction can delay cleanup until that job finishes. The schedule survives worker/server restarts, and missed runs execute when a worker returns. The worker must remain running, as it already needs to for extraction, autotune and noise reduction.

A renewable database lease prevents concurrent scheduled runs across workers. Cleanup checks that lease while processing records and immediately before deleting files; a worker that loses ownership stops. A crashed worker's lease expires after ten minutes. Cleanup errors are logged to the audio worker's existing logs and retried in an hour without stopping audio processing. The `StudioMaintenance` record stores next due time, last success and last error. `--once` remains an audio-only batch mode and does not run scheduled maintenance.

Scheduling is enabled by default. Optional `.env` settings: `STUDIO_AUTO_CLEANUP_ENABLED=False` disables it, and `STUDIO_CLEANUP_HOUR_UTC=1` chooses its UTC hour (0–23). Normal uploads/page requests never run cleanup.

If the previous separate timer was installed, disable it once to avoid running both systems:

```bash
sudo systemctl disable --now ggenre-audio-cleanup.timer
```

If that unit was never installed, no timer command is needed. Remove any old audio cleanup cron entry as well. Manual preview/apply commands remain available. Guide caches have their own command: `python manage.py cleanup_studio_guides --days 7`. Audio cleanup does not touch collaboration videos or the extraction model cache. Cleanup reclaims temporary/unreferenced storage; it does not impose a quota on active projects.

## Checks

See [REGRESSION_AUDIO_REPORT.md](REGRESSION_AUDIO_REPORT.md) for regression results, reproduced edge cases, and remaining manual acceptance checks.

`python manage.py check_studio_audio`

`python manage.py check_studio_audio --seconds 32` exercises a real extraction across a streaming window boundary. Test lengths are limited to 1–60 seconds.

Local validation on 13 November 2026: a 32-second generated clip, fast profile and one inference thread, completed in 76.33 seconds including subprocess startup (66.15 seconds inside the engine). The output was non-silent stereo PCM with the exact original frame count. A shorter three-second check took 8.2 engine seconds with four threads, versus 17.57 engine seconds before shortening the model windows. These are single local checks on different settings, not a benchmark of the live Droplet or a guarantee of song quality. Check actual worker timing and Linux memory logs after deployment and listen to a representative song; choose balanced mode if fast-mode artifacts are unacceptable.

This downloads the registered official model if needed, verifies its SHA-256 prefix, and runs real extraction on generated audio through the same processing path used by queued jobs. It verifies stereo PCM format, duration and non-silent output without creating artists, projects or library entries. Large model downloads use bounded byte-range requests as a fallback for connections that stall on a single large response.

`python manage.py test studio --noinput`

`node --test scripts/studio-recording-ui.test.cjs scripts/studio-audio.test.cjs`

New tests cover import conversion, malformed input, permission isolation, job limits, option validation, real FFmpeg denoising, original preservation, revision conflicts, reuse of extracted library recordings, and real PyWORLD pitch correction when installed. Run the extraction setup check in each deployment environment. Synthetic fixtures cannot establish separation quality; music listening checks and browser/device visual acceptance remain necessary.

Engine references: [Demucs](https://github.com/facebookresearch/demucs), [PyWORLD](https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder), [FFmpeg audio filters](https://ffmpeg.org/ffmpeg-filters.html).
