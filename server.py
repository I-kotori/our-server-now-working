import json, os, socket, sqlite3, threading, time, urllib.request, logging, subprocess, sys, hashlib
from collections import Counter
from contextlib import contextmanager, closing
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DB=os.environ.get('STATUS_DB',str(ROOT/'status.db'))
TARGETS=[('ssh101','포트 101'),('ssh102','포트 102'),('eclass','이클래스')]
RETENTION=7*86400

def connect():
    db=sqlite3.connect(DB,timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS checks (target TEXT, ts INTEGER, ok INTEGER, ms INTEGER)')
        db.execute('CREATE INDEX IF NOT EXISTS checks_target_ts ON checks(target,ts)')
        db.execute('CREATE TABLE IF NOT EXISTS incidents (id INTEGER PRIMARY KEY, target TEXT, started INTEGER, ended INTEGER)')
    except BaseException:
        db.close()
        raise
    return db

@contextmanager
def database():
    with closing(connect()) as db:
        with db:
            yield db

def raw_probe(target):
    start=time.monotonic()
    try:
        if target.startswith('ssh'):
            with socket.create_connection(('cs.dongguk.edu',int(target[3:])),timeout=5): pass
        else:
            request=urllib.request.Request('https://eclass.dongguk.edu',headers={'User-Agent':'DonggukStatus/1.0'})
            with urllib.request.urlopen(request,timeout=5) as response:
                if not 200<=response.status<400: raise ValueError('HTTP error')
        return 1,round((time.monotonic()-start)*1000)
    except (OSError,ValueError,HTTPException): return 0,None

def probe(target):
    try:
        result=subprocess.run([sys.executable,str(ROOT/'server.py'),'--probe',target],capture_output=True,text=True,timeout=5,check=True)
        ok,ms=json.loads(result.stdout)
        return int(bool(ok)),ms
    except (subprocess.SubprocessError,ValueError,OSError):
        return 0,None

def failure_ranges(samples):
    """Observed failed runs, ending at the next successful check if known."""
    result=[]
    start=last=None
    for ts,ok in samples:
        if start is not None and ts-last>420:
            result.append([start,last,'gap'])
            start=last=None
        if ok:
            if start is not None:
                result.append([start,ts,'recovered'])
                start=last=None
        else:
            if start is None:start=ts
            last=ts
    if start is not None:result.append([start,last,'open'])
    return result


def aggregate(samples,now,hours):
    count={1:60,24:24,168:42}[hours]
    step=hours*3600/count
    start=now-hours*3600
    buckets=[[] for _ in range(count)]
    gaps=[(a[0],b[0]) for a,b in zip(samples,samples[1:]) if b[0]-a[0]>420]
    for ts,ok in samples:
        if start<=ts<=now:
            buckets[min(count-1,int((ts-start)/step))].append((ts,ok))
    bars=[]
    details=[]
    runs=failure_ranges(samples)
    for i,items in enumerate(buckets):
        begin=start+i*step; end=begin+step
        missing=any(a<end and b>begin for a,b in gaps) or bool(items and (items[0][0]-begin>420 or end-items[-1][0]>420))
        bars.append([len(items),sum(ok for _,ok in items),bool(missing)])
        matching=[r for r in runs if r[0]<end and (r[1]>begin or r[0]>=begin)]
        details.append({'ranges':matching[:3],'more':max(0,len(matching)-3)})
    total=sum(b[0] for b in bars); successes=sum(b[1] for b in bars)
    return {'bars':bars,'issues':details,'success':min(99.99,round(100*successes/total,2)) if total and successes<total else 100.0 if total else None}

def record(target,ok,ms,now):
    with database() as db:
        db.execute('INSERT INTO checks VALUES (?,?,?,?)',(target,now,ok,ms))
        active=db.execute('SELECT id FROM incidents WHERE target=? AND ended IS NULL ORDER BY id DESC LIMIT 1',(target,)).fetchone()
        if ok and active: db.execute('UPDATE incidents SET ended=? WHERE id=?',(now,active[0]))
        if not ok and not active:
            recent=db.execute('SELECT ts,ok FROM checks WHERE target=? ORDER BY ts DESC LIMIT 3',(target,)).fetchall()
            if len(recent)==3 and not any(row[1] for row in recent) and recent[0][0]-recent[-1][0]<=180:
                db.execute('INSERT INTO incidents(target,started) VALUES (?,?)',(target,recent[-1][0]))
        return bool(db.execute('SELECT 1 FROM incidents WHERE target=? AND ended IS NULL',(target,)).fetchone())

def worker(target):
    failures=0
    while True:
        started=time.monotonic()
        try:
            ok,ms=probe(target); now=int(time.time()); confirmed=record(target,ok,ms,now)
        except Exception:
            logging.exception("모니터링 오류: %s", target)
            failures=0
            time.sleep(60)
            continue
        failures=0 if ok else failures+1
        interval=60 if not confirmed else min(300,60*2**max(0,min(failures-2,3)))
        time.sleep(max(1,interval-(time.monotonic()-started)))

def cleanup():
    while True:
        try:
            with database() as db:
                cutoff=int(time.time())-RETENTION
                db.execute('DELETE FROM checks WHERE ts < ?',(cutoff,))
                db.execute('DELETE FROM incidents WHERE ended IS NOT NULL AND ended < ?',(cutoff,))
        except Exception:
            logging.exception("기록 정리 오류")
            time.sleep(60)
            continue
        time.sleep(3600)

def status():
    now=int(time.time()); services=[]
    with database() as db:
        for key,name in TARGETS:
            recent=db.execute('SELECT ts,ok,ms FROM checks WHERE target=? ORDER BY ts DESC LIMIT 3',(key,)).fetchall()
            active=db.execute('SELECT 1 FROM incidents WHERE target=? AND ended IS NULL',(key,)).fetchone()
            state='unknown' if not recent or now-recent[0][0]>420 else ('up' if recent[0][1] else ('down' if active else 'checking'))
            samples=db.execute('SELECT ts,ok FROM checks WHERE target=? AND ts>=? ORDER BY ts',(key,now-RETENTION)).fetchall()
            services.append({'id':key,'name':name,'state':state,'last':recent[0][0] if recent else None,'ms':recent[0][2] if recent else None,'views':{str(h):aggregate(samples,now,h) for h in (1,24,168)}})
        incidents=[{'name':dict(TARGETS).get(t,t),'started':s,'ended':e} for t,s,e in db.execute('SELECT target,started,ended FROM incidents WHERE ended IS NULL OR ended>=? ORDER BY started DESC LIMIT 30',(now-RETENTION,))]
    return {'generated':now,'services':services,'incidents':incidents}

class CacheUnavailable(RuntimeError):
    pass


class StatusCache:
    """Share successes briefly and throttle failures without serving stale data."""
    def __init__(self, builder=status, ttl=5, retry_delay=2, wait_timeout=.25):
        self.builder, self.ttl = builder, ttl
        self.retry_delay, self.wait_timeout = retry_delay, wait_timeout
        self.lock = threading.Lock()
        self.payload, self.expires, self.retry_at = None, 0, 0

    def get(self):
        if not self.lock.acquire(timeout=self.wait_timeout):
            raise CacheUnavailable('aggregation busy')
        try:
            now = time.monotonic()
            if now < self.retry_at:
                raise CacheUnavailable('aggregation retry cooldown')
            if self.payload is None or now >= self.expires:
                try:
                    payload = json.dumps(self.builder(), ensure_ascii=False).encode()
                except Exception:
                    self.retry_at = time.monotonic() + self.retry_delay
                    logging.warning('status_aggregation_failed')
                    raise CacheUnavailable('aggregation failed') from None
                self.payload, self.expires = payload, time.monotonic() + self.ttl
                self.retry_at = 0
            return self.payload
        finally:
            self.lock.release()


STATUS_CACHE = StatusCache()
ICONS = frozenset(('/favicon.svg',))


class BoundedHTTPServer(ThreadingHTTPServer):
    request_queue_size = 32
    daemon_threads = True

    def __init__(self, address, handler, max_connections=16):
        self.slots = threading.BoundedSemaphore(max_connections)
        self.metrics_lock = threading.Lock()
        self.metrics = Counter()
        self.last_report = time.monotonic()
        super().__init__(address, handler)

    def observe(self, route, status_code, elapsed=0):
        # Fixed categories only: no IP, URL query, headers or arbitrary paths.
        with self.metrics_lock:
            self.metrics[f'{route}.{int(status_code)//100}xx'] += 1
            self.metrics['handler_ms_total'] += round(elapsed * 1000)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(10)
        return request, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.observe('overload', 503)
            try:
                request.settimeout(0.1)
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nRetry-After: 1\r\nConnection: close\r\n\r\n')
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        logging.error('http_request_failed')

    def service_actions(self):
        if time.monotonic() - self.last_report >= 300:
            with self.metrics_lock:
                counts = dict(self.metrics)
                self.metrics.clear()
            logging.warning('http_metrics interval_seconds=300 counts=%s', json.dumps(counts))
            self.last_report = time.monotonic()


class Handler(BaseHTTPRequestHandler):
    def version_string(self):
        return "Status"

    def log_message(self, format, *args):
        # BaseHTTPRequestHandler logs IPs and attacker-controlled paths by default.
        pass

    def log_request(self, code='-', size='-'):
        path = getattr(self, 'path', '').split('?', 1)[0]
        route = 'api' if path == '/api/status' else 'html' if path in ('/', '/index.html') else 'icon' if path in ICONS else 'other'
        self.server.observe(route, int(code), time.monotonic() - getattr(self, '_started', time.monotonic()))

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._started = time.monotonic()
        path = self.path.split('?', 1)[0]
        policy = 'no-cache'
        try:
            if path == '/api/status':
                data = STATUS_CACHE.get()
                kind, policy = 'application/json; charset=utf-8', 'no-store'
            elif path in ('/', '/index.html'):
                data, kind = (ROOT/'index.html').read_bytes(), 'text/html; charset=utf-8'
            elif path in ICONS:
                data = (ROOT/path[1:]).read_bytes()
                kind = 'image/svg+xml'
                policy = 'public, max-age=86400'
            else:
                self.send_error(404)
                return
        except CacheUnavailable:
            self.send_error(503)
            return
        except Exception:
            logging.exception('response_build_failed')
            self.send_error(503)
            return
        etag = '"' + hashlib.sha256(data).hexdigest() + '"' if policy != 'no-store' else None
        not_modified = etag is not None and any(tag.strip() == '*' or tag.strip().removeprefix('W/') == etag for tag in self.headers.get('If-None-Match', '').split(','))
        self.send_response(304 if not_modified else 200)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', policy)
        self.send_header('X-Content-Type-Options', 'nosniff')
        if etag:
            self.send_header('ETag', etag)
        if not not_modified:
            self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if not not_modified and self.command != 'HEAD':
            try:
                self.wfile.write(data)
            except (OSError, TimeoutError):
                pass

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--probe':
        if sys.argv[2] not in dict(TARGETS): sys.exit(2)
        print(json.dumps(raw_probe(sys.argv[2])))
        sys.exit(0)
    with database(): pass
    for key,_ in TARGETS: threading.Thread(target=worker,args=(key,),daemon=True).start()
    threading.Thread(target=cleanup,daemon=True).start()
    BoundedHTTPServer(('127.0.0.1',int(os.environ.get('PORT','9085'))),Handler).serve_forever()
