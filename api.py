# -*- coding: utf-8 -*-
# 외부 업체의 이벤트를 수신하는 로컬 HTTP API입니다.
# 주석 추가 버전: 기존 실행 로직과 설정값은 변경하지 않았습니다.

from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
import json,threading

# 기능별 관리 객체
class Api:
    # 이벤트 저장소를 연결하고 요청별 Handler를 생성합니다.
    def __init__(self,store,host,port,token=''):
        self.store=store; self.token=token
        outer=self
        # 기능별 관리 객체
        class Handler(BaseHTTPRequestHandler):
            # HTTP 응답을 UTF-8 JSON으로 직렬화합니다.
            def send_json(self,status,obj):
                b=json.dumps(obj,ensure_ascii=False).encode('utf8');self.send_response(status)
                self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)))
                self.end_headers();self.wfile.write(b)
            # 설정된 API 키가 있을 때 X-API-Key 헤더를 검사합니다.
            def auth(self):
                if outer.token and self.headers.get('X-API-Key')!=outer.token:
                    self.send_json(401,{'error':'invalid API key'});return False
                return True
            # 상태/세션/최근 이벤트 조회를 처리합니다.
            def do_GET(self):
                if not self.auth(): return
                route=urlparse(self.path)
                if route.path=='/health': self.send_json(200,{'status':'ok','session_id':outer.store.session_id});return
                if route.path=='/api/v1/session':
                    self.send_json(200,json.loads((outer.store.base/'metadata/session.json').read_text(encoding='utf8')));return
                if route.path=='/api/v1/events':
                    try: limit=min(1000,max(1,int(parse_qs(route.query).get('limit',['100'])[0])))
                    except ValueError: limit=100
                    with outer.store.lock:
                        lines=outer.store.events.read_text(encoding='utf8').splitlines() if outer.store.events.exists() else []
                    self.send_json(200,{'session_id':outer.store.session_id,'events':[json.loads(s) for s in lines[-limit:]]});return
                self.send_json(404,{'error':'not found'})
            # 외부 JSON 이벤트를 받아 events.jsonl에 저장합니다.
            def do_POST(self):
                if not self.auth(): return
                if urlparse(self.path).path!='/api/v1/events': self.send_json(404,{'error':'not found'});return
                try:
                    n=int(self.headers.get('Content-Length','0'))
                    if n<=0 or n>65536: self.send_json(413,{'error':'invalid size'});return
                    obj=json.loads(self.rfile.read(n));event=outer.store.event(obj)
                    self.send_json(201,event)
                except (ValueError,TypeError) as e: self.send_json(400,{'error':str(e)})
            # 기본 HTTP 요청 로그를 숨깁니다.
            def log_message(self,*args): pass
        self.server=ThreadingHTTPServer((host,int(port)),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    # API 서버 스레드를 시작합니다.
    def start(self): self.thread.start()
    # 서버를 안전하게 종료합니다.
    def stop(self): self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
