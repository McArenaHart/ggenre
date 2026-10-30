# Vocal video collaborations — V1

GGenre artists can add a vocal layer to an uploaded MP4 and publish the resulting combined video as a new GGenre post. The source image/video is retained. This version does not record a second camera view or provide split-screen video.

## Creator and collaborator journey

1. On upload, choose Open this video to vocal collaborations. Existing MP4 posts have an Open to vocal collaborations button on their detail page. Opening is explicit; existing content defaults closed.
2. An approved, visible, open video offers Add your voice on its post and in the feed for artist accounts. Embedded YouTube videos and MPEG files are excluded from this V1.
3. The mini studio plays the original video and song. Choose Harmony, Lead, Bass, Beatbox, Choir or Other vocal. Use headphones and record after the four-beat count-in. Stop reviews the take; Cancel also works during preparation/permission waits. Backgrounding cancels active capture. Microphone permission is requested only after Record; no camera is requested.
4. Set original/voice volumes and vocal alignment (minus/plus 1000 ms), then Create video preview. The private preview is a real MP4 containing the existing video and mixed audio. The source stays unchanged. Changing mix settings invalidates the displayed preview until rendered again.
5. Submit a title/caption and choose whether the next artist can join. Publishing consumes the existing content upload allowance, does not consume export credits, and requires normal content moderation. Comments and voting use existing GGenre behavior and voting approval rules.
6. Published posts display all contributor credits and a link to the previous post. Approved derivatives appear under This song is growing on their source. Another artist can join an approved open derivative, preserving the credit chain (maximum 32 contributions).
7. Studio → Your vocal collaborations retains saved previews and posted versions. Closing the source prevents new recording/publishing against it but retains existing copies and private previews. Closing is not retroactive removal of collaborated posts.

## Boundaries and operations

- Limits: source under 50 MB, up to five minutes, uploaded MP4 with an audio track; new recordings are validated 16-bit PCM WAV under 64 MB. Output is H.264/AAC MP4. Original video and added voice are peak limited together. The mini studio is responsive in portrait and landscape; it does not use the full Studio landscape gate.
- The existing Studio AudioWorklet schedules the guide and capture on one audio clock; the muted video follows that clock. Device delay is estimated, with explicit alignment adjustment for review. This is not a guarantee of identical latency across devices.
- Local FFmpeg is supplied by pinned imageio-ffmpeg 0.6.0. No external media API or remote processing service. Inputs are copied from Django storage to temporary local files, remote input protocols are disabled, and subprocesses use argument arrays, timeout limits and two encoder threads. Source/temporary files are not public downloads.
- Combined previews/files use private Studio storage and authenticated playback with byte-range seeking. Only the creator can view unpublished previews. Published playback follows content approval/visibility rules. Existing public upload-file hosting is unchanged; this is not DRM.
- A request UUID prevents duplicate previews on retries. Another render from the same artist is rejected while a recent render is processing. Publishing locks the collaboration, source and upload accounting; repeat submission returns the same post. Failed processing retains the browser take for retry. Unrendered takes remain in browser memory and have an exit warning; they are not persistent raw-vocal drafts.
- Preview rendering is synchronous and bounded to 120 seconds. For a larger rollout, move rendering to background jobs and add storage retention/cleanup and processing-status recovery. HTTPS, private storage configuration and real-device checks remain staging requirements. No deployment was performed.
- Content migration 0033 adds opt-in (default false); Studio 0006 adds collaboration records. Main SQLite database backed up before migration at .local-backups/before-video-collaborations-20261030.sqlite3. No main posts were opted in or test-published.

## Verification — 30 October 2026

50 Studio Django tests pass, including permission/owner isolation, opt-in and moderation gates, preview privacy and ranges, quota enforcement, idempotent publish, source closure, credit inheritance and real FFmpeg processing. The media integration test verifies both original 440 Hz and added 660 Hz contributions survive mixing and the source bytes stay unchanged. Existing 90 content/user regression tests pass. 110 JavaScript checks pass across Studio and collaboration controls, including pending-permission cancellation, take review, background cancellation, mix bounds and countdown timing.

Browser QA uses the separate studio-preview database: created an eight-second synthetic source, rendered a new vocal layer, submitted a test post through the actual UI, verified pending review and both credits. An authored temporary fixture supplied a synthesized microphone stream to the real AudioWorklet (no real microphone permission): four-beat count-in, full capture, take review, server video preview and cancelling a replacement take all succeeded. Portrait 375×812 and landscape 812×375 frames were inspected. Temporary static QA pages were removed afterward.

Physical microphone/headphone latency, actual singing and phone/browser interruption behavior must still be tested on real Android/iPhone devices. Camera performance capture is future work; V1 retains the original video while adding vocals.


Mobile follow-up: 56 viewport/page combinations passed overflow and visible-control size checks. Approved collaborations are verified in the actual main shared feed alongside ordinary uploads, with direct join actions. See STUDIO_USABILITY.md for exact pages, sizes, fixes and remaining physical-device checks.
