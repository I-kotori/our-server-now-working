import concurrent.futures
import http.client
import importlib.util
from pathlib import Path
import socket
import threading
import time
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('status_server',Path(__file__).parents[1]/'server.py')
app=importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class ServerTests(unittest.TestCase):
    def test_failure_ranges_group_and_recovery(self):
        self.assertEqual(app.failure_ranges([(10,1),(70,0),(130,0),(190,1),(250,0)]),[[70,190,'recovered'],[250,250,'open']])
        self.assertEqual(app.failure_ranges([(10,0),(500,0),(560,1)]),[[10,10,'gap'],[500,560,'recovered']])

    def test_aggregate_preserves_partial_failures_and_ranges(self):
        now=240*60
        samples=[(i*60,0 if i==100 else 1) for i in range(1,241)]
        view=app.aggregate(samples,now,24)
        self.assertLess(view['success'],100)
        ranges=[r for issue in view['issues'] for r in issue['ranges']]
        self.assertIn([6000,6060,'recovered'],ranges)
        self.assertEqual(len(view['issues']),24)

    def test_cache_coalesces_and_expires(self):
        calls=[]
        def build():
            calls.append(1); time.sleep(.01); return {'generated':len(calls)}
        cache=app.StatusCache(build,ttl=.05)
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            values=list(pool.map(lambda _:cache.get(),range(32)))
        self.assertEqual(len(calls),1)
        self.assertEqual(len(set(values)),1)
        time.sleep(.06)
        self.assertNotEqual(cache.get(),values[0])

    def test_failed_cache_build_retries(self):
        with patch.object(app,'status'):
            outcomes=iter([ValueError('offline'), {'services':[]}])
            def build():
                value=next(outcomes)
                if isinstance(value,Exception):raise value
                return value
            cache=app.StatusCache(build,retry_delay=.02)
            with self.assertRaises(app.CacheUnavailable):cache.get()
            with self.assertRaises(app.CacheUnavailable):cache.get()
            time.sleep(.03)
            self.assertIn(b'services',cache.get())

    def test_failure_coalescing_and_bounded_wait(self):
        calls=[]
        def fail():
            calls.append(1);time.sleep(.15);raise ValueError('locked')
        cache=app.StatusCache(fail,retry_delay=.1,wait_timeout=.03)
        def request(_):
            with self.assertRaises(app.CacheUnavailable):cache.get()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(request,range(8)))
        self.assertEqual(len(calls),1)
        request(0);self.assertEqual(len(calls),1)
        time.sleep(.11);cache.builder=lambda:{'recovered':True}
        self.assertIn(b'recovered',cache.get())
        entered, release = threading.Event(), threading.Event()
        def slow_success():
            entered.set();release.wait(3);return {'ok':True}
        bounded=app.StatusCache(slow_success,wait_timeout=.02)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            owner=pool.submit(bounded.get)
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaises(app.CacheUnavailable):bounded.get()
                self.assertFalse(owner.done())
            finally:
                release.set()
            self.assertIn(b'ok',owner.result(timeout=1))

    def test_http_limits_headers_and_privacy(self):
        server=app.BoundedHTTPServer(('127.0.0.1',0),app.Handler,max_connections=2)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        host,port=server.server_address
        def get(path,headers=None):
            conn=http.client.HTTPConnection(host,port,timeout=2)
            conn.request('GET',path,headers=headers or {})
            response=conn.getresponse();result=(response.status,dict(response.getheaders()),response.read());conn.close();return result
        try:
            with patch.object(app.STATUS_CACHE,'get',return_value=b'{"services":[]}'):
                status,headers,body=get('/api/status')
                self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-store')
            head=http.client.HTTPConnection(host,port,timeout=2);head.request('HEAD','/');response=head.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.read(),b'');head.close()
            status,headers,_=get('/')
            self.assertEqual(headers['Cache-Control'],'no-cache')
            self.assertEqual(get('/',{'If-None-Match':headers['ETag']})[0],304)
            for tag in ['W/'+headers['ETag'],'*','"different",'+headers['ETag']]:
                self.assertEqual(get('/',{'If-None-Match':tag})[0],304)
            status,headers,_=get('/favicon.svg')
            self.assertEqual(status,200);self.assertIn('max-age=86400',headers['Cache-Control'])
            self.assertEqual(get('/.env?token=SHOULD_NOT_LOG')[0],404)
            self.assertFalse(any('token' in k or '.env' in k for k in server.metrics))
            # Two incomplete requests consume exactly two bounded connections.
            sockets=[socket.create_connection((host,port),timeout=2) for _ in range(2)]
            for s in sockets:s.sendall(b'GET / HTTP/1.1\r\n')
            deadline=time.monotonic()+2
            while server.slots._value and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(get('/')[0],503)
            for s in sockets:s.close()
            time.sleep(.05)
            self.assertEqual(get('/')[0],200)
        finally:
            server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
