# -*- coding: utf-8 -*-
# RGB 및 IR 영상 전처리 함수 모음. 원본 16비트 Depth 값은 여기서 변경하지 않습니다.
# 주석 추가 버전: 기존 실행 로직과 설정값은 변경하지 않았습니다.

import cv2
import numpy as np

# BGR 입력 영상을 복사한 뒤 config의 순서대로 보정합니다.
def rgb_process(image, cfg):
    x=image.copy()
    if not cfg.get('enabled', True): return x
    # 노출 및 영역별 밝기 보정: LAB 휘도에 부드러운 가중치 적용.
    keys=('exposure','highlights','shadows','whites','blacks')
    if any(float(cfg.get(k,0)) for k in keys):
        lab=cv2.cvtColor(x,cv2.COLOR_BGR2LAB)
        t=np.arange(256,dtype=np.float32)/255
        y=t*2**float(cfg.get('exposure',0))
        for k,weight in [('highlights',np.clip((t-.5)*2,0,1)**2),('shadows',np.clip(1-t*2,0,1)**2),('whites',t**6),('blacks',(1-t)**6)]:
            y+=float(cfg.get(k,0))/255*weight
        lut=np.maximum.accumulate(np.clip(y*255,0,255)).astype(np.uint8)
        lab[:,:,0]=cv2.LUT(lab[:,:,0],lut)
        x=cv2.cvtColor(lab,cv2.COLOR_LAB2BGR)
    # RGB 채널 평균을 기준으로 색 편차를 줄입니다.
    if cfg.get('white_balance',False):
        f=x.astype(np.float32); means=np.mean(f,axis=(0,1)); target=float(np.mean(means))
        gains=np.clip(target/np.maximum(means,1),0.5,2.0)
        x=np.clip(f*gains,0,255).astype(np.uint8)
    # 밝기(더하기)와 대비(곱하기)를 적용합니다.
    contrast=float(cfg.get('contrast',1.0)); brightness=float(cfg.get('brightness',0))
    if contrast!=1 or brightness!=0:
        x=np.clip(x.astype(np.float32)*contrast+brightness,0,255).astype(np.uint8)
    # LAB 밝기 채널에 국부 대비 보정(CLAHE)을 적용합니다.
    if cfg.get('clahe',False):
        lab=cv2.cvtColor(x,cv2.COLOR_BGR2LAB);l,a,b=cv2.split(lab)
        clip=max(0.1,float(cfg.get('clahe_clip',1.8)))
        l=cv2.createCLAHE(clipLimit=clip,tileGridSize=(8,8)).apply(l)
        x=cv2.cvtColor(cv2.merge((l,a,b)),cv2.COLOR_LAB2BGR)
    # 감마 LUT로 중간 밝기 분포를 조절합니다.
    gamma=float(cfg.get('gamma',1.0))
    if gamma>0 and abs(gamma-1)>1e-6:
        lut=np.array([min(255,round(255*(i/255)**(1/gamma))) for i in range(256)],dtype=np.uint8)
        x=cv2.LUT(x,lut)
    # HSV 채도 채널의 강도를 조절합니다.
    sat=float(cfg.get('saturation',1.0))
    if sat!=1:
        hsv=cv2.cvtColor(x,cv2.COLOR_BGR2HSV);hsv[:,:,1]=np.clip(hsv[:,:,1].astype(np.float32)*sat,0,255).astype(np.uint8)
        x=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
    # 컬러 영상 잡음 제거는 처리 시간이 늘어날 수 있습니다.
    if cfg.get('denoise',False):
        strength=max(1,int(cfg.get('denoise_strength',5)))
        x=cv2.fastNlMeansDenoisingColored(x,None,strength,strength,7,21)
    # 가우시안 블러 영상과 차이를 이용해 선명도를 높입니다.
    sharp=float(cfg.get('sharpen',0))
    if sharp>0:
        blurred=cv2.GaussianBlur(x,(0,0),1.0)
        x=cv2.addWeighted(x,1+sharp,blurred,-sharp,0)
    return x

# 선택적 IR 영상에 중간값 필터 및 정규화를 적용합니다.
def ir_process(image,cfg):
    x=image.copy(); k=int(cfg.get('nir_median',3))
    if k>=3 and k%2: x=cv2.medianBlur(x,k)
    if cfg.get('nir_normalize'):
        lo,hi=np.percentile(x,(2,98))
        if hi>lo: x=np.clip((x.astype(np.float32)-lo)*255/(hi-lo),0,255).astype(np.uint8)
    return x
