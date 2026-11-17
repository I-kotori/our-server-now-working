"""Read-only adapter for an existing status API. Never starts monitor workers."""
import json
import threading
import time
import urllib.request
from urllib.parse import urlsplit


class StatusReader:
    def __init__(self, url='http://127.0.0.1:9085/api/status', ttl=5):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('STATUS_API_URL must be an HTTP(S) API URL without credentials, query or fragment')
        self.url, self.ttl = url, ttl
        self.lock = threading.Lock()
        self.data, self.expires, self.retry_at = None, 0, 0

    def snapshot(self):
        if not self.lock.acquire(timeout=.25):
            raise RuntimeError('Status API lookup is busy. Try again shortly.')
        try:
            now = time.monotonic()
            if now < self.retry_at:
                raise RuntimeError('Status API unavailable. Try again shortly.')
            if self.data is None or now >= self.expires:
                try:
                    request = urllib.request.Request(self.url, headers={'Accept': 'application/json', 'User-Agent': 'ServiceStatusMCP/1.0'})
                    with urllib.request.urlopen(request, timeout=5) as response:
                        body = response.read(262145)
                    if len(body) > 262144:
                        raise ValueError('Response too large')
                    data = json.loads(body)
                    if not isinstance(data, dict) or type(data.get('generated')) is not int or not isinstance(data.get('services'), list) or not isinstance(data.get('incidents'), list):
                        raise ValueError('Invalid status response')
                    for s in data['services']:
                        if not isinstance(s, dict) or not all(k in s for k in ('id', 'name', 'state', 'last', 'ms', 'views')) or s['state'] not in ('up', 'down', 'checking', 'unknown'):
                            raise ValueError('Invalid service')
                    self.data, self.expires = data, time.monotonic() + self.ttl
                except Exception:
                    self.retry_at = time.monotonic() + 2
                    raise RuntimeError('Status API unavailable or returned invalid data. No fresh status can be reported.') from None
            return self.data
        finally:
            self.lock.release()

    @staticmethod
    def select(data, service):
        selected = [s for s in data['services'] if service == 'all' or s['id'] == service]
        if not selected:
            raise ValueError('Unknown service ID. Use get_status to discover available IDs.')
        return selected

    def get_status(self):
        data = self.snapshot()
        return {'generated': data['generated'], 'time_unit': 'Unix seconds', 'display_timezone': 'Asia/Seoul',
                'meaning': 'Previously observed connectivity, not an on-demand check or a login test.',
                'services': [{k: s[k] for k in ('id', 'name', 'state', 'last', 'ms')} for s in data['services']]}

    def get_history(self, hours=24, service='all'):
        if type(hours) is not int or hours not in (1, 24, 168):
            raise ValueError('hours must be 1, 24 or 168')
        data = self.snapshot()
        selected = self.select(data, service)
        return {'generated': data['generated'], 'hours': hours, 'time_unit': 'Unix seconds', 'display_timezone': 'Asia/Seoul',
                'meaning': 'Success is successful checks / completed checks. Issue ranges are observations; gaps are unknown.',
                'bar_fields': ['checks', 'successful_checks', 'record_gap'],
                'issue_range_fields': ['first_failed_check', 'end_observation', 'end_kind'],
                'end_kinds': {'recovered': 'end is next successful check', 'open': 'end is last failed check; no recovery confirmed', 'gap': 'end is last failed check before a recording gap'},
                'services': [{'id': s['id'], 'name': s['name'], 'history': s['views'][str(hours)]} for s in selected]}

    def get_incidents(self, service='all'):
        data = self.snapshot()
        selected = self.select(data, service)
        names = {s['name'] for s in selected}
        return {'generated': data['generated'], 'time_unit': 'Unix seconds', 'display_timezone': 'Asia/Seoul',
                'meaning': 'Confirmed incidents require three consecutive failed checks. Shorter failures appear in get_history.',
                'incidents': [i for i in data['incidents'] if i['name'] in names]}
