# External extraction pilot (Modal)

This integration is prepared but disabled. No deployment or remote inference was run during implementation. Do not treat a configuration flag as verification of a provider's billing policy.

## Verified account state on 19 November 2026

The signed-in `mcarenahart` Starter workspace showed $1 included compute, $0 used and $0 charged. Its usage limit was $1, set by Modal; the dashboard required adding a payment method to raise it. The banner said adding a payment method unlocks the remainder of the advertised $30/month allowance. No payment method was added and no account setting was changed. The Resource Limits page displayed a concurrent GPU quota of 10, with zero in use; this is an account quota, not a guarantee of a particular GPU's availability.

Keep the account's provider-enforced usage cap within the confirmed free credit balance, with no out-of-pocket spending. If a $0 net spend control becomes available, set and verify it as well. Stop setup if the provider requires paid usage. Do not enable paid Model APIs, a paid plan, paid overflow or additional services for this pilot.

## What the app does

- `STUDIO_EXTRACTION_BACKEND=modal` routes extraction to an authenticated external endpoint. It never falls back to local neural extraction. Other existing audio tools continue on their existing worker.
- The pilot can dispatch only the extraction job named by `STUDIO_REMOTE_TEST_JOB_ID`. All other extraction requests wait. The existing global worker lease and a single Modal GPU container bound concurrency during this test.
- Both activation flags and valid connection settings are required. Default settings do not invoke Modal.
- A durable dispatch marker is saved before submission. Lost acknowledgements or orchestrator restarts do not submit a second paid job automatically. An uncertain or quota-rejected submission pauses external extraction for administrator review.
- Short-lived signed tokens authorize only that job's source, control and result endpoints. Tokens are action-specific, source-bound, expire after one hour, and stop working when the task is cancelled. The external worker receives no database credentials or Django secret key.
- Source and result transfers use bounded buffers and do not pass through the artist's device again. Existing server storage is retained; no object-storage account is needed.
- Returned WAVs are checked for size, format and original duration before they can be applied. Duplicate callbacks reuse the stored result. GPU work checks task status between streaming windows so cancelled or completed requests stop at the next boundary.
- The worker uses an authenticated CPU submission endpoint and a T4 extraction class. It loads the model once per GPU container and can reuse it while the container remains alive. The two-second idle window and 600-second function timeout are conservative pilot settings, not a guarantee of total invoice cost.

## Deploy in this order

1. Back up the database and private media. Deploy the GGenre code, run migrations through 0016, collect static files and restart the existing web/audio services. Configure `STUDIO_EXTRACTION_BACKEND=modal` with remote processing disabled. This queues extraction without running it locally. Existing default `local` installations retain their previous behavior until the backend setting is changed.
2. Verify the live HTTPS origin `https://www.ggenre.com` and the `/studio/remote-audio/...` routes are deployed. The provided worker is deliberately restricted to that exact origin; update both the worker's allowed origin and the server configuration if the production origin changes.
3. After account-access approval, authorize the Modal client in a separate local deployment environment using `requirements-remote-worker.txt` and Modal's normal `python -m modal setup` flow. Client/proxy credentials grant access to compute and must be stored securely, never committed or pasted into chat.
4. Verify the provider's no-charge cap before deploying. Image building, startup, CPU dispatch and GPU work can all consume credits. From the repository root, the deployment command is `python -m modal deploy -m remote_workers.modal_extract`. This command was not executed during implementation. The pinned SDK is 1.6.4; deployment definitions were imported with that SDK locally, without authentication or remote calls.
5. Create a Modal proxy token for the deployed web function. Put its ID/secret and the returned HTTPS `*.modal.run` URL in the server's private environment. Neither endpoint nor API key belongs in frontend JavaScript.
6. Queue a short synthetic or explicitly permitted extraction in GGenre. Use `python manage.py remote_audio_check --list-jobs` to find the selected waiting job ID. Processing itself does not consume a trial download.
7. Configure the selected job and activation flags, then restart the audio worker:

```dotenv
STUDIO_EXTRACTION_BACKEND=modal
STUDIO_PUBLIC_BASE_URL=https://www.ggenre.com
STUDIO_REMOTE_WORKER_URL=https://YOUR-AUTHENTICATED-FUNCTION.modal.run
STUDIO_REMOTE_PROXY_KEY=configure-securely
STUDIO_REMOTE_PROXY_SECRET=configure-securely
STUDIO_REMOTE_TEST_JOB_ID=SELECTED_JOB_ID
STUDIO_REMOTE_BILLING_VERIFIED=True
STUDIO_REMOTE_EXTRACTION_ENABLED=True
```

Run `python manage.py remote_audio_check` first. It reads local configuration only; it neither contacts Modal nor spends credits. The billing-verification flag records an operator decision and does not inspect the provider's account automatically.

8. Let exactly that selected job complete. Disable `STUDIO_REMOTE_EXTRACTION_ENABLED` afterward and restart the worker. Check the returned audio, original duration, application behavior, cold-start time and actual credit usage in Modal. Do not extrapolate a cost per song before measuring.

## Pauses and uncertain submissions

HTTP 402/429 or a missing result triggers a persistent provider pause. Other extraction jobs wait without local fallback. `remote_audio_check --clear-pause` clears that gate only after credits and the previous job have been reviewed; it does not erase dispatch history or make a previously dispatched job run twice. If a definitively failed pilot needs another attempt, cancel/review the old job and select a new job explicitly. Cancel any old active remote work before authorizing another test.

This is a one-job integration pilot, not a completed scalable free-compute service. More concurrent jobs require a measured capacity/budget policy and changes to the pilot restriction. A finite free credit balance cannot guarantee permanent free processing.

## References

- https://modal.com/docs/guide/webhook-proxy-auth
- https://modal.com/docs/guide/lifecycle-functions
- https://modal.com/docs/guide/budgets

## Verification

Automated transport tests cover scoped/expired/cancelled authorization, upload validation, callback idempotence, no local model invocation, uncertain submissions, provider-limit pauses, proxy headers, redirect rejection and the one-job activation gates. All 369 Django tests passed (one platform-dependent symlink skip), including the existing real local extraction regression; all 139 JavaScript tests passed. Migration 0016, system checks and migration consistency checks passed locally. Actual Modal image building, GPU execution and live-server deployment still require authenticated setup and were not performed by these tests.
