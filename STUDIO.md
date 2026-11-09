# GGenre Studio

Audio imports, vocal pitch correction, noise reduction, instrumental extraction and worker setup are documented in [STUDIO_AUDIO.md](STUDIO_AUDIO.md).

Artists open **Studio** from the navigation or `/studio/`.

- Create Gospel, Acapella, or Secular projects.
- Record or import up to 12 audio tracks, each up to six minutes and 64 MB. The browser processes at 44.1 kHz so a full-length stereo WAV fits within this upload limit.
- Adjust volume, mute, timeline offset, and trim times; preview and save the mix.
- Submit a saved mix to GGenre content. Existing content approval, visibility, quota, comments, and voting rules still apply. Ordinary ratings use the existing competition/OTP system and its approval rules.
- Export 16-bit stereo WAV. The first two export requests per artist are free for the account lifetime. Re-downloading the same export does not spend another allowance. Later requests wait for manual payment verification.
- Admins use **Studio exports** (`/studio/exports/`) to verify payment and approve or reject requests. Staff can also use Django admin export actions. No payment processor or price is configured by this feature.

## Storage and deployment

Apply `python manage.py migrate studio` before starting the updated application. This creates only new Studio tables. Run `python manage.py collectstatic --noinput` during the normal deployment process, then restart the application normally.

Source tracks and saved mixes live in `studio_private/`, outside `MEDIA_ROOT`. Keep that directory persistent and backed up; never expose it through nginx, public file hosting, or a web server static alias. Files are served through permission-checked application routes. The service worker excludes Studio routes from caching.

Each saved mix gets a new immutable filename. Published content and exports retain the saved version they reference, so later edits do not change previous publications or exports. Old source and mix files are intentionally retained; storage cleanup/retention is a future operational task.

Published mixes offer playback without a download control; browser-playable audio cannot be made impossible to copy. Project source tracks remain owner-only. Recording needs microphone permission and HTTPS (localhost also works). Imported audio support depends on the browser codec support. This version provides imported backing tracks rather than a licensed beat library, and basic mixing rather than a full DAW/effects suite. Recording now uses Web Audio and an AudioWorklet to put backing playback and raw microphone capture on the same audio clock. Choose a timeline start, tempo, and 0/4/8 beat count-in. Existing unmuted tracks play automatically with their current trims, gains, and timeline offsets. The count-in is excluded from the captured take. Microphone monitoring is disabled to avoid delayed feedback, and echo cancellation, noise suppression, and automatic gain control are requested off for music capture.

After Stop, review the vocal on its own or alongside the backing tracks. The review starts with a browser-reported input/output delay estimate, which is not a measured calibration. Positive delay correction moves vocals earlier; negative moves them later. A short capture tail retains delayed input when Stop is pressed. Keep saves a new private track at the chosen timeline position and preserves edits to existing tracks. Re-record and Discard do not change server data. Failed uploads leave the pending take available for retry in the current tab. Edits and pending takes now have browser-local recovery when IndexedDB storage is available; see below.

Use wired headphones for predictable latency. Real microphone capture, hardware delay, audible alignment, Bluetooth behavior, browser backgrounding, and mobile interruptions require real-device acceptance testing. Software scheduling alone cannot guarantee sample-accurate acoustic alignment across every device.

For production, allow Studio upload request bodies of at least 65 MB at the web server/proxy layer. This change does not alter nginx or any live deployment.

## Verification

Run `python manage.py test studio content users --noinput` for Studio permissions, free export accounting, payment approval, snapshot preservation, publication moderation, upload quota, comments, and existing content/user regressions.

Before release, verify microphone capture on the target browsers/devices, import an instrumental and record harmonies, trim/offset tracks, preview/save/reopen, then submit to content and approve through the existing dashboard. Confirm two free exports followed by an approval-gated third export. Test playback as a different logged-in user and ensure source track URLs and export URLs are denied. Browser microphone capture and audible mix quality need real-device testing.


## Free audio APIs evaluated

