# Studio audio tools

Import a local file in the recording inspector. Select **Solo vocal** for isolated voices or **Instrumental / complete song** for backing. Acapella remains vocal-only. Imports use the timeline cursor, retain the filename, and convert to private 44.1 kHz PCM WAV. Browser decoding is tried first; server FFmpeg conversion handles browser codec gaps. Protected, malformed, oversized and over-six-minute inputs are rejected. Original external files on the artist's device are never modified.

Open **Audio tools** on a track. Reduce steady hiss, low rumble and optional 50/60 Hz electrical hum; start gently. This cannot reliably erase overlapping speech, loud transients, reverb or distortion. Choose the rumble cutoff carefully for bass voices.

Pitch correction is available for vocal tracks in all three categories. Set the song's key and major/natural-minor/chromatic scale, correction amount and retune speed. It processes a solo voice after recording/import; it is unsuitable for choir mixtures, vocal percussion or live monitoring. WORLD analysis/resynthesis preserves the spectral envelope but can change vocal timbre. Listen before applying, particularly near chunk boundaries on long recordings.

Instrumental extraction is available in Gospel and Secular sessions. It separates the backing from the vocal using Demucs. Confirm permission to reuse the source recording. Preview the output, then use it in this session or save it to the instrumental library. Extracted audio is reused as an audio recording, not an editable piano-roll composition. The stored BPM is the session's declared tempo; it is not automatic tempo/key detection. Vocal bleed and separation artifacts are possible.

Preview with the result player and compare with the original track player. Save existing edits and keep/discard pending takes before applying. Applying adds a separate track with matching timeline/trim/gain and mutes the source, so Save mix, publishing and exports use the processed audio. Unmute the source and mute/remove the processed track to undo. Save mix again after applying. Processing does not publish or consume export allowances.

## Deployment

For local Windows development, install both requirements files in `.venv`, then use `scripts/start_local.ps1`. The launcher uses the project virtual environment for both Django and the audio worker, checks that the audio engines are installed, and runs the worker for the lifetime of the server. Starting Django alone with `runserver` still requires a separate worker using the same Python executable.

Apply `python manage.py migrate studio`, install `requirements-audio.txt` in the Python environment used by the worker and web process, and run `python manage.py process_studio_audio` as a supervised background service alongside Django. FFmpeg comes from the existing imageio-ffmpeg dependency. PyWORLD needs NumPy/SciPy. Demucs also installs PyTorch/Torchaudio and downloads its model on first use; allow time, disk, memory and model-download access. CPU processing works but can be slow. Missing optional engines return a setup error instead of accepting unusable jobs.

For a batch run use `python manage.py process_studio_audio --once`. If a worker is killed, stop all audio workers before running `--retry-interrupted` to requeue interrupted jobs. Atomic status claiming prevents two workers from intentionally taking the same queued task. Each artist can have two queued/running jobs. Source snapshots/results stay in private Studio storage and require owner authentication. Status polling reconnects after reopening the project and pauses in hidden tabs. Failed jobs can be submitted again.

Private snapshots are retained, including originals of removed tracks. Plan storage retention and disk monitoring before large-scale use. The separation subprocess has a 30-minute limit; use process-level memory/time limits on the supervised worker for production. No public audio hosting or external audio API is used.

## Checks

See [REGRESSION_AUDIO_REPORT.md](REGRESSION_AUDIO_REPORT.md) for regression results, reproduced edge cases, and remaining manual acceptance checks.

`python manage.py check_studio_audio`

This downloads the registered official model if needed, verifies its SHA-256 prefix, and runs real extraction on generated audio through the same processing path used by queued jobs. It verifies stereo PCM format, duration and non-silent output without creating artists, projects or library entries. Large model downloads use bounded byte-range requests as a fallback for connections that stall on a single large response.

`python manage.py test studio --noinput`

`node --test scripts/studio-recording-ui.test.cjs scripts/studio-audio.test.cjs`

New tests cover import conversion, malformed input, permission isolation, job limits, option validation, real FFmpeg denoising, original preservation, revision conflicts, reuse of extracted library recordings, and real PyWORLD pitch correction when installed. Run the extraction setup check in each deployment environment. Synthetic fixtures cannot establish separation quality; music listening checks and browser/device visual acceptance remain necessary.

Engine references: [Demucs](https://github.com/facebookresearch/demucs), [PyWORLD](https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder), [FFmpeg audio filters](https://ffmpeg.org/ffmpeg-filters.html).
