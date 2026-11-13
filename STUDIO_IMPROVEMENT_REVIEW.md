# Mini studio improvement review

Reviewed 13 November 2026 against the current local code. This is a code and existing-test-evidence review, not a live-server performance or acoustic-quality certification. No application behavior was changed in this review.

## What already works as a foundation

Private owner-controlled projects; recording and take review; original-file imports; waveform move/trim; track mute and gain; browser recovery copies; composition and reusable instrumentals; queued extraction, pitch correction and noise reduction; three-section extracted-instrumental arranging with crossfades; saved mix snapshots; moderation; shared instrumental/mix download allowance; and automatic orphan cleanup within the audio worker.

Existing local regression logs report 338 Django tests passing with two skips and 135 JavaScript tests passing. These were not rerun for this document. Physical-device recording, subjective music quality, live resource use and backup restoration remain separate validation needs.

## One coherent stabilization release

### 1. Make every paid or trial export request safe to repeat — highest priority

Evidence: `studio/views.py:export` consumes a free allowance before checking for an existing pending export, and does not reuse an existing free/approved export for the same mix file. `studio/instrumentals.py:request_download` already reuses free/approved/pending snapshots. Repeating the project export request can therefore spend another trial for an unchanged mix.

Use one shared export service for both sources. Reuse the same immutable version, serialize concurrent requests and support a request key. Clearly show the remaining allowance before confirmation. A newly saved audio version can count as a new export; downloading an existing eligible export should stay free.

Acceptance: two simultaneous requests for one unchanged version create one entitlement and consume one trial; mixed instrumental/vocal exports share the same allowance; rejected/pending/approved paths remain consistent.

### 2. Recover interrupted audio jobs automatically — highest priority

Evidence: `AudioJob` stores status and creation time but no worker lease, heartbeat, attempt count or completion time. The worker leaves interrupted jobs running until an administrator uses `--retry-interrupted`. The two-pending-job allowance can then block an artist indefinitely.

Add expiring worker ownership, bounded retries for transient failures, cancellation, timestamps and actionable error categories. Persist the current task so artists can leave and return. Show queue position and real processing stages; display estimates only when supported by measurements. Keep expensive inference concurrency at one initially on the current Droplet.

Acceptance: terminate a worker mid-job, restart it and recover automatically without duplicate results; cancel safely; exhausted attempts leave a clear retry option; one artist cannot monopolize all available processing.

### 3. Bound storage growth without deleting saved work — highest priority

Evidence: cleanup expires old temporary job references and removes unreferenced UUID WAV files. It intentionally retains files referenced by projects, instrumentals, exports and releases. It does not impose artist byte quotas or clean collaboration video files.

Track actual stored bytes, reserve capacity before expensive work, expose artist usage and enforce configurable account limits. Account for shared file references so reuse is not billed repeatedly. Add project/library deletion with trash and a recovery period, then reclaim only files with no remaining references. Include temporary files and collaboration videos in appropriate retention policies. Add low-disk admission checks and administrator alerts. Never silently shorten or delete an active song to save space.

At 44.1 kHz, stereo 16-bit PCM, six minutes is about 60.6 MiB per WAV; twelve distinct full-length tracks are about 727 MiB before mixes, results and backups. Upload size alone does not represent eventual storage cost.

Evaluate lossless FLAC for retained audio after measuring compatibility, disk savings and conversion cost. Use compressed audition copies where useful; preserve a source of export quality. Moving files to object storage is a later scale decision and does not replace quotas.

Acceptance: shared files survive deletion of one reference; trash restores correctly; a full disk produces a useful error before processing; cleanup cannot remove saved or paid snapshots.

### 4. Reduce phone memory use and repeated transfers — high priority

Evidence: `studio.js:load` decodes whole tracks and caches them; `mix` loads active tracks concurrently, renders a full stereo AudioBuffer and creates another WAV buffer. Six minutes of stereo float32 audio is about 121 MiB per decoded track. Twelve such tracks alone approach 1.42 GiB, excluding rendering and browser overhead. This is a worst-case calculation, not a measured live usage figure.

