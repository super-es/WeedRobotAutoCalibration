# -*- coding: utf-8 -*-
# 세션 폴더 생성 및 JSON/JSONL 저장 모듈입니다.
# 주석 추가 버전: 기존 실행 로직과 설정값은 변경하지 않았습니다.

import json, os, threading, datetime, pathlib, uuid

# 현재 시간을 시간대 포함 ISO 8601 밀리초 형식으로 반환합니다.
def iso_now(): return datetime.datetime.now().astimezone().isoformat(timespec='milliseconds')

# 기능별 관리 객체
class Store:
    # 세션별 녹화·이미지·메타데이터 폴더를 생성합니다.
    def __init__(self,root,session_id):
        self.session_id=session_id; self.base=pathlib.Path(root)/session_id; self.lock=threading.RLock()
        for d in ('rec','images/rgb','images/depth','images/depth_color','images/ir','metadata'): (self.base/d).mkdir(parents=True,exist_ok=True)
        self.events=self.base/'metadata/events.jsonl';self.frames=self.base/'metadata/frames.jsonl';self.segments=[];self.frame_index=0
        self.write_manifest()
    # session.json을 임시 파일로 작성한 뒤 원자적으로 교체합니다.
    def write_manifest(self):
        obj={'schema_version':'1.0','session_id':self.session_id,'started_at':self.session_id,'recordings':self.segments,'events_file':'metadata/events.jsonl','frames_file':'metadata/frames.jsonl','image_folders':{'rgb':'images/rgb','depth_raw':'images/depth','depth_preview':'images/depth_color','ir':'images/ir'},'notes':'Depth PNG is 16-bit raw depth, not meters. Use depth_scale_m_per_unit in frame metadata.'}
        tmp=self.base/'metadata/session.tmp';tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8');os.replace(tmp,self.base/'metadata/session.json')
    # 여러 스레드가 충돌하지 않도록 잠금 후 JSONL 한 줄을 추가합니다.
    def append(self,file,obj):
        with self.lock:
            with file.open('a',encoding='utf8') as f: f.write(json.dumps(obj,ensure_ascii=False)+'\n');f.flush()
    # 이벤트 타입을 검증하고 공통 메타데이터를 붙여 기록합니다.
    def event(self,body):
        if not isinstance(body,dict): raise ValueError('JSON object required')
        # 지원 이벤트 종류만 수신합니다. 새 turn_start/turn_end 도입 시 allowed 확장이 필요합니다.
        typ=body.get('type'); allowed={'drive_start','weed_detected','nozzle_fired','wheel_telemetry','gps_update','imu_update','drive_stop','custom'}
        if typ not in allowed: raise ValueError('unsupported type')
        event={'schema_version':'1.0','event_id':uuid.uuid4().hex,'session_id':self.session_id,'type':typ,'source':str(body.get('source','unknown')),'timestamp':str(body.get('timestamp') or iso_now()),'received_at':iso_now(),'data':body.get('data') if isinstance(body.get('data'),dict) else {}}
        self.append(self.events,event)
        # 잡초/살포 이벤트는 JSONL 외에 개별 JSON도 별도 보관합니다.
        if typ in {'weed_detected','nozzle_fired'}:
            path=self.base/'metadata'/f'{typ}_{event["received_at"].replace(":","").replace("+","p")}_{event["event_id"][:8]}.json'
            path.write_text(json.dumps(event,ensure_ascii=False,indent=2),encoding='utf8')
        return event
    # 이미지 프레임 정보를 frames.jsonl에 기록합니다.
    def frame(self,obj): self.append(self.frames,obj)
