# -*- coding: utf-8 -*-
"""영상 샘플의 강건한 휘도 통계로 보수적인 초기값을 산출합니다."""
import cv2
import numpy as np

DEFAULTS=dict(auto_balance_enabled=True,auto_target_luma=128,auto_strength=0.8,auto_smoothing=0.9,enabled=True,white_balance=False,clahe=False,clahe_clip=1.5,brightness=0,contrast=1.,gamma=1.,saturation=1.,denoise=False,denoise_strength=5,sharpen=0.,exposure=0,highlights=0,shadows=0,whites=0,blacks=0)

def analyze(image):
    # LAB L 채널: 색상과 밝기를 분리하여 식생 색상 변형을 줄입니다.
    h,w=image.shape[:2]; scale=min(1,640/max(h,w)); x=cv2.resize(image,(max(1,int(w*scale)),max(1,int(h*scale))),interpolation=cv2.INTER_AREA)
    l=cv2.cvtColor(x,cv2.COLOR_BGR2LAB)[:,:,0]
    p=np.percentile(l,[1,10,50,90,99]); return np.r_[p,np.mean(l>=250),np.mean(l<=5)]

def recommend(images):
    rows=np.array([analyze(x) for x in images]); p1,p10,p50,p90,p99,hi,lo=np.median(rows,axis=0)
    c=DEFAULTS.copy()
    # 수동 보정값 자동 추천은 AutoBrightness의 실시간 분석과 별개 기능입니다.
    # 중앙 밝기 목표 128, 감마 제한으로 과보정 방지.
    c['gamma']=round(float(np.clip(np.log(np.clip(p50/255,.02,.98))/np.log(128/255),.8,1.35)),2)
    c['highlights']=int(np.clip(-(p90-205)*1.2,-35,0))
    c['shadows']=int(np.clip((45-p10)*.8,0,30))
    c['whites']=int(np.clip((235-p99)*.4,-12,12))
    c['blacks']=int(np.clip((12-p1)*.4,-8,8))
    c['clahe']=bool(20<p90-p10<85 and p50>35 and p50<220)
    # 포화 픽셀은 복구 불가. 추가 증폭을 제한합니다.
    if hi>.03: c['gamma']=min(c['gamma'],1.0)
    if lo>.10: c['clahe']=False
    if p90-p10<5:
        c=DEFAULTS.copy()  # 단색/정보 부족 영상은 자동 보정하지 않음
    return c,dict(p10=float(p10),median=float(p50),p90=float(p90),highlight_pct=float(hi*100),shadow_pct=float(lo*100),samples=len(rows))

def video_samples(path,count=16):
    cap=cv2.VideoCapture(str(path)); frames=[]
    try:
        n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if n<=0: raise ValueError('영상 프레임 수를 읽을 수 없습니다.')
        for i in np.linspace(0,n-1,min(count,n),dtype=int):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(i)); ok,x=cap.read()
            if ok: frames.append(x)
    finally: cap.release()
    if not frames: raise ValueError('영상 샘플을 읽을 수 없습니다.')
    return frames
