"""Bounded, versioned four-bar composition patterns; no external sound assets."""
from .catalog import beats_for

SOUNDS = {
    "piano": {"piano", "bright-piano", "electric-piano", "organ", "synth-lead", "pluck", "strings", "warm-pad", "airy-pad"},
    "bass": {"bass", "sub-bass", "synth-bass"},
    "pad": {"pad", "warm-pad", "airy-pad", "strings", "organ", "electric-piano"},
}


def validate_piano(value, category):
    def integer(item, low, high):
        return type(item) is int and low <= item <= high
    if value.get("mode") not in ("piano", "bass", "chords", "drums", "full") or not integer(value.get("bpm"), 40, 240) or not integer(value.get("bars"), 1, 256) or value["bars"] * 240 / value["bpm"] > 300:
        raise ValueError("Keep the piano song within five minutes at 40–240 BPM.")
    if not integer(value.get("key"), 0, 11) or value.get("preset") not in {p["id"] for p in beats_for(category)}:
        raise ValueError("Choose a valid key and category style.")
    default_part = {"piano": "piano", "bass": "bass", "chords": "pad", "drums": "drums", "full": "piano"}[value["mode"]]
    allowed = {"piano", "bass", "pad", "drums"} if value["mode"] == "full" else {default_part}
    levels = value.get("levels", {})
    if not isinstance(levels, dict) or set(levels) - {"piano", "bass", "pad", "drums"} or any(type(level) not in (int, float) or not 0 <= level <= 1 for level in levels.values()):
        raise ValueError("Set instrument levels between zero and one.")
    sounds = value.get("sounds", {})
    if not isinstance(sounds, dict) or any(part not in SOUNDS or not isinstance(sound, str) or sound not in SOUNDS[part] for part, sound in sounds.items()):
        raise ValueError("Choose a supported sound for each instrument layer.")
    clips = value.get("clips")
    if not isinstance(clips, list) or len(clips) > 64:
        raise ValueError("Use up to 64 piano sections.")
    normalized, ids, spans, total = [], set(), [], 0
    for clip in clips:
        instrument = clip.get("instrument", default_part) if isinstance(clip, dict) else None
        if instrument not in allowed:
            raise ValueError("Choose an instrument available in this workspace.")
        if not isinstance(clip, dict) or not isinstance(clip.get("id"), str) or not 1 <= len(clip["id"]) <= 64 or clip["id"] in ids or not isinstance(clip.get("name"), str) or not 1 <= len(clip["name"].strip()) <= 80:
            raise ValueError("Give each section a unique identity and a name.")
        if not integer(clip.get("start"), 0, 255) or not integer(clip.get("bars"), 1, 32) or clip["start"] + clip["bars"] > value["bars"]:
            raise ValueError("Keep each section inside the song timeline.")
        if any(instrument == part and clip["start"] < end and clip["start"] + clip["bars"] > start for start, end, part in spans):
            raise ValueError("Piano sections cannot overlap. Move or duplicate into an empty space.")
        ids.add(clip["id"])
        spans.append((clip["start"], clip["start"] + clip["bars"], instrument))
        notes, occupied = clip.get("notes"), set()
        if not isinstance(notes, list) or len(notes) > 1024:
            raise ValueError("Use up to 1024 notes per section.")
        total += len(notes)
        if total > 4096:
            raise ValueError("Use up to 4096 notes per piano song.")
        clean = []
        for note in notes:
            if not isinstance(note, dict) or not integer(note.get("step"), 0, clip["bars"] * 16 - 1) or not integer(note.get("length"), 1, 64) or note["step"] + note["length"] > clip["bars"] * 16 or not integer(note.get("midi"), 24, 84) or note["midi"] + value["key"] > 96:
                raise ValueError("Invalid piano note position, pitch or duration.")
            if instrument == "drums" and (note["midi"] not in (24, 26, 28, 29, 31, 32, 33, 34) or note["length"] != 1):
                raise ValueError("Choose a supported drum or tom step.")
            identity = (note["step"], note["midi"])
            if identity in occupied:
                raise ValueError("Duplicate piano note.")
            occupied.add(identity)
            velocity = note.get("velocity", .7)
            if type(velocity) not in (int, float) or not 0 < velocity <= 1:
                raise ValueError("Invalid piano note velocity.")
            clean.append({"step": note["step"], "length": note["length"], "midi": note["midi"], "velocity": velocity})
        normalized.append({"id": clip["id"], "name": clip["name"].strip(), "start": clip["start"], "bars": clip["bars"], "notes": clean, "instrument": instrument})
    return {"schema": 2, "mode": value["mode"], "bpm": value["bpm"], "bars": value["bars"], "key": value["key"], "preset": value["preset"], "levels": levels, "sounds": sounds, "clips": normalized}


