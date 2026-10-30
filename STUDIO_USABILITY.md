# Studio usability testing

## Local assessment — 30 October 2026

This is an agent-led desktop walkthrough plus automated regression testing, not a study with representative users. No deployment was performed. Browser writes used the separate studio-preview SQLite database and studio_preview account; existing artist projects in the main database were not edited.

### Observed and verified

- Library → blank piano workspace → explicitly add four-bar idea → Fill song: 32 bars, eight sections, approximately 85 seconds at 90 BPM.
- Save completed; reload retained the arrangement. Use in Studio created preview project 8 with one private backing track; recording/playback controls unlocked after audio loaded.
- Publish/export panel explained the saved-mix prerequisite, two free exports and payment verification. Both submission actions were disabled before a mix was saved. No publication or payment was submitted through the browser.
- A fresh Bass workspace returned to Library without an unsaved-work warning after the fix.
- Existing-track Studio displayed the corrected ready message after the fix.

### Fixes made

1. Untouched new instrumental workspaces no longer start dirty and trigger an unnecessary exit warning. Actual edits, recording/review and restored drafts still activate protection.
2. Recovery wording now says instrumental rather than piano for all workspaces.
3. Existing-track projects now offer play/add/save guidance rather than telling users to record their first take.

### Automated evidence

103 JavaScript tests passed across audio, recording UI, timeline, orientation, beats, voices, composer, piano, MIDI and input selection. 34 Django Studio tests passed, including artist/owner restrictions, private audio, saved mix snapshots, publishing moderation, first-two-free exports/payment approval, revisions, Acapella restrictions, instrumental reuse and sound/tom persistence. Django system checks and JavaScript syntax checks passed. These checks do not establish novice usability, acoustic quality or production readiness. Social-platform regression outside Studio was not rerun in this pass.

## Moderated pilot checklist

Run with at least five artists, including beginners, on a private staging installation with disposable accounts. Give tasks without explaining which buttons to press. Record device/browser, task time, success without help, errors, help requests and a 1–5 ease rating. Observe with consent; do not collect passwords or raw recordings without permission.

| Task | Acceptance criterion |
| --- | --- |
| Find Studio and start Acapella | Artist finds it unaided; no beat controls appear; fan cannot enter artist tools. |
| Make a piano instrumental over one minute | Starts blank; artist adds notes, extends/repeats and understands song duration. |
| Edit and reuse a phrase | Select, copy/paste, move, resize and Undo work without unexpected note loss. |
| Build a full band | Artist switches layers, chooses sounds and understands Entire band versus Active layer. |
| Save and reopen | Notes, sounds, duration and title survive reload; Use in Studio copies the intended audio. |
| Record vocals over backing | Headphones, count-in and start position are understandable; existing tracks stay aligned. |
| Cancel/retry a take | Cancel during setup/count-in/recording adds no unwanted take; Keep/Discard are clear. |
| Recover interrupted work | Reload after edits and during a test take; restoration is explicit and saved work remains available. |
| Publish to GGenre | Saved mix enters moderation; private source tracks stay inaccessible to another account; approved content supports existing comments/ratings. |
| Export | First two exports succeed; third requires approval; rejection/retry does not accidentally consume allowance. |
| Phone orientation | On real Android and iPhone, portrait guidance appears on entry; landscape controls remain reachable; leaving Studio removes the gate. Browser/OS rotation behavior must be checked physically. |
| Keyboard/audio hardware | Permission denial/retry, MIDI pedal/note release, disconnect/reconnect, interface channel selection, headphones and latency all behave clearly. |
| Slow/offline network | Failed save is actionable; draft survives; retry does not duplicate data; stale edits cannot overwrite another session. |

Pilot release gate: no data-loss, privacy, recording-cancel or export-accounting failures; at least four of five artists complete the core compose/save/record tasks without intervention. Investigate any repeated failure before expanding the pilot. These are proposed acceptance targets, not measured results.

## Staging preparation still required

Use HTTPS for capture/MIDI permissions, isolated database and private audio storage, fresh test credentials, error logging and a tested backup/restore process. Do not expose the local artist/artist testing credential publicly. Confirm authenticated private-audio delivery, upload limits, service-worker/static refresh and moderation/admin permissions in the deployment environment. Run the existing social-platform regression suite before public testing. Schedule real-device and human sessions above; local automated success cannot replace them.


## Mobile collaboration pass — 30 October 2026

Tested eight rendered artist journeys at seven viewport sizes (56 combinations): collaboration workspace with an unusually long unbroken title, saved collaboration library, main shared feed, collaboration post/credits/comments, upload form, Studio home, instrumental library, and take-review/publish panels. Viewports: 320×568, 360×640, 390×844, 430×932, 667×375, 844×390 and 768×1024. These are browser viewport simulations, not physical Android/iPhone testing.

Fixed header/title overflow, wrapped long credits and form actions, raised visible controls to at least 44px height, enlarged checkbox labels and native/select controls, used 16px input text to avoid focus zoom on iOS, and included safe-area spacing. Applied corresponding fixes to shared navigation, post tools/comment submission, uploads and Studio library controls. The final DOM measurements found zero horizontal-overflow failures and zero visible form controls below 44px height across all 56 combinations (hidden replacement selects and label-backed checkboxes excluded). Visual checks covered portrait/landscape and a real AudioWorklet capture with a synthesized microphone stream in a 320px frame. Stop/Cancel remained reachable; cancellation retained the previous state. No real microphone permission was requested.

The actual main feed uses content/welcome.html. It already selects approved/visible Content records regardless of whether their media is a normal upload or a private collaboration video. Added the direct join action and a collaboration label to that template, prevented the stretched card link from covering the join/profile links, and allowed collaboration cards to grow instead of clipping the action. A normal uploaded MP4 and an approved collaborated video were seeded only in the isolated preview database and confirmed side by side in this shared feed. Tapping the collaboration action reached its correct /studio/collaborate/<id>/ workspace. New backend coverage confirms pending/hidden collaborations stay out of the public feed while approved ones appear alongside normal uploads, with authenticated media playback URLs. All 99 Studio/content regression tests passed.

Evidence: .local-backups/mobile-shared-content-feed.png and .local-backups/mobile-collaboration-controls.png. Temporary static QA fixtures were removed after testing. Physical phone hardware, browser chrome/virtual keyboard behavior and real singing latency still require device testing. This pass covers the eight journeys listed above; it is not a certification of every admin/chat screen or every phone/browser combination.


### UI recheck after performance changes
Fresh rendering of all eight artist journeys at seven viewport sizes passed again: 56 checks, zero measured overflow and zero undersized visible form controls. Browser navigation from the shared feed reached the correct collaboration workspace. Vocal-role keyboard selection and restoration worked. Review/publish layouts included vocal preview, combined-video preview, long title, caption, keep-collaboration-open checkbox and submission control. This pass checked layout and navigation; it did not activate a real microphone or submit a new post. Results: .local-backups/ui-recheck-results.json. Temporary QA pages removed.
