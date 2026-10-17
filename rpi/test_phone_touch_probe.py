#!/usr/bin/env python3
import unittest
from unittest import mock
import subprocess

import phone_touch_probe as P


class CommandTests(unittest.TestCase):
    @mock.patch('phone_touch_probe.subprocess.run')
    def test_command_combines_output(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, 'out', 'err')
        self.assertEqual(P.command('x'), 'outerr')

    @mock.patch('phone_touch_probe.subprocess.run')
    def test_command_reports_timeout(self, run):
        run.side_effect = subprocess.TimeoutExpired('x', 5)
        self.assertIn('ERROR:', P.command('x'))


if __name__ == '__main__':
    unittest.main()