- Native Web Audio / AudioWorklet: chosen for shared-clock playback and raw PCM capture without API keys, usage fees, or external transfer of vocals. https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletGlobalScope/currentFrame
- Tone.js (MIT): useful for later tempo transport, musical sequencing, and effects. It builds on the same Web Audio scheduling and does not remove device latency. https://github.com/Tonejs/Tone.js/
- wavesurfer.js: useful for waveform editing/visualization; it is not the recording/mixing engine. https://wavesurfer.xyz/

## Recording regression checks

Run `node --test scripts/studio-audio.test.cjs scripts/studio-recording-ui.test.cjs` for frame boundaries, countdown cancellation, sample-rate handling, timeline seeks, latency shifts, take review, upload retry, and preserving existing edits.

The browser synthetic-input fixture in `scripts/browser-tests/studio-audio-qa.html` tests the actual AudioWorklet with generated microphone input and muted output. During local development, temporarily copy it to `static/studio-audio-qa.html`, open `/static/studio-audio-qa.html`, and run its checks; remove the served copy afterward. It does not request microphone access.


## Waveform timeline and local recovery

The project timeline draws waveforms from private decoded track audio using Canvas. Drag a clip to move it, or drag its ends to trim it without changing the original recording. Left trimming preserves the clip end position. The numeric controls remain available for keyboard use and precision. Click the ruler to choose the recording start; zoom in for short clips. Waveforms combine both stereo channels and are scaled for visibility, which does not amplify the saved audio.

Track edits autosave to IndexedDB after a short pause. Completed but unkept takes are stored there too. Active recordings checkpoint approximately every five seconds, so a crash can lose the most recent few seconds or an in-flight storage write. A partial checkpoint is also offered for review when capture is interrupted.

Recovery is per browser origin, signed-in artist, and project. Reopening offers Restore or Discard rather than silently replacing server data. If the server project revision changed, only the vocal take can be recovered; older track edits do not overwrite current ones. Successful server saves and track uploads clear the obsolete draft, including queued writes. Removing a track also preserves the other track edits.

Only the latest local copy per artist/project is kept. Browser storage can be unavailable, full, cleared, or evicted; the status text reports failures. Recovery is not a server backup, and clearing browser data removes it. Use Save mix and Keep take to save work to GGenre. Publishing, moderation, and export accounting are unchanged.

Additional checks: `node --test scripts/studio-audio.test.cjs scripts/studio-recording-ui.test.cjs scripts/studio-timeline.test.cjs`. The browser fixture `scripts/browser-tests/studio-recovery-qa.html` checks native IndexedDB audio persistence, isolation, queued deletion, and Canvas rendering using generated audio only. Temporarily serve a copy from static/ for local QA and remove it afterward.


## Dedicated Studio interface

The Studio editor and project library now use their own base template, separate from the social-feed shell. The full-height workspace contains a transport (play/pause, stop, record, return to start, session clock, tempo and count-in), aligned mixer strips and waveform lanes, and a recording inspector. Original-take audition, volume, mute, numeric timing, and deletion remain available in each track strip. The playhead follows actual mixed playback and vocal recording. Playback starts at the chosen start position.

Publishing and export requests live in a header panel and retain all existing server permissions and quota rules. On narrow screens the recording inspector opens from the setup icon rather than covering the workspace with social navigation. Recovery notices, pending-take review, and local save status are retained. No payment, permission, storage, or database schema changes are part of this interface update.


### Cancel an active take

A visible Cancel take action appears while the microphone or backing tracks prepare, during the count-in, and while recording. Stop finishes a take for review; Cancel discards it, releases the microphone, and removes its local checkpoint while retaining pre-existing track edits. Cancellation tokens prevent delayed permission responses or late audio callbacks from restarting a cancelled take. A browser permission prompt already open must still be answered or dismissed by the artist; a cancelled attempt will not record afterward.

Cancellation was tested for active capture, pending microphone permission, pending audio setup, preservation of edits, and late callbacks, plus a browser UI check with simulated input and no microphone access.


## Landscape phone workspace and PC testing

