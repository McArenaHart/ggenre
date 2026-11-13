"""Loopback-only synthetic Studio fixture; never writes application data."""
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ggenre.settings')
import django
django.setup()
from django.template.loader import render_to_string
from studio.catalog import profile_for, beats_for

raw = io.BytesIO()
with wave.open(raw, 'wb') as audio:
    audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
    audio.writeframes(b'\x10\x27' * 48000)
removed = False
rendered = False


class Handler(BaseHTTPRequestHandler):
    def send(self, data, mime='application/json'):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/':
            project = SimpleNamespace(pk=1, title='Portable Studio QA', category='gospel', tempo=90, mix=rendered, pending_render=None, removed_tracks=[{'id': 1, 'name': 'Synthetic vocal'}] if removed else [], storage_used=.1, storage_limit=1024)
            tracks = [] if removed else [{'id': 1, 'name': 'Synthetic vocal', 'kind': 'vocal', 'gain': 1, 'offset': 0, 'trim_start': 0, 'trim_end': 0, 'muted': False, 'url': '/source.wav'}]
            self.send(render_to_string('studio/editor.html', {'project': project, 'tracks': tracks, 'revision': 'qa', 'free_left': 2, 'profile': profile_for('gospel'), 'beats': beats_for('gospel'), 'csrf_token': 'synthetic-qa-only'}).encode(), 'text/html; charset=utf-8')
        elif path.endswith('/peaks/'):
            self.send({'duration': 6, 'peaks': [.3] * 1600})
        elif path == '/studio/audio-jobs/7/':
            self.send({'id': 7, 'status': 'ready', 'url': '/source.wav'})
        elif path == '/source.wav':
            self.send(raw.getvalue(), 'audio/wav')
        elif path.startswith('/static/'):
            asset = (ROOT / path.lstrip('/')).resolve()
            if not asset.is_relative_to(ROOT / 'static') or not asset.is_file():
                self.send_error(404)
                return
            mime = 'text/javascript' if asset.suffix == '.js' else 'text/css' if asset.suffix == '.css' else 'application/octet-stream'
            self.send(asset.read_bytes(), mime)
        else:
            self.send_error(404)

    def do_POST(self):
        global removed, rendered
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path.endswith('/delete/'):
            removed = True
        elif self.path.endswith('/restore/'):
            removed = False
        elif self.path.endswith('/apply/'):
            rendered = True
        self.send({'ok': True, 'id': 7, 'status': 'queued', 'revision': 'qa'})


HTTPServer(('127.0.0.1', 8766), Handler).serve_forever()