def validate_config(value, category):
    if isinstance(value, dict) and type(value.get("schema")) is int and value["schema"] == 2:
        return validate_piano(value, category)
    if not isinstance(value, dict) or (type(value.get("schema")) is not int or value.get("schema") != 1):
        raise ValueError("Unsupported instrumental format.")
    def integer(item, low, high):
        return type(item) is int and low <= item <= high
    if not integer(value.get("bpm"), 40, 240) or value.get("bars") not in (4, 8, 16, 32) or type(value.get("bars")) is not int:
        raise ValueError("Choose 40–240 BPM and 4, 8, 16 or 32 bars.")
    if value.get("mode") not in ("piano", "bass", "chords", "full", "drums") or not integer(value.get("key"), 0, 11) or value.get("progression") not in ("major", "worship", "soul", "minor"):
        raise ValueError("Choose a valid workspace, key and progression.")
    if value.get("preset") not in {p["id"] for p in beats_for(category)}:
        raise ValueError("Choose a musical style for this category.")
    notes = value.get("notes", {})
    if not isinstance(notes, dict) or set(notes) - {"piano", "bass", "pad"}:
        raise ValueError("Invalid instrument pattern.")
    normalized = {}
    for part, events in notes.items():
        if not isinstance(events, list) or len(events) > 256:
            raise ValueError("Keep each instrument pattern under 257 notes.")
        normalized[part] = []
        occupied = set()
        for event in events:
            if not isinstance(event, dict) or not integer(event.get("step"), 0, 63) or not integer(event.get("midi"), 24, 84) or not integer(event.get("length"), 1, 16) or event["step"] + event["length"] > 64 or event["midi"] + value["key"] > 96:
                raise ValueError("Invalid note position, pitch or length.")
            identity = (event["step"], event["midi"])
            if identity in occupied:
                raise ValueError("Duplicate note in pattern.")
            occupied.add(identity)
            normalized[part].append({k: event[k] for k in ("step", "midi", "length")})
    drums = value.get("drums")
    if drums is not None:
        if not isinstance(drums, dict) or set(drums) - {"kick", "snare", "hat", "clap", "rim", "tom-low", "tom-mid", "tom-high"}:
            raise ValueError("Invalid drum pattern.")
        if any(not isinstance(hits, list) or len(hits) > 64 or any(not integer(hit, 0, 63) for hit in hits) or len(set(hits)) != len(hits) for hits in drums.values()):
            raise ValueError("Invalid drum steps.")
    levels = value.get("levels", {})
    if not isinstance(levels, dict) or set(levels) - {"drums", "piano", "bass", "pad"} or any(type(level) not in (float, int) or not 0 <= level <= 1 for level in levels.values()):
        raise ValueError("Set instrument volumes between zero and one.")
    result = {k: value[k] for k in ("schema", "bpm", "bars", "mode", "key", "progression", "preset")}
    result.update(notes=normalized, levels=levels)
    if drums is not None:
        result["drums"] = drums
    return result
