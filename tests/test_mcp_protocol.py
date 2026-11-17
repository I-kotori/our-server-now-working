"""Optional end-to-end stdio test. Run with requirements-mcp.txt installed."""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from test_mcp_tools import DATA

try:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    HAS_MCP=True
except ImportError:
    HAS_MCP=False


@unittest.skipUnless(HAS_MCP, 'Optional MCP SDK is not installed')
class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_and_readonly_calls(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                requests.append(self.path)
                payload=json.dumps(DATA).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        api=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=api.serve_forever,daemon=True);thread.start()
        params=StdioServerParameters(command=sys.executable,args=[str(Path(__file__).parents[1]/'mcp_server.py')],env={'STATUS_API_URL':f'http://127.0.0.1:{api.server_port}/api/status'})
        try:
            async with Client(params) as client:
                tools=(await client.list_tools()).tools
                self.assertEqual({t.name for t in tools},{'get_status','get_history','get_incidents'})
                self.assertTrue(all(t.annotations.read_only_hint for t in tools))
                status=await client.call_tool('get_status',{})
                self.assertFalse(status.is_error)
                self.assertEqual(status.structured_content['services'][0]['last'],990)
                for name,args in [('get_history',{'hours':168,'service':'ssh101'}),('get_incidents',{'service':'ssh101'})]:
                    self.assertFalse((await client.call_tool(name,args)).is_error)
                invalid=await client.call_tool('get_history',{'hours':12})
                self.assertTrue(invalid.is_error)
                self.assertEqual(requests,['/api/status'])
        finally:
            api.shutdown();api.server_close();thread.join()