Project pages require landscape when the viewport is portrait and at most 900 CSS pixels wide. Project selection remains available in portrait. A prompt replaces access to the editor, and the editor becomes inert until the viewport is widened or rotated. Phones use a compact single-row transport and a full-width arrangement in landscape; recording setup remains available from the setup icon. Safe-area insets account for phone notches.

Orientation changes do not cancel or stop an active recording. The portrait prompt retains direct Stop & review and Cancel take actions. Cancellation stays available while microphone permission or backing-track preparation is pending; Stop becomes available once the audio session exists.

To test on a Windows PC, open the local Studio in Chrome or Edge, press Ctrl+Shift+I, then Ctrl+Shift+M, select Responsive and enter 844 × 390. Use the device-toolbar Rotate control (or swap width and height) to compare with 390 × 844. There is no need to rotate the physical monitor. Device emulation tests viewport layout, not real microphone latency or all hardware/browser behavior.

Run `node --test scripts/studio-orientation.test.cjs` for orientation gating and the safe capture controls. Browser checks verified portrait/landscape rendering and live viewport switching with isolated generated test tracks.


## Category workflows and starter rhythm presets

Project type selection now uses a themed, keyboard-accessible picker that preserves the native form field. The same picker is used for Studio count-in and rhythm options.

- Acapella provides lead, soprano, alto, tenor, bass and vocal-percussion shortcuts, vocal imports, and the normal count-in. It has no beat library. The server rejects tracks explicitly submitted as backing or Studio beats for Acapella; it does not analyze the contents of an uploaded vocal file.
- Gospel offers Worship, Praise and Congregational starter rhythms and lead, backing choir and congregation voice shortcuts.
- Circular / Secular offers R&B pocket, Hip-hop and Contemporary bounce starter rhythms and its own vocal shortcuts. The stored category remains `secular` for compatibility.

These are original synthesized percussion patterns, not complete instrumental songs or a licensed sample collection. Each rhythm can be previewed, given a tempo from 40–240 BPM, and added as a 4/8/16/32-bar WAV track. Adding one sets the project's count-in tempo. One Studio beat is allowed per project; remove it before replacing it or changing its tempo. Artists can still import their own permitted instrumentals for Gospel and Circular / Secular.

Migration 0002 adds project tempo and track kind/preset/BPM fields. Existing projects retain tempo 80 (the previous UI default), and existing files remain untouched. Beat addition does not publish content or consume an export. Explicit Save mix, content moderation, and the original export allowance rules remain in effect.

Additional checks: `node --test scripts/studio-beats.test.cjs` and `python manage.py test studio --noinput`. Browser QA covered styled project selection, creating an Acapella project, voice shortcuts, and generating/adding a Circular / Secular rhythm with a matching count-in tempo.


## Acapella voice workflow
Acapella sessions accept vocal tracks only and omit instrumental beat controls. Choose a voice part (lead, harmony, choir parts, bass or vocal percussion); new take names advance automatically. Existing voice names can be edited in the mixer. Import voices at the chosen timeline position.

Solo controls monitoring for playback, take review and recording guides only. Save mix always renders every unmuted voice. Mute excludes a voice from the finished mix. An optional C3–C5 reference note stops before recording and is never saved as a track. Use headphones to prevent speaker bleed. The finished Acapella mix has a common peak reduction when required to avoid digital clipping; raw recordings remain unchanged. This does not repair clipping already captured by the microphone.

Voice setup preferences persist within the browser session. Local recovery includes names, edits, capture tempo and unfinished takes. Mutations carry an optional project revision token and reject stale tabs instead of overwriting newer work. Publishing, payment approval and the first two free exports retain their existing workflow.

Validation: 41 JavaScript tests and 20 Django Studio tests pass, plus Django system checks and migration checks. Real microphone quality, headphone bleed, device latency and phone rotation still require device acceptance testing. Suggested acceptance: record lead and harmony, cancel a third take, rename/trim/align a voice, Solo then Save (both unmuted voices must remain), Mute then Save (muted voice absent), refresh/recover, publish and export.


