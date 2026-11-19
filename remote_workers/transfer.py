"""Bounded file transfers between a GPU worker and one authorized GGenre job."""
import http.client
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

MAX_BYTES = 64 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_payload(payload, origin):
    base = urlsplit(origin)
    if base.scheme != 'https' or not base.hostname or base.path not in ('', '/'):
        raise ValueError('Configure the public GGenre HTTPS origin.')
    if not isinstance(payload, dict) or type(payload.get('job_id')) is not int or payload['job_id'] <= 0:
        raise ValueError('Invalid job.')
    for action in ('source', 'control', 'result'):
        url = urlsplit(payload.get(action + '_url', ''))
        if url.scheme != 'https' or url.netloc != base.netloc or url.path != f'/studio/remote-audio/{payload["job_id"]}/{action}/' or url.query or url.fragment or url.username:
            raise ValueError('Worker transfers must use the configured GGenre job endpoints.')
        token = payload.get('tokens', {}).get(action, '')
        if not isinstance(token, str) or not 20 <= len(token) <= 2048:
            raise ValueError('Missing job authorization.')


def active(payload):
    request = Request(payload['control_url'], headers={'X-GGenre-Job-Token': payload['tokens']['control']})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        return json.loads(response.read(4096)).get('active') is True


def download(payload, destination):
    request = Request(payload['source_url'], headers={'X-GGenre-Job-Token': payload['tokens']['source']})
    with build_opener(NoRedirect()).open(request, timeout=60) as response, Path(destination).open('wb') as target:
        count = 0
        while block := response.read(65536):
            count += len(block)
            if count > MAX_BYTES:
                raise ValueError('The source exceeds the audio limit.')
            target.write(block)


def upload(payload, source=None):
    url = urlsplit(payload['result_url'])
    connection = http.client.HTTPSConnection(url.hostname, url.port, timeout=60)
    headers = {'X-GGenre-Job-Token': payload['tokens']['result']}
    try:
        if source:
            size = Path(source).stat().st_size
            if not 44 <= size <= MAX_BYTES:
                raise ValueError('The result exceeds the audio limit.')
            headers.update({'Content-Type': 'audio/wav', 'Content-Length': str(size)})
            with Path(source).open('rb') as stream:
                connection.request('PUT', url.path, body=stream, headers=headers)
        else:
            body = b'{"failed":true}'
            headers.update({'Content-Type': 'application/json', 'Content-Length': str(len(body))})
            connection.request('PUT', url.path, body=body, headers=headers)
        response = connection.getresponse()
        response.read(4096)
        if response.status != 200:
            raise ValueError('GGenre refused the result; the task may no longer be active.')
    finally:
        connection.close()