Separate lightweight audition from final rendering. Generate reusable waveform peaks and compressed audition assets; load only needed audio and release unused buffers. Measure a track-budget policy for phones. Queue final server rendering rather than rendering every full mix on the phone. Reuse an existing server mix for mastering instead of uploading a client-rendered mix again. Move expensive mastering/arrangement rendering out of web requests where measurements justify it.

The normal private audio helper currently streams a full FileResponse without implementing byte ranges. Add and test authenticated range-capable delivery, preferably delegated to the reverse proxy, before relying on efficient seeking. Keep all alternate delivery paths private.

Acceptance: representative long projects remain usable on physical phones; seeking does not redownload an entire file; finalized mixes match timeline settings; exports never fall back to low-quality audition files.

### 5. Finish the editing safety tools — high priority

The main waveform editor supports moving, trimming and zooming, but lacks an integrated undo/redo history. Deleting a track saves immediately and reloads. Composition undo does not provide undo for the main audio timeline.

Add undo/redo for timeline and mixer edits, reversible deletion, duplicate/split, short edge fades, looped selection and optional beat/bar snapping. Offer solo and renaming consistently across categories. Extend local recovery to the extracted-instrumental editor. Distinguish local recovery from saved server work; use revisions for server autosave and conflict handling.

For intro/middle/outro cuts, provide beat-grid assistance and boundary audition. Crossfades prevent abrupt joins but do not guarantee musical timing. Suggest cut points as editable guidance, with the artist retaining control.

Acceptance: edits and undo reproduce the same timeline; clips remain aligned after saving; reload recovery is explicit; section transitions are checked with real music as well as synthetic samples.

### 6. Make saving and uploading resilient — high priority

Original-file upload already avoids browser WAV expansion. The remaining request waits for upload and server preparation together, with a delayed generic message. A lost response can leave the user uncertain whether saving succeeded.

Add upload progress and distinct uploading/preparing/ready states. Assign a client request key so retrying can find an already saved result. Preserve the original file or take until acknowledgement. Consider resumable uploads only after slow-network measurements show a need; they add complexity and do not speed up inference.

Acceptance: disconnect after the server commits, retry and receive the existing track; interrupt a transfer without losing the take; stale tabs cannot overwrite newer edits.

### 7. Surface sound quality and operational health — release gate

Keep the original recording and provide level-matched before/after audition for tuning, denoise and mastering. Explain that pitch correction needs a suitable key and an individual vocal, and that extraction quality depends on the source. Add output peak/loudness reporting and practical presets before adding more effects. Validate fast extraction settings on real music; speed alone is insufficient.

Provide an administrator view for worker heartbeat, queue age, processing time versus song length, failure categories, free disk and cleanup last success. Cleanup remains scheduled inside the app worker as requested; the view must reveal when that worker is down. Verify database plus private-media backup and restoration, deploy migrations/static assets together, and document rollback. Test real recording permissions, Bluetooth/headphone latency and interruption recovery on iPhone Safari and Android Chrome.

Acceptance: restore an isolated backup successfully; detect a stopped worker; exercise recording/import → process → arrange → layer → save → download/publish on target devices. Rerun privacy, ownership, export-concurrency, cleanup and existing app regression tests.

## Scope and order

Implement 1–3 first, then 4–6, and validate 7 across the release. Prefer additive migrations and small reviewable commits, followed by one coordinated production rollout. Keep account limits and retention periods configurable rather than hard-coding unagreed commercial policy.

Defer real-time autotune, large plugin racks, simultaneous multiplayer editing and infrastructure migration until measurements or artist feedback justify them. These do not resolve the current reliability and capacity gaps.

A single planned release can establish this baseline; browser changes, artist feedback and production load will still require ongoing maintenance. No code changes, production deployment or new performance claims are implied by this review.