## Instrumental backing builder
Gospel and secular sessions now offer original synthesized piano, bass, sustained synth chords, drums or a combined full backing. Choose one of twelve root keys, major I–V–vi–IV, major I–IV–I–V, major seventh ii–V–I–vi or minor i–VI–III–VII progressions, tempo and 4/8/16/32 bars. Preview renders a four-bar harmonic cycle. Style suggests a progression without restricting the user's choice.

The result is baked into one private WAV backing track using the existing beat workflow and one-generated-backing limit. Its name records style, instruments, key, progression and BPM. Choose configuration before adding; remove the generated track to replace it. Instruments are additive synthesis approximations, not sampled acoustic instruments. Original source voices, existing backing tracks and Acapella restrictions are preserved. No external services, sample downloads, API keys or schema migrations.

Verification: 45 JavaScript tests and 21 Django Studio tests, including note transposition, all instrument modes, progression bounds, synthesis envelopes and output peak limiting. Browser smoke test previews and adds a full backing in the separate preview database.


## Dedicated instrumental workspaces
Open Studio → Instrumental Library. Piano, Bass, Chords and Full arrangement have dedicated entry points into an editable composer. Full arrangement includes a drum sequencer, piano roll, bass roll and sustained chord roll. Each composition uses a four-bar, sixteenth-note pattern repeated over 4/8/16/32 bars. Change octave, note length and bar, toggle note cells, set instrument levels, transpose key or generate a starting pattern. Style/chord changes affect generated patterns only when Generate is pressed. Preview plays four bars; saving renders the configured song length.

Instrumental stores a validated versioned JSON composition and private PCM WAV, with artist-only ownership and revision conflict checks. Local browser drafts offer same-version recovery. Reopen from the private library to edit. Use in Studio copies the WAV to a new vocal project by default; library cards also offer existing projects in the same category. Existing sessions require a matching tempo when tracks are present, no existing generated backing and space under the 12-track limit. Acapella rejects instrumental reuse. Backing copies remain unchanged if their original composition is edited. Device exports still go through the existing Studio allowance/payment workflow.

Migration 0003 creates the Instrumental table. Before applying locally, SQLite backup created under .local-backups/before-instrumental-workspaces-20261029-032313.sqlite3. Existing Studio project/track/export/release/allowance rows compared unchanged after migration. The pending preexisting users.0020 default-only OTP field migration also ran; no OTP row changes were introduced.

Verification: 51 JavaScript tests and 25 Studio Django tests pass. Browser QA in separate preview DB: edit a piano note, render preview, save, reload with note intact, Use in Studio creates project with private backing and matching tempo. No microphone was activated.


## Immediate note audition
Composer cells now audition their instrument when clicked, while retaining add/remove editing. Pitch and drum-name buttons audition without editing. Auditions respect transposition, instrument level and note length (short listening sample capped at 1.5 seconds). Preview progression plays the entire four-bar pattern with all enabled parts. Stop, saving, progression preview and page exit stop active auditions; pending audio activation is cancelled safely. The audio context opens only on interaction, needs no microphone, is reused across clicks, and caps simultaneous audition voices at eight. 55 JavaScript tests pass, including note pitch/volume, drum audition, mute, pending cancellation and cleanup. Browser smoke check confirms pitch-label audition leaves the composition saved, cell audition edits the note, and full progression still renders.

New instrumental workspaces start with empty piano, bass, chord and drum patterns. Generate starting pattern is optional. Saved compositions and explicitly restored drafts retain their notes.


## Piano: play, record and arrange complete songs
Piano now opens a dedicated performance workspace, rather than the four-bar loop editor. New songs remain blank. Add a named section, play using mouse/touch or A W S E D F T G Y H U J K O L P, and Record section with optional 4/8-beat count-in and metronome. Hold keys for duration; recording captures notes (not microphone audio), quantized to sixteenth notes. Stop opens Keep/Discard review; Cancel preserves existing notes. Layer onto section optionally overdubs. Piano keys and note correction cells audition immediately.

Arrange independent named sections along a bar timeline, duplicate them, drag them into empty positions or set start and length explicitly. Each section supports 1–32 bars, up to 1024 notes; a song supports up to 64 sections and 4096 notes within five minutes. Song length accepts any whole bar count up to the tempo-dependent five-minute bound, not just 4/8/16/32. Clip overlap and truncating notes when shrinking sections are rejected. Play section and Play song are distinct. The note-correction grid is secondary, inside expandable Edit notes. Song duration is always visible.

