"""Loopback-only UI fixture using synthetic audio, with no application DB writes."""
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ggenre.settings')
import django
django.setup()
from django.template.loader import render_to_string
from django.test import RequestFactory

config = {'crossfade_ms': 20, 'sections': [{'start': i * 2, 'end': (i + 1) * 2, 'gain': 1} for i in range(3)]}
title = 'Synthetic arrangement QA'
raw = io.BytesIO()
with wave.open(raw, 'wb') as audio:
    audio.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
    audio.writeframes(b''.join(struct.pack('<h', int(10000 * math.sin(2 * math.pi * [220, 330, 440][i // 88200] * i / 44100))) for i in range(264600)))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/':
            data = render_to_string('studio/extract_arrangement.html', {'title': title, 'config': config, 'source_url': '/source.wav', 'save_url': '/save/', 'revision': 'qa', 'sample_rate': 44100, 'csrf_token': 'qa-only'}).encode()
            mime = 'text/html; charset=utf-8'
        elif path == '/source.wav':
            data, mime = raw.getvalue(), 'audio/wav'
        elif path.startswith('/static/'):
            file = (ROOT / path.lstrip('/')).resolve()
            if not file.is_relative_to(ROOT / 'static') or not file.is_file():
                self.send_error(404); return
            import mimetypes
            data, mime = file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Type', mime); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        global config, title
        if self.path != '/save/':
            self.send_error(404); return
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        request = RequestFactory().generic('POST', self.path, body, content_type=self.headers['Content-Type'])
        config, title = json.loads(request.POST['config']), request.POST['title']
        data = json.dumps({'ok': True, 'url': '/?saved=1'}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)


if __name__ == '__main__':
    print('Synthetic UI fixture: http://127.0.0.1:8765', flush=True)
    HTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
