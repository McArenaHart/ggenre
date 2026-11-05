# Audio regression report — 5 November 2026

## Result

Automated application regression: **PASS**. The final run completed **272 Django tests and 121 JavaScript tests**, with **zero failures and zero skips**. Real Demucs extraction was enabled for the full Django run.

Browser visual acceptance and human listening acceptance remain **unverified**. Both available computer/browser automation runtimes failed to initialize with `failed to write kernel assets: The system cannot find the path specified`. Automated audio checks verify format, duration, pitch movement, hum attenuation and workflow correctness; they do not establish subjective music quality or device microphone behavior.

## Coverage

- Real MP3, M4A, FLAC and OGG conversion to editable 44.1 kHz stereo PCM WAV; malformed and over-five-minute input rejection.
- Import names, vocal/backing choice, cursor position, existing edits, conversion fallback, failed-import retry and Acapella vocal-only behavior.
- Real noise reduction: attenuation of a known 50 Hz hum while preserving a 220 Hz voice tone.
- Real pitch correction: correction of a detuned tone, preserved duration, and queue/worker/apply flows in Gospel, Acapella and Secular.
- Real extraction: queue → worker → private preview → apply → save mix → export. The original file hash remains unchanged; exported bytes match the processed mix.
- Extracted library storage and reuse in a new song; protection against accidental piano-roll overwrite.
- Original preservation, mute/copy behavior, timing/trim/gain preservation, stale revision handling, track limits, queue limits, failures/retry and reconnecting to pending jobs.
- Artist ownership, fan/anonymous access denial, CSRF protection and private playback caching.
- Existing chat, mission, OTP/voting, content, subscriptions, collaboration, recording, recovery, timeline, orientation, composition, keyboard/MIDI and export regression suites.

## Fixes found during regression

1. Extracted audio could be opened through a composer URL expecting piano-roll metadata. It now redirects to the library, and composer saves cannot overwrite extracted recordings.
2. Processing a rhythm preset could create another preset track without its preset metadata. The processed copy is now a backing audio track; the original preset remains intact.
3. An older asynchronous status response could replace the preview of a newer task. Responses are now checked against the current job before updating the interface. A test reproduced the failure before the fix and passes afterward.
4. Per-artist queue checks now lock the artist row, covering requests across different projects. Engine availability checks include prerequisite packages, rather than only the top-level engine package.

## Reproduce

PowerShell, from the repository root:

```powershell
$env:STUDIO_TEST_EXTRACTION = '1'
python manage.py test --noinput --verbosity 2 --settings=ggenre.test_settings
Remove-Item Env:STUDIO_TEST_EXTRACTION
$jsTests = @(rg --files scripts -g '*.test.cjs')
node --test @jsTests
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --check
git diff --check
```

The dedicated test settings use an isolated in-memory SQLite database, in-memory channels, local email and fast test password hashing. Production settings are unchanged. Install `requirements-audio.txt` and cache the official model with `python manage.py check_studio_audio` before enabling the real extraction test.

The final logs are local, ignored Git files: `regression-final-django.log`, `regression-final-django-error.log` and `regression-final-javascript.log`. Django's error log includes expected 400/403/404/409/503 responses from negative tests; the final test summary is `OK`.

## Environment and commit notes

Django checks, Python/JavaScript syntax checks, migration consistency, applied migrations and Git whitespace checks passed.

`python -m pip check` reports an existing shared-environment conflict: `numba 0.61.2` requires `numpy<2.3,>=1.24`, while installed NumPy is `2.4.4`. NumPy 2.4.4 was present before the audio-engine installation; Numba is not a declared application/audio dependency. No unrelated shared packages were downgraded. An invalid `~zdata` distribution warning is also present in that Python installation.

Do not include the pre-existing tracked `__pycache__` changes or unrelated `PROJECT_MAP_AND_ROADMAP.md` in the audio-feature commit. No files were staged, committed or pushed during verification.
