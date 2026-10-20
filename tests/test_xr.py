# SPDX-License-Identifier: GPL-2.0-or-later
import unittest
from unittest.mock import patch
from cmuxr_gui import xr

class Routing(unittest.TestCase):
    def test_active_domed_is_reused(self):
        with patch.object(xr,'get_json',return_value={'compositor_pid':123,'xr_socket':'dome-xr','xr_active':True}):
            self.assertEqual(xr.route()[0],'domed-existing')

    def test_domed_without_xr_uses_its_desktop_server(self):
        with patch.object(xr,'get_json',return_value={'compositor_pid':123,'xr_socket':'dome-xr','xr_active':False}):
            mode,server=xr.route('http://127.0.0.1:49641')
            self.assertEqual((mode,server),('domed','http://127.0.0.1:49641'))

    def test_standalone_is_only_a_fallback_when_domed_absent(self):
        with patch.object(xr,'get_json',side_effect=ConnectionRefusedError()),patch.object(xr,'dome_in_use',return_value=False):
            self.assertEqual(xr.route()[0],'fallback')
        with patch.object(xr,'get_json',side_effect=ConnectionRefusedError()),patch.object(xr,'dome_in_use',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'DomeD is in use'):
                xr.route()

    def test_explicit_domed_server_never_falls_back(self):
        with patch.object(xr,'get_json',side_effect=ConnectionRefusedError()),patch.object(xr,'dome_in_use',return_value=False):
            with self.assertRaises(RuntimeError):
                xr.route('http://127.0.0.1:49641')

    def test_nonlocal_server_is_rejected(self):
        for value in ('https://127.0.0.1:49640','http://example.com:49640','http://127.0.0.1:49640/api','http://127.0.0.1:0'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                xr.server_url(value)

if __name__=='__main__':
    unittest.main()
