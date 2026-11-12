# Studio audio tools

Import a local file in the recording inspector. Select **Solo vocal** for isolated voices or **Instrumental / complete song** for backing. Acapella remains vocal-only. Imports use the timeline cursor and retain the filename. The browser uploads the original compressed file once, without decoding it or expanding it into WAV. The server converts compressed imports to private 44.1 kHz PCM WAV before taking a project database lock; existing valid PCM recordings bypass conversion. Protected, malformed, oversized and over-six-minute inputs are rejected. Original external files on the artist's device are never modified.

A three-minute 44.1 kHz stereo 16-bit WAV is about 31.8 MB, regardless of whether its original MP3 was 2 MB or 7 MB. Sending the original file avoids that upload expansion and avoids the old conversion-download-reupload fallback. Editable audio is still stored as PCM, and the editor downloads it for waveform editing. WAV validation reads bounded blocks instead of duplicating the entire audio in memory. Slow uploads remain locked until the server answers, so a late successful response finishes the import instead of being discarded after two minutes.

Deploy the updated backend and static JavaScript together, run `python manage.py collectstatic --noinput`, and restart the web workers. No database migration is required for this import change. The server needs the existing `imageio-ffmpeg` dependency. A browser still using the older JavaScript will continue sending WAV until its assets refresh.

Open **Audio tools** on a track. Reduce steady hiss, low rumble and optional 50/60 Hz electrical hum; start gently. This cannot reliably erase overlapping speech, loud transients, reverb or distortion. Choose the rumble cutoff carefully for bass voices.

Pitch correction is available for vocal tracks in all three categories. Set the song's key and major/natural-minor/chromatic scale, correction amount and retune speed. It processes a solo voice after recording/import; it is unsuitable for choir mixtures, vocal percussion or live monitoring. WORLD analysis/resynthesis preserves the spectral envelope but can change vocal timbre. Listen before applying, particularly near chunk boundaries on long recordings.

Instrumental extraction is available in Gospel and Secular sessions. It separates the backing from the vocal using Demucs. Confirm permission to reuse the source recording. Preview the output, then use it in this session or save it to the instrumental library. Extracted audio is reused as an audio recording, not an editable piano-roll composition. The stored BPM is the session's declared tempo; it is not automatic tempo/key detection. Vocal bleed and separation artifacts are possible.

Preview with the result player and compare with the original track player. Save existing edits and keep/discard pending takes before applying. Applying adds a separate track with matching timeline/trim/gain and mutes the source, so Save mix, publishing and exports use the processed audio. Unmute the source and mute/remove the processed track to undo. Save mix again after applying. Processing does not publish or consume export allowances.

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

On Ubuntu, schedule daily cleanup with the deployment's actual virtualenv Python and project paths, for example after confirming them on the server:

### Recommended: supervised systemd timer

From the deployed repository with its virtualenv activated, install using the existing application account (replace `ggenre` if the web service uses another account):

```bash
sudo "$(command -v python)" scripts/install_audio_cleanup.py --project "$PWD" --python "$(command -v python)" --user ggenre
```

The installer first previews cleanup using the chosen account and Python, validates the systemd units, installs them, enables the timer and runs cleanup once. The timer runs daily between 03:00 and 03:15 Africa/Harare (01:00 UTC plus jitter), resumes after reboots, catches missed schedules, and prevents overlapping scheduled runs. CPU and memory limits reduce impact on a small Droplet. Logs go to the system journal. It loads the same project `.env` through Django settings; no secrets are copied into unit files.

Use `--preview` to print the unit definitions without changing the server. Verify or disable the installation with:

```bash
systemctl list-timers --all ggenre-audio-cleanup.timer
journalctl -u ggenre-audio-cleanup.service -n 50 --no-pager
sudo systemctl disable --now ggenre-audio-cleanup.timer
```

### Alternative: cron (do not enable both)

```cron
0 3 * * * cd /home/ggenre/ggenre/ggenre && /path/to/venv/bin/python manage.py cleanup_studio_audio --apply >> /var/log/ggenre-audio-cleanup.log 2>&1
```

Use an account with access to private storage and its database; keep the log writable. Guide caches have their own command: `python manage.py cleanup_studio_guides --days 7`. The audio cleanup command does not touch collaboration videos or the extraction model cache. No migration is required. Deploy the updated worker/web code together so all new writes use shared immutable references. Cleanup reclaims temporary/unreferenced storage; it does not impose a quota on active projects.

## Checks

See [REGRESSION_AUDIO_REPORT.md](REGRESSION_AUDIO_REPORT.md) for regression results, reproduced edge cases, and remaining manual acceptance checks.

`python manage.py check_studio_audio`

This downloads the registered official model if needed, verifies its SHA-256 prefix, and runs real extraction on generated audio through the same processing path used by queued jobs. It verifies stereo PCM format, duration and non-silent output without creating artists, projects or library entries. Large model downloads use bounded byte-range requests as a fallback for connections that stall on a single large response.

`python manage.py test studio --noinput`

`node --test scripts/studio-recording-ui.test.cjs scripts/studio-audio.test.cjs`

New tests cover import conversion, malformed input, permission isolation, job limits, option validation, real FFmpeg denoising, original preservation, revision conflicts, reuse of extracted library recordings, and real PyWORLD pitch correction when installed. Run the extraction setup check in each deployment environment. Synthetic fixtures cannot establish separation quality; music listening checks and browser/device visual acceptance remain necessary.

Engine references: [Demucs](https://github.com/facebookresearch/demucs), [PyWORLD](https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder), [FFmpeg audio filters](https://ffmpeg.org/ffmpeg-filters.html).
