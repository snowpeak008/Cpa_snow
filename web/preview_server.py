"""Loopback-only UI preview. Synthetic data; cannot reach production or models."""
import argparse
import datetime
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**k):super().__init__(*a,directory=str(ROOT),**k)
    def json(self,data,status=200):
        body=json.dumps(data).encode();self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-CPA-Version','v8.0.31')
        self.send_header('X-CPA-Support-Plugin','true')
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        path=urlsplit(self.path).path
        if path.startswith(('/v8/management','/v0/management')):
            key=path.split('/management',1)[1]
            if key=='/config.yaml':
                body=b'port: 8317\ndebug: false\nplugins:\n  enabled: true\n  entries:\n    account-concurrency:\n      enabled: true\n      config:\n        max_per_key: 5\n        max_per_account: 2\nrouting:\n  strategy: round-robin\n'
                self.send_response(200);self.send_header('Content-Type','text/plain');self.end_headers();self.wfile.write(body);return
            if key=='/config':return self.json({'server':{'port':8317},'access':{'api-keys':[]},'plugins':{'enabled':True},'routing':{'strategy':'round-robin'},'observability':{'logs':{'request-log':False}},'oauth':{'excluded-models':{}},'api-keys':{}})
            if key=='/credentials':return self.json({'files':[],'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
            if key=='/plugins':return self.json({'plugins_enabled':True,'plugins_dir':'plugins','plugins':[]})
            if key.endswith('/errors'):return self.json({'files':[]})
            if key=='/observability/usage/api-keys':return self.json({})
            if 'logs' in key:return self.json({'lines':[],'latest-timestamp':0})
            if 'usage' in key:return self.json({'usage':{'total_requests':0,'success_count':0,'failure_count':0,'total_tokens':0,'apis':{}},'api_keys':[]})
            if key=='/server/latest-version':return self.json({'latest-version':'v8.0.31'})
            return self.json({})
        if path=='/v1/models':return self.json({'object':'list','data':[]})
        if path=='/':self.path='/management.html'
        if path in ('/','/management.html'):
            html=(ROOT/'management.html').read_text(encoding='utf-8')
            notice='<div style="position:fixed;bottom:12px;right:18px;z-index:99999;background:#1a3340;border:1px solid #42616d;border-radius:7px;padding:7px 12px;color:#b8d1dd;font:12px Segoe UI,sans-serif;pointer-events:none">本地预览 · 演示数据 · 未连接生产</div>'
            body=html.replace('</body>',notice+'</body>').encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        return super().do_GET()
    def do_POST(self):self.json({'error':'Preview only; writes disabled'},403)
    do_PUT=do_PATCH=do_DELETE=do_POST
    def log_message(self,fmt,*args):print(fmt%args,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18732);a=p.parse_args()
    print('Snow Console preview: http://127.0.0.1:%s/management.html'%a.port,flush=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