Saved piano songs use JSON schema 2 with explicit clips and non-repeating notes. Legacy schema-1 piano patterns convert into independent four-bar sections in the browser on opening, preserving the original loop placements; server storage/audio stays unchanged until Save. Other instrument workspaces keep their existing schema-1 workflow. Save renders the whole song. Use in Studio keeps the private copy/tempo/export workflow. No database migration is needed.

Verification: 63 JavaScript tests and 28 Django Studio tests pass. Browser QA in isolated preview DB records three played notes, keeps a take, duplicates four sections into an 85-second song, plays the complete song, saves/reopens all sections, cancels another recording without changing saved notes, and reuses the piano in vocal Studio at matching tempo. Hardware touch performance and computer keyboard rollover still need real-device acceptance testing.


## Main piano-roll layout
The piano roll is again the primary view: playable white/black keys remain fixed on the left while the entire song scrolls horizontally. New piano songs default to 32 blank bars (about 85 seconds at 90 BPM). Set Song length or use Extend song 8 bars, also available at the far right end. The grid width grows with song length; zoom changes visual scale, not timing. The ruler shows bars and elapsed time, and playback displays a moving playhead.

Click an empty grid position anywhere in the song to add a note; an independent section is created automatically when needed. Click a note to select/audition it, drag to move in time/pitch, drag the right edge to change duration, and right-click/Delete to remove. Playable keys on the left also work while recording. Computer-keyboard performance and section management remain available in optional expandable panels. Record can create its first blank section automatically.

Verification: 67 JavaScript tests and 28 Django Studio tests. Browser checks cover blank 32-bar start, drawing notes, vertical/horizontal dragging, resizing, extending 32 to 40 bars, horizontal scroll with fixed keys, adding a note at bar 10, and saving/reopening the song. No migration or existing-song rewrite is needed.

Vertical and optional horizontal piano keys now sustain while held, using a continuous periodic tone with attack/sustain and a short release on pointer/key up. There is no fixed 16-second audio timeout or natural fade to silence during a hold. Stop, cancellation, blur, hidden-page and exit cleanup remain active. Schema-2 piano note rendering and overdub guides sustain for each stored note's duration, so saved playback matches held-note behavior. Legacy backing presets retain their original envelope. 70 JavaScript tests pass, including a simulated hold beyond 16 seconds, loop audibility and saved-note sustain/release.


## Piano note selection and phrase copy/paste
Select all selects every note across the song, including offscreen bars/octaves. Shift-click adds/removes individual notes; Deselect clears selection. Copy notes stores a phrase in the artist's browser-session clipboard, preserving relative note timing, durations, velocities and sounding pitches. Pick Paste at bar and Beat, then Paste notes. Sources stay intact; pasted notes become independent selected notes. The song extends when required within its existing five-minute limit. Existing same-onset pitches are skipped; held notes that would be truncated by an existing section boundary are rejected with guidance. Ctrl/Cmd+A/C/V work outside text fields. This internal clipboard does not require system clipboard permissions and can be reused across the artist's piano workspaces in the same browser session.

Verification: 75 JavaScript tests pass, including multi-section selection, phrase timing, original immutability, duplicate skipping, song extension, bounds and pitch transposition. Browser QA copies four notes to bar 17 and confirms Select all finds all eight originals/copies.


## Consistent library workspaces and beginner helpers
Piano, Bass, Chords, Drums and Full arrangement now share the song-wide editor, 32-bar blank starts, recording/count-in, private save/reopen, copy/paste and Studio reuse. Bass uses a low default range with a root-plus-octave brush; Chords starts with a major-chord brush and whole-bar duration; Drums provides kick/snare/hat/clap/rim pads and single-hit sequencing. Full arrangement uses four independent instrument layers and level faders; different instruments may overlap, same-layer sections may not. Legacy schema-1 compositions convert locally into matching editable instrument sections without altering stored audio until Save.

