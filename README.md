# WeedRobotAutoCalibration

제초로봇 RGB·Depth 데이터 수집 및 RGB 영상 자동 보정 실험 프로그램 (WeedRobotCollector v3.3).

## 구성

- `main.py` — RealSense D455 영상 수집 및 녹화
- `processor.py` — RGB 영상 보정 처리
- `auto_calibration.py` — 영상 샘플 분석을 통한 보수적인 보정 초기값 추천
- `tune_image.py` — 보정값 GUI 조정 및 설정 저장
- `api.py`, `store.py`, `simulator.py` — 외부 이벤트 수신 및 JSONL 기록, 가상 이벤트 생성
- `config.json` — 설정값 (`recording.segment_seconds=300`, GRID 1×24)

## 시작하기

Windows, Python 3.11 권장.

```powershell
python -m pip install -r requirements.txt
python tune_image.py
```

영상/이미지를 열고 자동 초기값을 추천받아 조정한 뒤 `config.json`에 저장합니다.

D455 카메라가 연결된 환경에서 녹화를 실행하려면:

```powershell
python main.py
```

## 주의

- 현장 RGB 영상에서 품질 개선을 정량 검증하기 전인 **실험용 기본 알고리즘**입니다.
- RGB 색상의 식생 정보 보존을 위해 강한 자동 보정은 제한합니다.
- 클리핑으로 소실된 하이라이트 픽셀은 복원되지 않습니다.
- Depth 원시 거리값은 RGB 전처리 대상이 아닙니다.
- D455는 정상적인 USB 3.x 연결을 확인해야 하며, 장비 통합 시험은 별도로 필요합니다.
- `output/`, 실제 영상, 센서 로그, API 인증 키 등은 저장소에 커밋하지 마세요.
- 둑방 번호는 Python 수집 데이터에 직접 저장하지 않고 추후 HTML 후처리로 분석합니다.

## 데이터

수집 데이터는 `output/<session_id>/rec`, `images`, `metadata`로 분리됩니다. 영상은 기본 5분 단위 MP4로 분할하며 이벤트는 `events.jsonl`에 누적됩니다.

이 저장소는 실험/개발용으로, 장비 현장 검증 결과를 보증하지 않습니다.


## v3.4: 자동 밝기 균형 (기본 ON)

`python tune_image.py` 실행 후 이미지 또는 MP4 영상을 선택하세요.

- **자동 밝기 균형 ON/OFF**: 자동 휘도 정규화를 즉시 활성화하거나 우회합니다 (기본 ON).
- **목표 밝기(L)**: 기본 128 / 범위 80~175 (8비트 LAB L 채널).
- **자동 보정 강도**: 기본 0.8 / 범위 0~1.
- **영상 변화 완충**: 기본 0.90 / 범위 0~0.995. 녹화 중 프레임별 보정 값의 급격한 변화 완화.
- **설정값 config.json 저장** 후 `python main.py` 재실행 시 녹화 RGB에 적용됩니다.
- `auto_balance_enabled=false`이면 자동 밝기 알고리즘을 완전히 통과하고, 기존 수동 처리 설정은 독립적으로 적용됩니다.
- GUI에서 JPG/PNG는 단일 프레임, MP4는 최대 16프레임의 통계와 대표 프레임으로 확인합니다. MP4 전체를 재인코딩하는 기능은 아닙니다.
- 카메라 녹화 경로는 매 프레임 값을 분석하되 계수를 평활화하여 화면 깜박임을 완화합니다.
- LAB L 영역 기반 변환은 색상 편차를 줄이지만 과다노출로 이미 소실된 부분은 복구할 수 없습니다.
- 원본 RGB 영상 보존 기능은 별도 구현이 필요합니다. 현재 녹화 RGB는 보정본입니다.
- **검증**: 가상 어두운/밝은 그라데이션에 대한 단위 테스트를 추가했습니다. 실제 현장 장면, D455 연동, 품질 기준 확립은 아직 별도 검증이 필요합니다.

```powershell
python -m unittest discover -s tests -v
```
