# Portable, bounded Studio processing

The normal Python deployment remains supported on Windows and Linux. Docker is optional. The worker, web app and maintenance schedule still belong to this application; no additional cleanup timer is required.

Waveforms now use small server-generated envelopes instead of decoding every file on page load. Save Mix and Auto Master render in the worker using bounded-memory FFmpeg; the browser submits settings, not a rendered full-song WAV. Completed extractions reuse their immutable result. Reusing a library instrumental pins the same immutable file instead of creating another WAV. Retained browser decode caches are capped at 128 MiB; active recording and local audition still need their active audio buffers, so that cache cap is not a total browser-memory guarantee.

## Existing deployment

Stop audio workers for the deployment. Back up the database and private media together. Install the existing requirements, run `python manage.py migrate --noinput`, collect static files and restart the existing web/worker services. Do not run a second worker against older application code during migrations. Migration 0014 gives legacy interrupted jobs an expired lease so the new worker can recover them.

Keep the default storage location for existing installs. To move it, copy the complete private directory with filenames unchanged, verify the copy, then point **both** web and worker at the same absolute `STUDIO_STORAGE_ROOT`. Keep the old copy until a restore check succeeds. Configure database credentials through the environment. `STUDIO_MODEL_ROOT` optionally relocates the official model cache, and the standard `TMPDIR`/`TEMP` setting controls temporary files. A machine move must include the database, private media, and environment; the model cache can be copied to avoid downloading it again.

Suggested small-server settings are in `.env.example`: CPU extraction, one inference thread, fast profile, six-second streaming windows, and one active heavy job across workers. An expiring database lease prevents overlapping model loads when duplicate workers are started. A heartbeat renews ownership; expired interrupted jobs retry at most twice. Extraction cancellation kills its subprocess within the polling interval. A synchronous FFmpeg/tuning step may finish its current step before stopping, but cancelled work cannot replace a saved result.

Neural extraction still loads a substantial model. Smaller windows bound stem buffers; they do not make that model fit every 1 GB installation alongside a database and web server. Measure real process peak memory with `python manage.py check_studio_audio --seconds 32` and a representative song before changing capacity. This release does not promise a particular production speed or quality. Use balanced extraction only when resources and listening tests justify it.

## Storage policy

`STUDIO_ARTIST_STORAGE_MIB` defaults to 1024 MiB per artist; set 0 to disable the account cap. Existing referenced files are included without copying them or rewriting existing projects. New files have an accounting record; shared filenames count once per artist. Removing an item does not free physical storage immediately: trash and orphan retention protect recovery. Over-limit accounts keep playback and existing downloads; new files are refused. `STUDIO_MIN_FREE_MIB` defaults to 256 MiB reserved on both media and temporary volumes. Account storage and the reserve are configurable deployment policy, not subscription entitlements.

Removed tracks remain recoverable for seven days. Daily in-worker cleanup purges expired removed tracks and later reclaims unreferenced WAVs using the existing orphan grace period. Saved exports/releases retain their audio references. The cleaner removes corresponding accounting rows when deleting an orphan. Collaboration videos contribute to quota, but automatic video retention is not introduced by this release.

## Optional container worker

`Dockerfile.studio` has a light `web` target and a CPU-only `worker` target. `compose.studio.yml` runs only the worker for an existing installation. Build with Docker Compose, set `STUDIO_HOST_AUDIO` to the existing absolute private-media directory, then run `docker compose -f compose.studio.yml up -d --build`. Stop the original worker first. The mounted folder must be writable by the container's studio user. The database hostname must be reachable from inside the container; `localhost` means the container itself. Named volumes retain the model cache and temporary workspace. SQLite deployments additionally need a shared persistent database file and explicit settings; the provided Compose example assumes a reachable database service configured through `.env`.

The Compose file caps CPU use at one core by default. It does not provision a database, reverse proxy, TLS or additional hardware. Existing HTTPS/authentication and private-file protection must remain in place. Container builds were not verified unless explicitly recorded in the release test report.

The provided CPU image targets conventional Linux CPU deployments. Do not assume an untested CPU architecture or GPU build uses the same binary packages. The core web image does not include neural audio dependencies; the worker target does. For a split-image installation, run `check_studio_audio` on the worker first, then configure `STUDIO_REMOTE_AUDIO_ENGINES=tune,separate` on the web host. These explicitly enabled remote engines are offered only while a shared-database worker heartbeat is recent. Both hosts must share the database and private storage; this setting does not send audio to an external service or bypass ownership checks. Local setup checks continue checking the actual installed packages.

## Health and release checks

`python manage.py studio_health` reports worker age, queued/running/stale tasks, free disk and cleanup success. Administrators can read the same information at `/studio/health/`. No audio or credential data is exposed. A missing or old worker heartbeat needs investigation even when the website still loads.

Run the Django and JavaScript regression suites and check real extraction. Test recording on physical iPhone/Android devices and listen to section transitions with real music. Restore a database/private-media backup in an isolated location before treating the backup policy as verified. No production deployment or backup restoration is implied by local automated tests.