Start blank or explicitly Add a 4-bar idea. Quick song length choices cover about 1–4 minutes, with all song limits retained. Major/minor chord brushes add triads with one click. Repeat phrase duplicates after the original; Fill song repeats a selected phrase through remaining duration. Undo/Redo (Ctrl/Cmd+Z/Y) make edits reversible in the current session. Full arrangement's starter-idea option includes all four layers by default, with an explicit checkbox to use just the active layer. Setup and optional ideas sit in an inspector so the instrument grid stays visible. Nothing is generated without user action.

Schema 2 retains backward-compatible piano clips and now includes instrument identity for bass, pad and drums; server validation enforces ownership, valid roles/drum hits, levels, non-overlap by role, 64 sections, 4096 notes and five-minute bounds. No model migration is needed. Song rendering mixes deterministic PCM directly with progress updates instead of constructing a large Web Audio source graph. Legacy beat rendering remains unchanged.

Verification: 81 JavaScript tests and 30 Django Studio tests pass. Browser QA covers full-band idea/fill/undo, bass-layer editing, one-click chord creation/repeat, drum pad/idea/fill/playback, and saved full-band reopening with all 32 sections intact. Real-device touch and musical acceptance remain hands-on checks.


## Full-band editing parity
Full Arrangement now defaults to Entire band selection scope. Select entire band and Ctrl/Cmd+A include every instrument; Active instrument only limits actions to the visible layer. From bar / Through bar selects a phrase range across the chosen scope. Copy/paste, Repeat and Fill use those selected notes with instrument identity preserved. Whole-band selection survives switching visible instrument layers. The selection counter reports both note count and number of layers.

Song length (bars) and elapsed duration are visible directly beside the roll, in addition to the inspector. Choose Note length then Apply note length to selection for batch duration edits across piano, bass and chords; notes stop at their section boundaries, and drum hits remain single steps. Undo reverses these edits. No audio or export permissions change.

Verification: 84 JavaScript tests pass. Browser QA selected all 896 notes across four layers, copied a 112-note four-bar range to bar 33 with originals intact, changed 64 melodic durations while keeping drums single-step, undid that change and selected all 1008 original/copied notes across four layers.


## External keyboards: MIDI and audio provisions
Every instrument workspace has an External keyboard · MIDI / Audio panel. Connect MIDI keyboard explicitly requests MIDI input access without SysEx or output access. Choose all inputs or one device and all channels or channels 1–16. Note on/off (including note-on velocity zero), playing strength, sustain pedal CC64, all-notes/all-sound off, duplicate note-on, hot-plugging, panic and disconnect cleanup are handled. MIDI plays/records the active instrument, using the existing take/review/save flow. MIDI drum input maps common GM kick/snare/hat/clap/rim pitches. This version accepts melodic MIDI C1–C6, with the existing transposition and duration limits. Device access is browser/platform dependent and requires a secure context (HTTPS or trusted localhost) and user permission. No connection is requested on page load.

Start keyboard audio session creates an artist-owned Gospel/Secular Studio session, keeping note work in local recovery and opening Keyboard / audio interface mode. Studio offers Record source, exact audio-input device selection, an explicit Enable / refresh inputs permission action and channel mix/left/input1/right/input2 selection. Capture remains mono PCM in this V1; stereo input can be mixed or one channel selected. A keyboard needs an audio interface or native USB audio support to provide its own sound. The live audio input stays silent in speakers; use headphones/interface direct monitoring. Keyboard takes retain timing, review/retry/cancel/recovery, and save as private backing audio; microphones remain vocal tracks. Acapella remains vocal-only. Export/payment rules are unchanged.

Validation: 99 JavaScript tests and 32 Django Studio tests pass, including MIDI permission laziness, velocity, sustain, channel/device filtering, disconnect and pending-permission cleanup; input constraints/temporary-stream cleanup; mono mixing/channel isolation; keyboard-audio backing classification and Acapella protection. Browser UI checks do not connect MIDI or activate any microphone/interface. Physical keyboard, driver, sustain pedal and latency acceptance testing remains necessary on the actual hardware. No database migration is required.


