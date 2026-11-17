import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('mcp_tools',Path(__file__).parents[1]/'mcp_tools.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
DATA={'generated':1000,'services':[{'id':'ssh101','name':'Port 101','state':'up','last':990,'ms':4,'views':{str(h):{'bars':[[1,1,False]],'issues':[],'success':100} for h in (1,24,168)}}], 'incidents':[{'name':'Port 101','started':500,'ended':600}]}

class ReaderTests(unittest.TestCase):
    def test_tools_share_one_api_read_and_filter(self):
        reader=module.StatusReader()
        with patch.object(module.urllib.request,'urlopen',side_effect=lambda *a,**k:io.BytesIO(json.dumps(DATA).encode())) as fetch:
            self.assertEqual(reader.get_status()['services'][0]['last'],990)
            self.assertEqual(reader.get_history(168,'ssh101')['hours'],168)
            self.assertEqual(len(reader.get_incidents('ssh101')['incidents']),1)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(fetch.call_args.args[0].full_url,'http://127.0.0.1:9085/api/status')
            with self.assertRaises(ValueError):reader.get_history(2)
            with self.assertRaises(ValueError):reader.get_history(24,'unknown')
            self.assertEqual(fetch.call_count,1)

    def test_outage_never_returns_stale_success_and_throttles(self):
        reader=module.StatusReader(ttl=0)
        with patch.object(module.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(DATA).encode())):reader.get_status()
        with patch.object(module.urllib.request,'urlopen',side_effect=OSError('secret upstream address')) as fetch:
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError,'unavailable') as error:reader.get_status()
                self.assertNotIn('secret',str(error.exception))
            self.assertEqual(fetch.call_count,1)

    def test_invalid_data_and_oversized_response(self):
        for body in [b'not json',b'{}',b'x'*262145]:
            with patch.object(module.urllib.request,'urlopen',return_value=io.BytesIO(body)):
                with self.assertRaises(RuntimeError):module.StatusReader().get_status()
        for url in ['file:///etc/passwd','https://u:p@example.com/api','https://example.com/api?token=secret']:
            with self.assertRaises(ValueError):module.StatusReader(url)
