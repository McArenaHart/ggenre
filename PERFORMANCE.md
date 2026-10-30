# Performance improvements — 30 October 2026

The pass targets repeated work in shared feed/post reads, the header/chat widgets and collaboration reference-audio preparation. Page layout, published-content filtering/order, moderation, chat eligibility, recording, export allowances and polling intervals remain in place. No whole-page caching or cross-user response caching was added.

## Measured read workload

An isolated copy of the preview SQLite database was populated with 50 approved posts, 10 artists, 10 fans, five votes and eleven viewers per post, 30 comments on one post, and 20 allowed peer conversations. Templates were warmed before profiling requests with Django CaptureQueriesContext. Main artist data was not used for load fixtures.

| Request | Queries before | Queries after |
| --- | ---: | ---: |
| Feed, one post | 37 | 14 |
| Feed, ten posts | 46 | 14 |
| Feed, fifty posts | 86 | 14 |
| Post with thirty comments | 148 | 31 |

Query counts include authentication/header work. These are local read benchmarks, not a production concurrency or mobile-network load test. Local response timings vary with machine load; the stable result is that feed query count no longer rises per post and comment authors no longer add per-comment queries. A repeated eight-second collaboration guide request fell from about 211 ms to about 41 ms in the local cached run; first-time preparation still performs extraction, and network transfer cost is unchanged.

## Changes

- Feed/recommendation card counts use indexed scalar count subqueries, avoiding one viewer-count query per card and loading every Vote object. Separate viewer/vote counts prevent join multiplication. Counts are refreshed for each queryset/request; live view tracking refreshes its current instance after adding a viewer.
- Comment authors and post media/creator relations load in bulk. Interest tags use their existing prefetch rather than issuing a names query per viewed post. Recommendation ranking and source approval/visibility conditions are unchanged.
- Header peer unread totals use a single SQL aggregation with active/not-suspended/non-admin participant and approved/unexpired chat conditions. Chat authorization functions themselves are unchanged. Admin unread summation also runs in SQL.
- Two additive indexes match feed ordering and per-post comment ordering. SQLite EXPLAIN changed from temporary ordering B-trees to content_feed_order_idx and content_comment_time_idx. Migration content.0034 was applied after a main-database backup.
- Prepared guide WAV files are stored privately under studio_private/guide_cache. The key includes source storage location, name, size and modification time. Every request still checks artist/source collaboration access before opening a cache entry. Changed files receive a new key. Atomic writes prevent partial cache reads, and unsupported/unwritable caches fall back to normal extraction. Private responses retain no-store. No user vocal takes, rendered previews or exports are stored in this cache.
- Badge/contact/mission polling shares an in-flight request instead of stacking another on a slow connection. Existing intervals, payloads, errors/retries and WebSocket heartbeat/message behavior remain unchanged. Updated script version URLs are included on both base and direct-chat pages. Direct chat loads each controller once instead of loading a second copy through the base template; this also preserves the original chat-root cleanup registry.

## Maintenance and validation

Remove old generated guides periodically when appropriate for staging/production disk capacity:

```text
python manage.py cleanup_studio_guides --days 7 --dry-run
python manage.py cleanup_studio_guides --days 7
```

The command only targets hash-named generated WAVs and abandoned guide temporary files in the configured guide-cache directory; it never recurses into source/preview folders. The Django setting STUDIO_GUIDE_CACHE_DIR can override the default directory. No recurring job was created automatically.

Targeted tests cover query growth (one versus twenty-five feed entries; one versus thirty comments), accurate unmultipled viewer/vote counts, fresh counts after reads/writes, both sides of unread chat counts, disabled/expired peers, cached bytes, source changes, permission revocation, read-only cache fallback, cleanup safety and overlapping polling/retry behavior. Browser walkthrough checks the shared feed, credited post and collaboration recording entry without activating a microphone. All 246 Django tests across Studio, content, users and chat passed, plus all 113 JavaScript checks. The full disposable-database run used a test-process-only fast password hasher; separate login and registration tests also passed with the normal app password hasher. No production password setting changed. Three pre-existing admin tests expected copy no longer present in unchanged templates; those assertions now check the real review navigation/form action URLs instead, retaining approval/rejection behavior checks.

Final local median timings: feed with fifty posts 202.94 → 101.89 ms; thirty-comment post 236.64 → 144.71 ms; warmed eight-second guide 210.66 → 40.69 ms. These medians are machine/workload-dependent, not production latency guarantees. The feed remained at fourteen queries from one through fifty posts.

Local evidence is in .local-backups/performance-before.json, performance-final.json and query-plan-before.txt/query-plan-after.txt. Timings should be remeasured with realistic content volume, concurrent users, production database/storage and mobile network conditions before a large rollout.
