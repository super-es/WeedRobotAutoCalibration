# -*- coding: utf-8 -*-
# 실제 업체 데이터 연동 전, 5초 간격의 가상 잡초/노즐 이벤트를 만듭니다.
# 주석 추가 버전: 기존 실행 로직과 설정값은 변경하지 않았습니다.

import threading,time,random,datetime

# 시뮬레이션 이벤트의 타임스탬프를 생성합니다.
def now():return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")
# 기능별 관리 객체
class Simulator:
    # 시드 기반 난수와 가상 바퀴 회전수를 초기화합니다.
    def __init__(self,store,cfg):
        self.store=store;self.cfg=cfg;self.stop_event=threading.Event();self.thread=None
        self.rng=random.Random(cfg.get("seed",42));self.rotation=0;self.started_at=now()
    # simulation.enabled=true일 때만 백그라운드 생성기를 실행합니다.
    def start(self):
        if not self.cfg.get("enabled",False):return
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
    # 가상 잡초와 노즐 이벤트를 생성합니다. 실제 ㄹ자 주행 궤적은 모사하지 않습니다.
    def loop(self):
        interval=max(.1,float(self.cfg.get("interval_seconds",5)))
        while not self.stop_event.is_set():
            ts=now();self.rotation+=self.rng.randint(1,5)
            gps={"latitude":None,"longitude":None,"fix_valid":False,"simulated":True}
            # curve_direction은 무작위 값으로, 실제 회전 지속시간을 뜻하지 않습니다.
            motion={"wheel_rotation_count":self.rotation,"wheel_rotation_started_at":self.started_at,"wheel_rotation_ended_at":ts,"curve_direction":self.rng.choice(["straight","left","right"]),"gps":gps}
            grid=self.rng.randint(1,24)
            self.store.event({"type":"weed_detected","source":"simulator_huintec","timestamp":ts,"data":{**motion,"weed_detected_at":ts,"weed_type":"SIMULATED_UNKNOWN","grid_index":grid,"grid_rows":1,"grid_cols":24,"grid_row":1,"grid_col":grid,"simulated":True}})
            self.store.event({"type":"nozzle_fired","source":"simulator_controller","timestamp":ts,"data":{**motion,"nozzle_fired_at":ts,"nozzle_number":grid,"grid_index":grid,"simulated":True}})
            if self.stop_event.wait(interval):break
    # 생성 스레드에 종료를 요청하고 기다립니다.
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=3)
