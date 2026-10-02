"""Exercise API discovery without starting the desktop GUI."""
import ast
import inspect
from pathlib import Path
import threading
import unittest

from desktop_reminders import ReminderEngine


class NativeWindowTrap:
    def __dir__(self):
        raise AssertionError('API discovery reached a native window')


def discover_api(obj, seen=None):
    # Match pywebview's public-attribute recursion, including property access.
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return
    seen.add(id(obj))
    for name in dir(obj):
        if name.startswith('_'):
            continue
        value = getattr(obj, name)
        if inspect.ismethod(value) or inspect.isfunction(value):
            continue
        if not callable(value) and hasattr(value, '__module__'):
            discover_api(value, seen)


class ReminderBridgeTests(unittest.TestCase):
    def test_bridge_discovery_with_all_popup_windows_open(self):
        source = Path(__file__).parents[1] / 'whattime_app.py'
        tree = ast.parse(source.read_text())
        api_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Api')
        module = ast.fix_missing_locations(ast.Module(body=[api_class], type_ignores=[]))
        env = {'threading': threading, 'ReminderEngine': ReminderEngine}
        exec(compile(module, str(source), 'exec'), env)
        api = env['Api']()
        windows = [name for name in vars(api) if name.endswith('_window')]
        self.assertEqual(len(windows), 6)
        for name in windows:
            setattr(api, name, NativeWindowTrap())
        discover_api(api)
        payload = {'id': 'preview', 'level': 'start'}
        api._desktop_payload = payload
        self.assertEqual(api.get_desktop_reminder(), payload)
        self.assertTrue(callable(api.close_desktop_reminder))
        self.assertTrue(callable(api.preview_desktop_reminder))

    def test_discovery_detects_public_native_window(self):
        class UnsafeApi:
            window = NativeWindowTrap()
        with self.assertRaisesRegex(AssertionError, 'native window'):
            discover_api(UnsafeApi())
