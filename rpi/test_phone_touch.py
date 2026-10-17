#!/usr/bin/env python3
import unittest

import phone_touch as PT


class NormalizeTests(unittest.TestCase):
    def test_normalizes_visible_image(self):
        self.assertEqual(PT.normalized(60, 120, 10, 20, 100, 200), (0.5, 0.5))

    def test_clamps_outside_image(self):
        self.assertEqual(PT.normalized(-20, 999, 10, 20, 100, 200), (0.0, 1.0))

    def test_rejects_empty_image(self):
        with self.assertRaises(ValueError):
            PT.normalized(1, 1, 0, 0, 0, 10)


class GestureTests(unittest.TestCase):
    def test_short_stationary_press_is_tap(self):
        g = PT.GestureTracker()
        g.down(.5, .5, 1.0)
        result = g.up(.505, .503, 1.2)
        self.assertEqual(result.kind, 'tap')
        self.assertFalse(g.active)

    def test_drag_never_becomes_tap(self):
        g = PT.GestureTracker()
        g.down(.2, .2, 1.0)
        move = g.move(.4, .3, 1.1)
        self.assertEqual(move.kind, 'move')
        result = g.up(.4, .3, 1.2)
        self.assertEqual(result.kind, 'release')

    def test_long_press_does_not_click(self):
        g = PT.GestureTracker()
        g.down(.5, .5, 1.0)
        result = g.up(.5, .5, 2.0)
        self.assertEqual(result.kind, 'release')

    def test_cancel_does_not_emit_action(self):
        g = PT.GestureTracker()
        g.down(.5, .5, 1.0)
        self.assertTrue(g.active)
        self.assertIsNone(g.cancel())
        self.assertFalse(g.active)
        self.assertIsNone(g.up(.5, .5, 1.1))

    def test_move_without_down_is_ignored(self):
        g = PT.GestureTracker()
        self.assertIsNone(g.move(.5, .5, 1.0))


if __name__ == '__main__':
    unittest.main()
