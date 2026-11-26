# -*- coding: utf-8 -*-
# 실제 카메라 없이 이미지 또는 영상 샘플로 RGB 보정값을 실험하는 Tkinter GUI입니다.

"""Interactive RGB image correction lab. Runs without RealSense hardware.
Usage: python tune_image.py --image path/to/sample.jpg
       python tune_image.py
"""
import argparse, json, pathlib, copy, tkinter as tk
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
        self.initial_cfg=copy.deepcopy(self.cfg)
        self.auto_derived=dict(self.cfg.get('auto_derived_values',{}))
        self.setting_vars=False
        self.samples=[];self.original=None;self.processed=None;self.path=None
        self.auto_controller=AutoBrightness()
        self.last_auto_stats={}
        master.title('Weed Robot - RGB 자동 밝기 균형 v3.4')
        master.geometry('1300x950')
        main=ttk.Frame(master,padding=12);main.pack(fill='both',expand=True)
        top=ttk.Frame(main);top.pack(fill='x')
        ttk.Button(top,text='이미지 열기',command=self.open_image).pack(side='left',padx=3)
        ttk.Button(top,text='영상 열기',command=self.open_video).pack(side='left',padx=3)
        ttk.Button(top,text='보정 이미지 저장',command=self.save_image).pack(side='left',padx=3)
        ttk.Button(top,text='설정값 config.json 저장',command=self.save_config).pack(side='left',padx=3)
        ttk.Label(top,text='원본 이미지 → 보정 이미지 비교 / 수치 변경 시 자동 반영').pack(side='right')
        pane=ttk.Panedwindow(main,orient='horizontal');pane.pack(fill='both',expand=True,pady=12)
        controls_outer=ttk.Frame(pane,padding=4);pane.add(controls_outer,weight=1)
        # 왼쪽 컨트롤에 독립적인 세로 스크롤을 제공하여 창 크기와 무관하게 모든 슬라이더 접근
        canvas=tk.Canvas(controls_outer,highlightthickness=0,width=350)
        scrollbar=ttk.Scrollbar(controls_outer,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        control=ttk.Frame(canvas,padding=8)
        control_window=canvas.create_window((0,0),window=control,anchor='nw')
        control.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(control_window,width=e.width))
        def scroll_left(e):
            if e.delta:canvas.yview_scroll(-int(e.delta/120),'units')
        # 위젯에 커서가 있는 동안만 스크롤 동작: 다른 패널의 스크롤 방해 방지
        def bind_wheel(widget):
            widget.bind('<MouseWheel>',scroll_left,add='+')
            for child in widget.winfo_children():bind_wheel(child)
        self.bind_scroll=bind_wheel
        display=ttk.Frame(pane,padding=8);pane.add(display,weight=3)
        self.variables={};self.labels={};self.entries={}
        # 핵심 명령은 스크롤 컨트롤 상단에 두어 좁은 창에서도 버튼이 잘리지 않게 합니다.
        actions=ttk.Frame(control);actions.pack(fill='x',pady=(0,10))
        ttk.Button(actions,text='자동 수치 계산·적용',command=self.auto).pack(fill='x',pady=2)
        ttk.Button(actions,text='원본 ↔ 보정 비교/변경내역',command=self.show_changes).pack(fill='x',pady=2)
        ttk.Button(actions,text='설정 초기화',command=self.reset).pack(fill='x',pady=2)
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
        self.bind_scroll(control)
        if image_path:self.load(image_path)
    # ON/OFF 보정 옵션 체크박스를 추가합니다.
    def check(self,parent,key,title,default):
        var=tk.BooleanVar(value=bool(self.cfg.get(key,default)))
        self.variables[key]=var
        ttk.Checkbutton(parent,text=title,variable=var,command=(self.toggle_auto if key=='auto_balance_enabled' else self.update)).pack(anchor='w',pady=3)
    # 수치 보정 슬라이더와 현재값 라벨을 추가합니다.
    def scale(self,parent,key,title,lo,hi,step):
        default=DEFAULTS[key]
        var=tk.DoubleVar(value=float(self.cfg.get(key,default)));self.variables[key]=var
        row=ttk.Frame(parent);row.pack(fill='x',pady=(1,0))
        ttk.Label(row,text=title).pack(side='left')
        val=ttk.Label(row,text=f'{var.get():.2f}');val.pack(side='right');self.labels[key]=val
        entry=ttk.Entry(row,width=7);entry.insert(0,str(var.get()));entry.pack(side='right');self.entries[key]=entry
        def apply_value(event):
            try: var.set(max(lo,min(hi,float(entry.get()))));self.changed(key)
            except ValueError: messagebox.showerror('입력 오류','숫자를 입력하세요.')
        entry.bind('<Return>',apply_value)
        tk.Scale(parent,from_=lo,to=hi,resolution=step,orient='horizontal',showvalue=False,variable=var,command=lambda v,k=key:self.changed(k)).pack(fill='x')
    def changed(self,key):
        if not self.setting_vars and key in self.auto_derived:
            # Scale.set()에 의해 늦게 도착한 자동 갱신 콜백은 자동값을 유지합니다.
            if abs(float(self.variables[key].get())-float(self.auto_derived[key]))>0.002:
                self.auto_derived.pop(key,None)  # 사용자가 수정한 항목만 수동 처리
        self.update()

    def toggle_auto(self):
        # ON 시 계산값을 실제 숫자 컨트롤에 적용. OFF 시 기존 숫자는 유지하여 수동 보정이 가능
        if self.variables['auto_balance_enabled'].get() and self.samples:
            self.auto()
        else:
            self.auto_derived.clear()
            self.update()

    # GUI에 표시된 값을 처리 설정 딕셔너리로 변환합니다.
    def params(self):
        data=dict(self.cfg)
        for key,var in self.variables.items():
            v=var.get()
            if key in ('brightness','denoise_strength'):v=int(round(v))
            data[key]=v
        data['auto_derived_values']=dict(self.auto_derived) if data.get('auto_balance_enabled') else {}
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
        if not self.samples:
            messagebox.showinfo('안내','이미지 또는 영상을 먼저 열어주세요.')
            return
        values,stats=recommend(self.samples)
        is_auto=bool(self.variables['auto_balance_enabled'].get())
        # 영상마다 자동 밝기 알고리즘이 계산한 감마 계수를 수치 컨트롤에 실제 반영.
        self.auto_controller.reset()
        self.auto_controller.apply(self.original,{**self.params(),'auto_balance_enabled':True})
        info=dict(self.auto_controller.last_stats)
        self.last_auto_stats=info
        values['gamma']=round(1.0/max(float(info.get('exponent',1.0)),0.01),3)
        keys=('gamma','highlights','shadows','whites','blacks')
        self.setting_vars=True
        try:
            for key in keys:
                if key in self.variables:
                    self.variables[key].set(values[key])
        finally:
            self.setting_vars=False
        # 자동 실행 중에는 위 수치를 참고용/직접 수정 가능한 상태로 유지하지만,
        # 동일 효과를 중복 적용하지 않습니다. 수동 편집한 키는 auto_derived에서 빠집니다.
        self.auto_derived={key:round(float(values[key]),3) for key in keys} if is_auto else {}
        self.update()
        self.status.set(f"수치 입력칸 반영 완료 | 분석 프레임 {stats['samples']}개 | 중앙값 {stats['median']:.1f}")
    # 슬라이더 변경 시 즉시 RGB 전처리를 다시 실행합니다.
    def update(self):
        for key,label in self.labels.items():
            value=f'{self.variables[key].get():.2f}';label.configure(text=value)
            entry=self.entries.get(key)
            if entry is not None and self.master.focus_get()!=entry:entry.delete(0,'end');entry.insert(0,value)
        if self.original is None:return
        try:
            self.auto_controller.reset()  # GUI 정지영상 미리보기는 슬라이더 즉시 반영
            settings=self.params()
            balanced=self.auto_controller.apply(self.original,settings)
            self.processed=rgb_process(balanced,settings)
            self.describe_auto()
            self.render(self.original_label,self.original,'원본')
            self.render(self.processed_label,self.processed,'보정')
            self.status.set(f'{pathlib.Path(self.path).name} | {self.original.shape[1]}x{self.original.shape[0]} | 자동 밝기: {self.auto_controller.last_stats.get("direction", "OFF")} | 설정 저장 시 다음 녹화부터 적용')
        except Exception as e:self.status.set(f'보정 오류: {e}')
    # 현재 자동 밝기 알고리즘의 실제 계산값을 실시간으로 보여줍니다.
    def describe_auto(self):
        stats=self.auto_controller.last_stats
        if stats:self.last_auto_stats=dict(stats)
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

    # 별도 팝업: 원본/보정 이미지, 설정 변경 전후 수치, 실제 자동 밝기 계산 결과
    def show_changes(self):
        if self.original is None:
            messagebox.showinfo('안내','이미지 또는 영상을 먼저 열어주세요.')
            return
        window=tk.Toplevel(self.master)
        window.title('원본 ↔ 보정 비교 및 변경값')
        window.geometry('1080x850')
        window.transient(self.master)
        window.columnconfigure(0,weight=1)
        window.columnconfigure(1,weight=1)
        row=ttk.Frame(window,padding=10);row.pack(fill='x')
        for img,title in ((self.original,'원본'),(self.processed,'현재 보정')):
            from PIL import Image,ImageTk
            rgb=cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
            im=Image.fromarray(rgb);im.thumbnail((510,340))
            photo=ImageTk.PhotoImage(im)
            lbl=ttk.Label(row,text=title,image=photo,compound='top')
            lbl.image=photo
            lbl.pack(side='left',expand=True,padx=8)
        ttk.Label(window,text='설정 초기값 → 현재값 (변경 항목)',font=('Segoe UI',11,'bold')).pack(anchor='w',padx=12)
        table=ttk.Treeview(window,columns=('initial','current','effect'),show='headings',height=13)
        for key,title,width in (('initial','설정 초기값',200),('current','현재값',200),('effect','구분',250)):
            table.heading(key,text=title);table.column(key,width=width,anchor='center')
        # 이름은 tree의 #0 대신 첫 컬럼으로 표시해 변경 항목을 명확히 보여줍니다.
        table.configure(columns=('name','initial','current','effect'))
        table.heading('name',text='항목');table.column('name',width=190,anchor='w')
        current=self.params()
        for key in self.variables:
            a=self.initial_cfg.get(key,DEFAULTS.get(key))
            b=current.get(key)
            if isinstance(a,float) or isinstance(b,float):
                changed=abs(float(a)-float(b))>0.001
            else:changed=a!=b
            if changed:table.insert('', 'end',values=(key,str(a),str(b),'자동 추천' if key in self.auto_derived else '수동/현재값'))
        table.pack(fill='both',expand=True,padx=12,pady=10)
        ttk.Label(window,text='자동 분석값: '+json.dumps(self.last_auto_stats,ensure_ascii=False),wraplength=1000).pack(anchor='w',padx=12,pady=8)
        ttk.Button(window,text='닫기',command=window.destroy).pack(pady=8)

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
        if self.last_auto_stats:
            self.config['processing']['auto_last_analysis']=dict(self.last_auto_stats)
        try:
            self.config_path.write_text(json.dumps(self.config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            self.cfg=self.config['processing'];messagebox.showinfo('저장 완료','config.json에 보정값을 저장했습니다. 다음 녹화 실행부터 적용됩니다.')
        except Exception as e:messagebox.showerror('저장 오류',str(e))
    # 실행 당시 config.json에 있던 초기 설정값으로 복원합니다 (파일 저장은 별도).
    def reset(self):
        self.setting_vars=True
        try:
            for key,var in self.variables.items():
                var.set(self.initial_cfg.get(key,DEFAULTS.get(key)))
            self.auto_derived=dict(self.initial_cfg.get('auto_derived_values',{}))
        finally:self.setting_vars=False
        self.update()
        self.status.set('config.json을 열었을 때의 설정값으로 초기화 완료 — 저장 버튼을 누르면 파일에 반영됩니다.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image');parser.add_argument('--config',default=str(ROOT/'config.json'))
    args=parser.parse_args();window=tk.Tk();Tuner(window,args.config,args.image);window.mainloop()
