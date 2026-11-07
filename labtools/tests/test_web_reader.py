import http.server,json,signal,subprocess,sys,tempfile,threading,unittest
from pathlib import Path

class WebReaderTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.token='a'*64;self.token_file=Path(self.folder.name)/'token.secret';self.token_file.write_text(self.token);self.status=200;self.body=b'{}';self.auth=[]
        fixture=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                fixture.auth.append(self.headers.get('Authorization')=='Bearer '+fixture.token)
                self.send_response(fixture.status);self.send_header('Content-Length',str(len(fixture.body)));self.end_headers();self.wfile.write(fixture.body)
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True;self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.addCleanup(self.close_server)
    def close_server(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def argv(self):return [sys.executable,'-m','sdwan_lab.web_reader','--url','http://127.0.0.1:'+str(self.server.server_port),'--source','127.0.0.1','--token-file',str(self.token_file)]
    def test_http_rejection_reports_status_per_path_without_token(self):
        self.status=403;result=subprocess.run(self.argv(),capture_output=True,text=True,timeout=5);self.assertEqual(result.returncode,1)
        report=json.loads(result.stdout);self.assertEqual(report['errors'],3);self.assertTrue(all(v['status']==403 for v in report['errors_by_path'].values()));self.assertNotIn(self.token,result.stdout+result.stderr);self.assertEqual(self.auth,[True]*3)
    def test_invalid_json_is_distinguished_from_http_rejection(self):
        self.body=b'not-json';result=subprocess.run(self.argv(),capture_output=True,text=True,timeout=5);report=json.loads(result.stdout)
        self.assertEqual(result.returncode,1);self.assertTrue(all(v['kind']=='JSONDecodeError' and 'status' not in v for v in report['errors_by_path'].values()))
    def test_successful_reader_stops_with_a_complete_summary(self):
        child=subprocess.Popen(self.argv(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready');child.send_signal(signal.SIGTERM);out,err=child.communicate(timeout=3)
            report=json.loads(out);self.assertEqual(child.returncode,0,err);self.assertEqual(report['errors'],0);self.assertGreaterEqual(report['requests'],3);self.assertTrue(all(self.auth));self.assertNotIn(self.token,out+err)
        finally:
            if child.poll() is None:child.kill();child.communicate(timeout=2)
            child.stdout.close();child.stderr.close()
