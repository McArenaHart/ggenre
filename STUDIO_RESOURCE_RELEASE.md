# Studio resource and portability release — 13 November 2026

This release implements the resource, recovery and accounting priorities from the studio review. It is not a claim that every proposed editing feature or every production validation task is complete.

## Delivered

- Small server waveform envelopes replace full-track browser decoding just to display the timeline. Original-track and processed preview players defer audio loading until requested. Retained decoded browser caches are bounded at 128 MiB; active playback/recording buffers are separate.
- Save Mix and Auto Master submit settings to the same worker queue. FFmpeg renders immutable input snapshots with one filter thread, without client full-song rendering and re-upload. Reopening a project offers an earlier unfinished render; applying refuses stale project revisions.
- Fast extraction defaults to one inference thread and six-second streaming hops with one-second joins. Completed extraction results are reused. A global database lease prevents multiple worker processes from loading models concurrently against the same database. Balanced and device overrides remain configurable.
- Processing reads immutable local source files directly rather than copying them into temporary directories. Other storage implementations retain a bounded-copy fallback. Library reuse pins the existing immutable WAV instead of writing another copy; library edits still create a new filename and cannot change an existing session's audio.
- Worker leases, heartbeats and bounded attempts recover interrupted jobs automatically. Artists can cancel queued/running tasks. Extraction cancellation stops its subprocess; other engines stop after their current step and cannot publish a cancelled result.
- One shared export service reuses free/approved/pending entitlements for the same immutable mix or instrumental version. Repeated requests no longer spend extra trials. The existing shared default two-trial policy remains.
- Upload request keys handle a lost success response safely. Imports reuse their uncertain request key when the same file is selected again; recorded takes retain their key in recovery data. The UI distinguishes byte-transfer progress from server preparation. Converted imports spool to disk rather than reading the entire prepared WAV into another memory buffer.
- Configurable per-artist storage limits and disk reserves refuse new writes before exhausting storage. Accounting includes legacy references and shared filenames; cleanup removes reclaimed file accounting. Defaults: 1024 MiB per artist, 256 MiB reserved on media and temporary storage; account cap 0 disables the account limit.
- Timeline/mixer undo and redo, seven-day recovery for removed tracks, section-editor local recovery, authenticated byte-range audio delivery, and an administrator health screen/command are included. Cleanup remains scheduled inside the audio worker.
- Configurable media/model/temp paths, environment examples, a lightweight web image, optional CPU-worker image, Compose configuration and deployment instructions support moving the app between installations. A configured lightweight web host can queue remote engines only while the shared worker heartbeat is recent.

## Extraction-window observations

One generated 32-second stereo clip, local Windows CPU, fast profile, one inference thread. Both runs produced non-silent stereo PCM with the original duration. These observations preceded the final direct-file optimization; they are not controlled production benchmarks or subjective music-quality results.

| Streaming hop | Engine time | Entire subprocess | Peak working set |
| --- | ---: | ---: | ---: |
| Previous 30 seconds | 57.24 s | 62.22 s | 608.5 MiB |
| New 6 seconds | 53.62 s | 59.35 s | 565.6 MiB |

Observed total process-memory improvement was about 7%, not the much larger percentage implied by comparing stem-window sizes alone. The neural model and libraries still occupy substantial memory. Avoiding unnecessary decoding, repeated extraction, duplicate WAVs and temporary source copies provides additional savings outside that comparison. A 1 GB Droplet still needs its web/database/worker combination measured on representative real songs.

## Validation and rollout

Final verification: 356 Django tests passed in 38.943 seconds, including real extraction, with one platform-dependent symlink test skipped. All 138 JavaScript tests passed. Coverage includes render timing and revision protection, immutable input pinning without local copies, expired leases, cancellation, remote worker capability checks, shared storage accounting, disk admission, trash/cleanup protection, byte ranges, ownership, request retries and export allowance reuse.

Local migrations through 0015 apply successfully and system/migration checks pass. Browser verification used a loopback-only synthetic fixture with no application database writes: waveform display, volume undo/redo, queued saving and mastering preview were exercised. Evidence: `.local-backups/portable-studio-qa.jpg` (local ignored artifact).

The optional Compose configuration parses successfully. Docker is not installed in this workspace, so image builds and container execution were not verified. Neither physical iPhone/Android recording, human listening tests, backup restoration nor production deployment was performed. Existing SSH authorization to the production server is unavailable; pushing code does not establish that the live app has been updated.

Deploy web code and collected static assets together, apply migrations, then restart the existing web and audio worker services. Stop old audio workers during this upgrade. Back up the database and private media together first. See [STUDIO_PORTABILITY.md](STUDIO_PORTABILITY.md) for paths, shared storage, quotas, worker settings and optional containers.

## Remaining review items

Split/duplicate clips, beat/bar snapping, boundary suggestions, looped selections, consistent solo/rename controls across categories, server autosave across devices, project/library trash, compressed retained sources, automatic video retention and level-matched comparison/loudness reporting remain separate work. Main recording/local audition still decodes its active audio, so the cache bound is not a total memory cap. This release prioritizes the requested resource consumption and portable processing baseline.
