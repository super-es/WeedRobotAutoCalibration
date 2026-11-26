# -*- coding: utf-8 -*-
# 실제 카메라 없이 이미지 또는 영상 샘플로 RGB 보정값을 실험하는 Tkinter GUI입니다.

"""Interactive RGB image correction lab. Runs without RealSense hardware.
Usage: python tune_image.py --image path/to/sample.jpg
       python tune_image.py
"""
import argparse, json, pathlib, tkinter as tk
from tkinter import ttk, filedialog, messagebox
import cv2
import numpy as np
from processor import rgb_process
from auto_calibration import DEFAULTS, recommend, video_samples
from auto_balance import AutoBrightness

ROOT=pathlib.Path(__file__).resolve().parent

# 한글 경로를 포함한 이미지 파일을 OpenCV로 읽습니다.
def read_image(path):
    raw=np.fromfile(str(path),dtype=np.uint8)
    img=cv2.imdecode(raw,cv2.IMREAD_COLOR)
    if img is None: raise ValueError('이미지를 열 수 없습니다: '+str(path))
    return img

# 한글 경로에도 저장되도록 인코딩한 바이트를 기록합니다.
def write_image(path,img):
    ext=pathlib.Path(path).suffix.lower() or '.png'
    ok,data=cv2.imencode(ext,img)
    if not ok: raise ValueError('이미지 인코딩 실패')
    data.tofile(str(path))

