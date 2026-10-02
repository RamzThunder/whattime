import ast
from pathlib import Path
import unittest


class UpdateTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).parents[1] / 'whattime_app.py'
        tree = ast.parse(source.read_text())
        methods = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name in ('_version_tuple', '_build_update_result')]
        self.env = {'APP_VERSION': '3.1.0', 'IS_MAC': True}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), self.env)

    def result(self, assets, version='v3.1.1'):
        return self.env['_build_update_result']({'tag_name': version, 'assets': [
            {'name': name, 'browser_download_url': 'https://example.com/' + name}
            for name in assets]})

    def test_mac_notifies_windows_only_release_without_error(self):
        result = self.result(['whattime.exe'])
        self.assertFalse(result['has_update'])
        self.assertEqual(result['other_platform_release'], 'Windows')
        self.assertNotIn('error', result)
        self.assertNotIn('url', result)

    def test_windows_still_receives_installer(self):
        self.env['IS_MAC'] = False
        self.assertTrue(self.result(['whattime.exe'])['has_update'])

    def test_windows_notifies_mac_only_release_without_error(self):
        self.env['IS_MAC'] = False
        result = self.result(['WhatTime-mac.dmg'])
        self.assertFalse(result['has_update'])
        self.assertEqual(result['other_platform_release'], 'macOS')
        self.assertNotIn('error', result)
        self.assertNotIn('url', result)

    def test_mac_update_and_current_version(self):
        self.assertTrue(self.result(['WhatTime-mac.dmg', 'whattime.exe'])['has_update'])
        self.assertNotIn('other_platform_release', self.result(['whattime.exe'], 'v3.1.0'))

    def test_empty_release_and_network_failure_remain_errors(self):
        self.assertIn('error', self.result([]))
        self.assertEqual(self.env['_build_update_result']({'_error': 'offline'})['error'], 'offline')
