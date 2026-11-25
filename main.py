# -*- coding: utf-8 -*-
# D455 카메라 수집/녹화 진입점. config.json의 processing 설정을 RGB 영상에 적용합니다.
# 주석 추가 버전: 기존 실행 로직과 설정값은 변경하지 않았습니다.

import argparse,datetime,json,logging,time,pathlib
import cv2,numpy as np
from store import Store,iso_now
from processor import rgb_process,ir_process
from api import Api
from simulator import Simulator

# 설정을 읽고 API·시뮬레이터·카메라를 실행하며 MP4와 이미지/메타데이터를 저장합니다.
def run():
    # 실행 옵션: --config 로 다른 설정 파일을 선택할 수 있습니다.
    ap=argparse.ArgumentParser();ap.add_argument('--config',default='config.json');args=ap.parse_args()
    cfg=json.loads(pathlib.Path(args.config).read_text(encoding='utf8'))
    # 세션 ID는 실행 시작 시각이며 output/<세션 ID> 아래 저장합니다.
    sid=datetime.datetime.now().strftime('%Y%m%d_%H%M%S');store=Store(cfg['recording']['root'],sid)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s');log=logging.getLogger('weed')
    # 외부 이벤트 수신 API와 가상 이벤트 생성기를 카메라와 별도로 시작합니다.
    api=Api(store,**cfg['api']);api.start();sim=Simulator(store,cfg.get('simulation',{}));sim.start();log.info('API http://%s:%s',cfg['api']['host'],cfg['api']['port'])
    import pyrealsense2 as rs
    # D455 RGB(BGR8)·Depth(Z16) 스트림 해상도/FPS를 설정합니다.
    pipe=rs.pipeline();rc=rs.config();cam=cfg['camera'];cw,ch,cf=cam['color'];dw,dh,df=cam['depth']
    rc.enable_stream(rs.stream.color,cw,ch,rs.format.bgr8,cf)
    rc.enable_stream(rs.stream.depth,dw,dh,rs.format.z16,df)
    # IR 스트림은 카메라/설정에서 지원할 때만 추가합니다.
    if cam.get('infrared_enabled'):rc.enable_stream(rs.stream.infrared,int(cam.get('infrared_index',1)),dw,dh,rs.format.y8,df)
    profile=None;writers={};segment_start=None;segment_no=-1;last_image=-1e20
    try:
        # 카메라가 USB 대역폭 문제로 연결되지 않으면 이 지점에서 예외가 날 수 있습니다.
        profile=pipe.start(rc);scale=profile.get_device().first_depth_sensor().get_depth_scale()
        align=rs.align(rs.stream.color) if cam.get('align_depth_to_color',True) else None
        log.info('카메라 시작: depth scale %s',scale)
        while True:
            try: frames=pipe.wait_for_frames(int(cam.get('timeout_ms',5000)))
            except RuntimeError as e:
                log.error('카메라 프레임 수신 실패: %s',e);break
            if align: frames=align.process(frames)
            color=frames.get_color_frame();depth=frames.get_depth_frame()
            if not color or not depth:continue
            # RGB에는 보정을 적용하지만 raw Depth는 16비트 원본으로 유지합니다.
            rgb=np.asanyarray(color.get_data());raw=np.asanyarray(depth.get_data());processed=rgb_process(rgb,cfg['processing'])
            # Depth MP4용 컬러 영상은 시각화 이미지이며 실제 거리값이 아닙니다.
            vis=cv2.applyColorMap(cv2.convertScaleAbs(raw,alpha=0.03),cv2.COLORMAP_JET)
            # Align can change depth resolution to RGB resolution.
            if vis.shape[:2]!=processed.shape[:2]:vis=cv2.resize(vis,(processed.shape[1],processed.shape[0]),interpolation=cv2.INTER_NEAREST)
            now=time.monotonic();timestamp=iso_now();duration=float(cfg['recording']['segment_seconds'])
            # 설정한 초 단위로 MP4를 분할하며 각 구간을 session.json에 기록합니다.
            if segment_start is None or now-segment_start>=duration:
                for w in writers.values():w.release()
                writers={};segment_start=now;segment_no+=1
                suffix='' if segment_no==0 else f'_{segment_no:03d}'
                for kind,img in [('rgb',processed),('depth',vis)]:
                    name=f'rec/{kind}_{sid}{suffix}.mp4';path=store.base/name
                    h,w=img.shape[:2];writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),float(cf if kind=='rgb' else min(cf,df)),(w,h))
                    if not writer.isOpened():raise RuntimeError(f'MP4 writer error: {path}')
                    writers[kind]=writer
                store.segments.append({'index':segment_no,'started_at':timestamp,'rgb':f'rec/rgb_{sid}{suffix}.mp4','depth':f'rec/depth_{sid}{suffix}.mp4'})
                store.write_manifest()
            writers['rgb'].write(processed);writers['depth'].write(vis)
            # 일정 간격마다 학습용 RGB/Depth 정지 이미지와 frames.jsonl을 저장합니다.
            interval=float(cfg['recording']['image_interval_seconds'])
            if now-last_image>=interval:
                last_image=now;store.frame_index+=1;fid=f'{sid}_{store.frame_index:08d}'
                rel_rgb=f'images/rgb/{fid}.jpg';rel_depth=f'images/depth/{fid}.png';rel_vis=f'images/depth_color/{fid}.jpg'
                ok1=cv2.imwrite(str(store.base/rel_rgb),processed,[cv2.IMWRITE_JPEG_QUALITY,int(cfg['recording']['jpeg_quality'])])
                ok2=cv2.imwrite(str(store.base/rel_depth),raw);ok3=cv2.imwrite(str(store.base/rel_vis),vis)
                if not all((ok1,ok2,ok3)):log.warning('이미지 저장 실패 %s',fid)
                item={'frame_id':fid,'session_id':sid,'timestamp':timestamp,'camera_timestamp_ms':float(color.get_timestamp()),'camera_timestamp_domain':str(color.get_frame_timestamp_domain()),'depth_timestamp_ms':float(depth.get_timestamp()),'depth_scale_m_per_unit':scale,'rgb':rel_rgb,'depth_raw':rel_depth,'depth_preview':rel_vis,'rgb_depth_aligned':bool(align),'segment_index':segment_no}
                if cam.get('infrared_enabled'):
                    ir=frames.get_infrared_frame(int(cam.get('infrared_index',1)))
                    if ir:
                        ir_img=ir_process(np.asanyarray(ir.get_data()),cfg['processing']);rel_ir=f'images/ir/{fid}.png'
                        cv2.imwrite(str(store.base/rel_ir),ir_img);item['ir']=rel_ir
                store.frame(item)
            # 미리보기가 켜져 있으면 Q 키로 녹화를 종료할 수 있습니다.
            if cfg['recording'].get('preview',False):
                cv2.imshow('RGB - press Q to quit',processed);cv2.imshow('Depth - press Q to quit',vis)
                if cv2.waitKey(1)&0xff==ord('q'):break
    # 정상 종료/예외 상황 모두에서 MP4·카메라·API를 정리합니다.
    finally:
        for w in writers.values():w.release()
        if profile is not None:pipe.stop()
        cv2.destroyAllWindows();sim.stop();api.stop();log.info('종료: %s',store.base)
if __name__=='__main__':run()
