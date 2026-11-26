# -*- coding: utf-8 -*-
"""외부 카메라 없이 자동 밝기 보정을 확인합니다.
실행: python -m unittest discover -s tests -v
"""
import pathlib
import sys
import unittest
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from auto_balance import AutoBrightness


def gradient(low, high):
    x = np.tile(np.linspace(low, high, 256, dtype=np.uint8), (128, 1))
    return np.repeat(x[:, :, None], 3, axis=2)


class AutoBalanceTests(unittest.TestCase):
    def test_dark_image_gets_brighter(self):
        image = gradient(25, 85)
        result = AutoBrightness().apply(image, {'auto_balance_enabled': True})
        self.assertGreater(float(np.median(result)), float(np.median(image)) + 10)

    def test_bright_image_gets_darker(self):
        image = gradient(160, 235)
        result = AutoBrightness().apply(image, {'auto_balance_enabled': True})
        self.assertLess(float(np.median(result)), float(np.median(image)) - 10)

    def test_off_returns_exact_original(self):
        image = gradient(10, 220)
        result = AutoBrightness().apply(image, {'auto_balance_enabled': False})
        np.testing.assert_array_equal(result, image)

    def test_default_enabled(self):
        image = gradient(25, 85)
        result = AutoBrightness().apply(image, {})
        self.assertGreater(float(np.median(result)), float(np.median(image)))

    def test_smoothing_limits_abrupt_exponent_change(self):
        controller = AutoBrightness()
        controller.apply(gradient(25, 85), {})
        first = controller.last_stats['exponent']
        controller.apply(gradient(160, 235), {})
        second = controller.last_stats['exponent']
        self.assertLess(abs(second - first), 0.15)


if __name__ == '__main__':
    unittest.main()