# 영상 보정 GUI
class Tuner:
    # 보정 설정을 읽고 원본/결과 비교 UI와 슬라이더를 만듭니다.
    def __init__(self,master,config_path,image_path=None):
        self.master=master; self.config_path=pathlib.Path(config_path)
        self.config=json.loads(self.config_path.read_text(encoding='utf-8'))
        # processing 섹션만 편집하므로 녹화/API 설정은 유지됩니다.
        self.cfg=self.config.setdefault('processing',{})
        self.samples=[];self.original=None;self.processed=None;self.path=None
        self.auto_controller=AutoBrightness()
        master.title('Weed Robot - RGB 자동 밝기 균형 v3.4')
        master.geometry('1300x950')
        main=ttk.Frame(master,padding=12);main.pack(fill='both',expand=True)
        top=ttk.Frame(main);top.pack(fill='x')
        ttk.Button(top,text='이미지 열기',command=self.open_image).pack(side='left',padx=3)
        ttk.Button(top,text='영상 열기',command=self.open_video).pack(side='left',padx=3)
        ttk.Button(top,text='자동 초기값 산출',command=self.auto).pack(side='left',padx=3)
        ttk.Button(top,text='계산값 → 수동 감마 적용',command=self.apply_snapshot).pack(side='left',padx=3)
        ttk.Button(top,text='보정 이미지 저장',command=self.save_image).pack(side='left',padx=3)
        ttk.Button(top,text='설정값 config.json 저장',command=self.save_config).pack(side='left',padx=3)
        ttk.Button(top,text='설정 초기화',command=self.reset).pack(side='left',padx=3)
        ttk.Label(top,text='원본 이미지 → 보정 이미지 비교 / 수치 변경 시 자동 반영').pack(side='right')
        pane=ttk.Panedwindow(main,orient='horizontal');pane.pack(fill='both',expand=True,pady=12)
        control=ttk.Frame(pane,padding=8);pane.add(control,weight=1)
        display=ttk.Frame(pane,padding=8);pane.add(display,weight=3)
        self.variables={};self.labels={};self.entries={}
        self.check(control,'enabled','수동 전처리 적용',True)
        # 자동 밝기 균형: 기본 ON / OFF 버튼. 수동 전처리와 독립적으로 동작합니다.
        self.check(control,'auto_balance_enabled','자동 밝기 균형 ON/OFF',True)
        self.scale(control,'auto_target_luma','목표 밝기(L)',80,175,1)
        self.scale(control,'auto_strength','자동 보정 강도',0.0,1.0,0.05)
        self.scale(control,'auto_smoothing','영상 변화 완충',0.0,0.995,0.005)
        ttk.Label(control,text='[현재 영상의 자동 계산값]').pack(anchor='w',pady=(8,2))
        self.auto_result=tk.StringVar(value='영상 입력 전 / 자동 분석 대기')
        ttk.Label(control,textvariable=self.auto_result,justify='left',wraplength=330).pack(anchor='w',pady=(0,8))
        self.check(control,'white_balance','자동 화이트밸런스',False)
        self.check(control,'clahe','CLAHE 대비 보정',False)
        self.scale(control,'clahe_clip','CLAHE 강도',0.1,6.0,0.1)
        # 수치를 바꿔가며 비교할 수 있는 RGB 보정 파라미터들입니다.
        for key,title,lo,hi,step in [('exposure','노출 EV',-1,1,.05),('highlights','하이라이트',-60,60,1),('shadows','그림자',-60,60,1),('whites','화이트',-40,40,1),('blacks','블랙',-40,40,1)]:
            self.scale(control,key,title,lo,hi,step)
        self.scale(control,'brightness','밝기',-100,100,1)
        self.scale(control,'contrast','대비',0.2,3.0,0.05)
        self.scale(control,'gamma','감마',0.2,3.0,0.05)
        self.scale(control,'saturation','채도',0.0,3.0,0.05)
        self.check(control,'denoise','노이즈 제거',False)
        self.scale(control,'denoise_strength','노이즈 제거 강도',1,20,1)
        self.scale(control,'sharpen','선명도',0,2.0,0.05)
        self.images=ttk.Frame(display);self.images.pack(fill='both',expand=True)
        self.original_label=ttk.Label(self.images,text='원본: 이미지를 선택하세요',anchor='center');self.original_label.pack(side='left',fill='both',expand=True)
        self.processed_label=ttk.Label(self.images,text='보정 결과',anchor='center');self.processed_label.pack(side='left',fill='both',expand=True)
        self.status=tk.StringVar(value='이미지를 열면 슬라이더로 보정값을 조절할 수 있습니다.')
        ttk.Label(main,textvariable=self.status).pack(anchor='w')
        if image_path:self.load(image_path)
    # ON/OFF 보정 옵션 체크박스를 추가합니다.
    def check(self,parent,key,title,default):
        var=tk.BooleanVar(value=bool(self.cfg.get(key,default)))
        self.variables[key]=var
        ttk.Checkbutton(parent,text=title,variable=var,command=self.update).pack(anchor='w',pady=3)
    # 수치 보정 슬라이더와 현재값 라벨을 추가합니다.
    def scale(self,parent,key,title,lo,hi,step):
        default=DEFAULTS[key]
        var=tk.DoubleVar(value=float(self.cfg.get(key,default)));self.variables[key]=var
        row=ttk.Frame(parent);row.pack(fill='x',pady=(1,0))
        ttk.Label(row,text=title).pack(side='left')
        val=ttk.Label(row,text=f'{var.get():.2f}');val.pack(side='right');self.labels[key]=val
        entry=ttk.Entry(row,width=7);entry.insert(0,str(var.get()));entry.pack(side='right');self.entries[key]=entry
        def apply_value(event):
            try: var.set(max(lo,min(hi,float(entry.get()))));self.update()
            except ValueError: messagebox.showerror('입력 오류','숫자를 입력하세요.')
        entry.bind('<Return>',apply_value)
        tk.Scale(parent,from_=lo,to=hi,resolution=step,orient='horizontal',showvalue=False,variable=var,command=lambda v,k=key:self.update()).pack(fill='x')
    # GUI에 표시된 값을 처리 설정 딕셔너리로 변환합니다.
    def params(self):
        data=dict(self.cfg)
        for key,var in self.variables.items():
            v=var.get()
            if key in ('brightness','denoise_strength'):v=int(round(v))
            data[key]=v
        return data
    # 이미지 선택 대화상자를 엽니다.
    def open_image(self):
        path=filedialog.askopenfilename(filetypes=[('Images','*.jpg *.jpeg *.png *.bmp *.tif *.tiff'),('All files','*.*')])
        if path:self.load(path)
    # 선택한 이미지를 읽어 보정 결과를 갱신합니다.
    def load(self,path):
        try:
            self.original=read_image(path);self.samples=[self.original];self.path=path;self.auto_controller.reset();self.auto()
        except Exception as e:messagebox.showerror('파일 오류',str(e))
    def open_video(self):
        path=filedialog.askopenfilename(filetypes=[('Video','*.mp4 *.avi *.mov *.mkv')])
        if not path:return
        try:
            self.samples=video_samples(path);self.original=self.samples[len(self.samples)//2];self.path=path;self.auto_controller.reset();self.auto()
        except Exception as e:messagebox.showerror('영상 오류',str(e))
    def auto(self):
        if not self.samples:return
        values,stats=recommend(self.samples)
        automatic = bool(self.variables['auto_balance_enabled'].get())
        for key,var in self.variables.items():
            # 영상 자동 밝기 ON이면 기존 수동 감마/하이라이트 추천을 중복 적용하지 않습니다.
            # 사용자가 목표 밝기를 바꾸면 자동 보정 강도만 변경됩니다.
            if key in ('auto_balance_enabled','auto_target_luma','auto_strength','auto_smoothing'):
                continue
            if automatic:
                if key in ('enabled','nir_median','nir_normalize'):
                    continue
                var.set(DEFAULTS.get(key,values.get(key,var.get())))
            else:
                var.set(values.get(key,var.get()))
        self.update()
        self.status.set(f"자동 분석 | 샘플 {stats['samples']}개 | L 중앙값 {stats['median']:.1f} | 밝은 포화 {stats['highlight_pct']:.1f}% | 어두운 포화 {stats['shadow_pct']:.1f}%")
    # 슬라이더 변경 시 즉시 RGB 전처리를 다시 실행합니다.
    def update(self):
        for key,label in self.labels.items():
            value=f'{self.variables[key].get():.2f}';label.configure(text=value)
            entry=self.entries.get(key)
            if entry is not None and self.master.focus_get()!=entry:entry.delete(0,'end');entry.insert(0,value)
        if self.original is None:return
        try:
            self.auto_controller.reset()  # GUI 정지영상 미리보기는 슬라이더 즉시 반영
            balanced=self.auto_controller.apply(self.original,self.params())
            self.processed=rgb_process(balanced,self.params())
            self.describe_auto()
            self.render(self.original_label,self.original,'원본')
            self.render(self.processed_label,self.processed,'보정')
            self.status.set(f'{pathlib.Path(self.path).name} | {self.original.shape[1]}x{self.original.shape[0]} | 자동 밝기: {self.auto_controller.last_stats.get("direction", "OFF")} | 설정 저장 시 다음 녹화부터 적용')
        except Exception as e:self.status.set(f'보정 오류: {e}')
    # 현재 자동 밝기 알고리즘의 실제 계산값을 실시간으로 보여줍니다.
    def describe_auto(self):
        stats=self.auto_controller.last_stats
        if not stats:
            self.auto_result.set('자동 밝기 OFF — 적용 계수 없음')
            return
        exponent=float(stats['exponent'])
        equivalent_gamma=1.0/max(exponent,0.01)
        original=float(stats['p50'])
        corrected=255*(original/255)**exponent
        self.auto_result.set(
            f"중앙 밝기: {original:.1f} → {corrected:.1f} (목표 {stats['target_luma']:.0f})\\n"
            f"보정 방향: {stats['direction']} | 환산 감마: {equivalent_gamma:.3f}\\n"
            f"실제 LUT 지수: {exponent:.3f} | 하이라이트 포화: {stats['highlight_clip_pct']:.2f}%\\n"
            f"그림자 포화: {stats['shadow_clip_pct']:.2f}% | P10: {stats['p10']:.1f} / P90: {stats['p90']:.1f}\\n"
            "※ 수동 노출/하이라이트 설정과 구분되는 자동 계수입니다."
        )

    # 자동 밝기 보정 결과를 한 장면의 고정 수동 감마 값으로 전환합니다.
    # 이 작업은 자동 ON/OFF와 달리 영상 전체에 고정된 수치를 적용할 때 사용합니다.
    def apply_snapshot(self):
        if self.original is None:
            messagebox.showinfo('안내','이미지 또는 영상을 먼저 열어주세요.')
            return
        if not self.variables['auto_balance_enabled'].get():
            messagebox.showinfo('안내','자동 밝기 균형을 ON으로 설정하세요.')
            return
        self.auto_controller.reset()
        self.auto_controller.apply(self.original,self.params())
        stats=self.auto_controller.last_stats
        if not stats:return
        # processor.gamma는 밝기 LUT 지수의 역수입니다.
        self.variables['gamma'].set(round(1.0/max(float(stats['exponent']),0.01),3))
        # 자동 보정과 수동 감마를 중복 적용하지 않도록 자동 모드를 끕니다.
        self.variables['auto_balance_enabled'].set(False)
        self.update()
        self.status.set('수동 감마 값에 자동 계산값을 적용했습니다. 중복 방지를 위해 자동 밝기를 OFF로 변경했습니다. 설정 저장을 눌러 확정하세요.')

    # OpenCV BGR 이미지를 Tkinter 화면에 맞춰 표시합니다.
    def render(self,label,image,title):
        from PIL import Image,ImageTk
        rgb=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        im=Image.fromarray(rgb);im.thumbnail((425,620))
        photo=ImageTk.PhotoImage(im)
        label.configure(image=photo,text=title,compound='top');label.image=photo
    # 현재 보정 결과를 이미지 파일로 저장합니다.
    def save_image(self):
        if self.processed is None:messagebox.showinfo('안내','이미지를 먼저 열어주세요.');return
        path=filedialog.asksaveasfilename(defaultextension='.png',filetypes=[('PNG','*.png'),('JPEG','*.jpg')])
        if path:
            try:write_image(path,self.processed);self.status.set('이미지 저장: '+path)
            except Exception as e:messagebox.showerror('저장 오류',str(e))
    # GUI 보정값을 config.json에 기록합니다. 다음 녹화 실행부터 반영됩니다.
    def save_config(self):
        # 설정 파일을 저장해도 실행 중인 main.py에는 자동 반영되지 않습니다.
        self.config['processing']=self.params()
        # 참고용 분석 결과: 고정 파라미터로 재적용하지 않습니다.
        if self.auto_controller.last_stats:
            self.config['processing']['auto_last_analysis']=dict(self.auto_controller.last_stats)
        try:
            self.config_path.write_text(json.dumps(self.config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            self.cfg=self.config['processing'];messagebox.showinfo('저장 완료','config.json에 보정값을 저장했습니다. 다음 녹화 실행부터 적용됩니다.')
        except Exception as e:messagebox.showerror('저장 오류',str(e))
    # 보정 슬라이더를 기본값으로 되돌립니다.
    def reset(self):
        defaults=DEFAULTS
        for key,var in self.variables.items():var.set(defaults[key])
        self.update()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image');parser.add_argument('--config',default=str(ROOT/'config.json'))
    args=parser.parse_args();window=tk.Tk();Tuner(window,args.config,args.image);window.mainloop()
