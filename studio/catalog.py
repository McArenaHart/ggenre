"""Shared V1 project workflows and original synthesized rhythm definitions."""
PROFILES = {
    "gospel": {"label": "Gospel", "description": "Worship, praise and congregational music", "tempo": 90, "record_label": "Record vocal", "import_title": "Bring in your sound", "import_hint": "Import a vocal or instrumental", "parts": ["Lead vocal", "Backing choir", "Congregation", "Harmony"], "beat_heading": "Gospel rhythm presets"},
    "acapella": {"label": "Acapella", "description": "Voices, harmonies and vocal percussion only", "tempo": 80, "record_label": "Record voice", "import_title": "Add a vocal recording", "import_hint": "Lead, harmony, bass or vocal percussion", "parts": ["Lead voice", "Harmony", "Soprano", "Alto", "Tenor", "Bass voice", "Vocal percussion"], "beat_heading": ""},
    "secular": {"label": "Circular / Secular", "description": "R&B, hip-hop and contemporary rhythms", "tempo": 92, "record_label": "Record vocal", "import_title": "Bring in your sound", "import_hint": "Import a beat, vocal or instrumental", "parts": ["Lead vocal", "Harmony", "Backing vocal", "Ad-libs"], "beat_heading": "Circular / secular rhythm presets"},
}

BEATS = [
    {"id": "gospel-worship", "category": "gospel", "name": "Worship", "description": "Gentle kick, snare and steady eighth-note hats", "bpm": 72, "swing": 0, "pattern": {"kick": [0,8], "snare": [4,12], "hat": [0,2,4,6,8,10,12,14]}},
    {"id": "gospel-praise", "fill": {"tom-high": [12, 13], "tom-mid": [14], "tom-low": [15]}, "category": "gospel", "name": "Praise", "description": "An energetic, syncopated praise rhythm", "bpm": 112, "swing": 0, "pattern": {"kick": [0,6,8,10], "snare": [4,12], "clap": [4,12], "hat": [0,2,4,6,8,10,12,14]}},
    {"id": "gospel-congregation", "category": "gospel", "name": "Congregational", "description": "A simple pulse for group singing", "bpm": 90, "swing": 0, "pattern": {"kick": [0,8], "clap": [4,12], "hat": [0,4,8,12]}},
    {"id": "secular-rnb", "category": "secular", "name": "R&B pocket", "description": "A relaxed groove with lightly swung hats", "bpm": 82, "swing": .12, "pattern": {"kick": [0,7,10], "snare": [4,12], "hat": [0,2,4,6,8,10,12,14]}},
    {"id": "secular-hiphop", "fill": {"tom-high": [13], "tom-mid": [14], "tom-low": [15]}, "category": "secular", "name": "Hip-hop", "description": "A clear backbeat with syncopated kicks", "bpm": 92, "swing": .04, "pattern": {"kick": [0,6,8,11], "snare": [4,12], "hat": [0,2,4,6,8,10,12,14]}},
    {"id": "secular-afropop", "category": "secular", "name": "Contemporary bounce", "description": "Interlocking kick, rim and hat patterns", "bpm": 104, "swing": 0, "pattern": {"kick": [0,6,8,14], "rim": [3,7,11,15], "clap": [4,12], "hat": [0,2,4,6,8,10,12,14]}},
]

def profile_for(category):
    return PROFILES[category]

def beats_for(category):
    return [beat for beat in BEATS if beat["category"] == category]


REFERENCE_NOTES = [{"midi": midi, "label": ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"][midi % 12] + str(midi // 12 - 1)} for midi in range(48, 73)]