## Standard sound palette and toms
Instrument sound now selects a persisted voice per piano/bass/chord layer. Voices include Grand piano, Bright piano, Electric piano, Drawbar organ, Classic synth lead, Soft pluck, String ensemble, Classic synth chords, Warm worship pad, Airy pad, Finger bass, Sub bass and Synth bass (filtered by suitable layer). Preview sound auditions the selected voice; live keys/MIDI, overdub guides, playback and saved WAV rendering use the choice. New Gospel projects default the chord layer to Warm worship pad, with a gentle attack and release. Existing projects without sound metadata retain their existing voice defaults; stored audio is unchanged until Save. All sounds are original synthesis, with no downloaded samples or service API dependency.

Drums now include low, mid and high toms, separate sequencer rows/pads, H/J/K shortcuts and GM MIDI tom mappings (41/43 low, 45/47 mid, 48/50 high). Add tom fill places high/mid/low hits at the end of the Through bar position. Praise and Hip-hop ideas include a tom fill on every fourth bar; rhythm rendering, editable patterns, saving and server validation accept toms. Sound metadata is validated per instrument and kept in the existing JSON config; no migration is required.

Verification: 103 JavaScript tests and 34 Django Studio tests pass. Browser QA previews the worship pad, adds and saves a chord idea, confirms its sound survives reopen, previews the high tom, adds a three-tom fill and saves it. Existing selection, MIDI/audio input, recording and export tests pass.


## Admin export allowances

Admin navigation: Studio exports → Manage artist export limits & resets (`/studio/exports/controls/`). Search artists, set a free-export limit, correct free usage, or reset usage to zero while retaining the limit. A reason is required and changes are logged in Django admin history with actor/time; the page shows the latest 20 allowance changes. A stale limit/usage snapshot is rejected. Artists without an allowance row display the default two credits and can be configured before their first export. Zero credits requires payment approval immediately. Lowering the limit below usage yields zero remaining credits. Existing exports, downloaded files, pending payments and approval decisions are unchanged by resets. Repeat downloads of an existing export remain free; the counter measures new free export requests, not HTTP downloads. Payment approval continues through the existing review screen.

Django admin also registers Export allowances with search, edit fields and a logged bulk Reset usage action; deletion is disabled to avoid silently restoring default credits. Migration 0004 adds free_limit=2 while preserving every existing free_used value. Artist home/editor display the actual remaining allowance. Main database backed up to `.local-backups/before-export-controls-20261030-053452.sqlite3` before migration.

Browser validation on isolated preview database: changed studio_preview limit from 2 to 4, corrected usage to 2, reset to 0; confirmed 4 remaining and both audit entries. No main artist allowances changed during QA. Regression tests cover configurable/zero quotas, reset, audit, invalid/stale submissions, CSRF, artist-only targeting and existing payment/download behavior.


### Suspend export limits
Admin controls and Django admin now expose per-artist unlimited_exports. When enabled, new export requests are immediately available without payment approval and do not consume free_used. Unchecking resumes the saved limit and usage. Existing pending requests and download permissions remain unchanged. The setting is included in stale-form checks and audit entries; Reset usage preserves the unlimited setting. No artists are automatically enabled. Migration 0005 defaults false. Audit history is collapsed under Admin change history; new entries use named limit/usage/unlimited values instead of positional tuples. 41 Studio tests pass, including suspension, resumption and audit/stale protection. Isolated browser QA enabled the preview artist and confirmed the saved checkbox and collapsed history.


## Vocal video collaborations

A separate lightweight Add your voice workspace lets artists layer vocals onto opted-in MP4 posts and submit a credited new video. It reuses Studio capture without changing existing project, instrumental or export workflows. See COLLABORATIONS.md for the creator journey, limits, migrations, privacy and full validation evidence.


## Read and collaboration performance

Private reference-audio guides can be reused after per-request authorization, with source fingerprint invalidation and uncached fallback. Feed/post counters, recommendations and header unread totals avoid per-item queries; polling requests share in-flight work. See PERFORMANCE.md for measured results, the additive index migration, cleanup command and regression validation.
