"""Bounded, authenticated-route audio streaming with single byte ranges."""
import re
from django.http import FileResponse, HttpResponse, StreamingHttpResponse


def deliver(audio, request=None, attachment=False, filename=None):
    size = audio.size
    raw = request.headers.get('Range', '') if request else ''
    if raw and not attachment:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', raw)
        try:
            if not match or not any(match.groups()):
                raise ValueError()
            first, last = match.groups()
            start = int(first) if first else max(0, size - int(last))
            end = min(size - 1, int(last)) if first and last else size - 1
            if start > end or start >= size:
                raise ValueError()
        except ValueError:
            response = HttpResponse(status=416)
            response['Content-Range'] = f'bytes */{size}'
        else:
            def chunks():
                with audio.open('rb') as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        block = stream.read(min(65536, remaining))
                        if not block:
                            break
                        remaining -= len(block)
                        yield block
            response = StreamingHttpResponse(chunks(), status=206, content_type='audio/wav')
            response['Content-Range'] = f'bytes {start}-{end}/{size}'
            response['Content-Length'] = end - start + 1
    else:
        response = FileResponse(audio.open('rb'), content_type='audio/wav', as_attachment=attachment, filename=filename)
    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
