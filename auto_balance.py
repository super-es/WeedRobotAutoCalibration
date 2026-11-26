# -*- coding: utf-8 -*-
"""RGB 영상의 자동 밝기 균형. 원본 Depth는 처리하지 않습니다.

중앙 휘도 목표를 이용해 어두운 프레임을 밝게, 밝은 프레임을 어둡게 합니다.
프레임 간 보정계수는 EMA로 완만하게 변경해 플리커(flicker)를 줄입니다.
"""
import cv2
import numpy as np


class AutoBrightness:
    """영상 스트림별로 한 개 생성하는 상태 유지형 자동 밝기 보정기."""

    def __init__(self):
        self._exponent = None
        self.last_stats = {}

    def reset(self):
        self._exponent = None
        self.last_stats = {}

    def apply(self, image, cfg):
        if not cfg.get('auto_balance_enabled', True):
            self.reset()
            return image.copy()
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError('AutoBrightness에는 BGR 8-bit 컬러 영상이 필요합니다.')
        target = float(np.clip(cfg.get('auto_target_luma', 128), 80, 175))
        strength = float(np.clip(cfg.get('auto_strength', 0.8), 0, 1))
        smoothing = float(np.clip(cfg.get('auto_smoothing', 0.90), 0, 0.995))
        h, w = image.shape[:2]
        scale = min(1.0, 320.0 / max(h, w))
        sample = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        luma = cv2.cvtColor(sample, cv2.COLOR_BGR2LAB)[:, :, 0]
        p10, p50, p90, p99 = np.percentile(luma, [10, 50, 90, 99])
        high_clip = float(np.mean(luma >= 250))
        low_clip = float(np.mean(luma <= 5))

        # 거의 단색이면 자동 조정을 생략합니다.
        if p90 - p10 < 8 or strength <= 0:
            desired = 1.0
        else:
            # exponent < 1: 밝게 / exponent > 1: 어둡게.
            base = np.clip(p50 / 255.0, 0.04, 0.98)
            desired = np.log(target / 255.0) / np.log(base)
            desired = float(np.clip(desired, 0.65, 1.55))
            desired = 1.0 + (desired - 1.0) * strength
            if high_clip >= 0.04 and desired < 1.0:
                desired = max(desired, 0.93)
            if low_clip >= 0.12 and desired > 1.0:
                desired = min(desired, 1.06)

        if self._exponent is None:
            self._exponent = desired
        else:
            self._exponent = smoothing * self._exponent + (1.0 - smoothing) * desired
        exponent = float(self._exponent)
        # LAB 휘도만 변환해 식생 색상 변형을 줄입니다.
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        lut = np.clip(255.0 * (np.arange(256, dtype=np.float32) / 255.0) ** exponent, 0, 255).astype(np.uint8)
        lab[:, :, 0] = cv2.LUT(lab[:, :, 0], lut)
        result = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        self.last_stats = {
            'p10': round(float(p10), 1), 'p50': round(float(p50), 1),
            'p90': round(float(p90), 1), 'p99': round(float(p99), 1),
            'highlight_clip_pct': round(high_clip * 100, 2),
            'shadow_clip_pct': round(low_clip * 100, 2),
            'target_luma': round(target, 1), 'exponent': round(exponent, 3),
            'direction': '밝게' if exponent < 0.985 else ('어둡게' if exponent > 1.015 else '유지')
        }
        return result
