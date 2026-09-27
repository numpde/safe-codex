"""Trusted qualification suite; candidate code runs only in child interpreters."""
import base64
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import unittest

try:
    _libc = ctypes.CDLL(None, use_errno=True)
    if _libc.prctl(4, 0, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_DUMPABLE")
except (AttributeError, OSError) as error:
    raise RuntimeError("cannot make verifier undumpable") from error

_RUNNER = r'''
import contextlib, importlib.util, json, sys
spec = importlib.util.spec_from_file_location("candidate", "/workspace/duration.py")
module = importlib.util.module_from_spec(spec)
try:
    with open("/dev/null", "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        spec.loader.exec_module(module)
        request = json.load(sys.stdin)
        value = request["value"]
        if request.get("bytes"):
            import base64
            value = base64.b64decode(value)
        try:
            result = module.parse_duration(value)
        except Exception as error:
            result = {"error": type(error).__name__}
        else:
            result = {"value": result}
    print(json.dumps(result, separators=(",", ":")))
except BaseException:
    raise SystemExit(2)
'''

def run_candidate(value):
    request = {"value": value}
    if isinstance(value, bytes):
        request = {"value": base64.b64encode(value).decode(), "bytes": True}
    process = subprocess.Popen([sys.executable, "-I", "-c", _RUNNER], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        stdout, _ = process.communicate(json.dumps(request).encode(), timeout=2)
    except subprocess.TimeoutExpired:
        process.kill(); process.communicate()
        raise AssertionError("candidate execution timed out")
    if process.returncode != 0 or len(stdout) > 1024 * 1024:
        raise AssertionError("candidate execution failed")
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeDecodeError) as error:
        raise AssertionError("candidate returned invalid result") from error
    if not isinstance(result, dict) or set(result) not in ({"value"}, {"error"}):
        raise AssertionError("candidate returned invalid result shape")
    return result

class Contract(unittest.TestCase):
    def test_valid(self):
        for text, value in [("1h30m", 5400), ("45s 2m", 165), ("0s", 0),
                            (" 2h 3m 4s ", 7384), ("0005m", 300),
                            ("1s1h", 3601), ("100000h", 360000000)]:
            with self.subTest(text=text):
                self.assertEqual(run_candidate(text), {"value": value})

    def test_invalid(self):
        for text in ["", " ", "1", "1h1h", "1h 2h", "-1s", "1.5h", "1d",
                     "1h junk", "junk 1h", "1H", "1 h", "1m+2s"]:
            with self.subTest(text=text):
                self.assertEqual(run_candidate(text), {"error": "ValueError"})

    def test_types(self):
        for value in [None, 3, 1.5, [], b"1h"]:
            with self.subTest(value=value):
                self.assertEqual(run_candidate(value), {"error": "TypeError"})

    def test_state(self):
        state = Path("/workspace/.agent/STATE.md").read_text()
        self.assertIn("Objective", state)
        self.assertIn("Tests", state)

if __name__ == "__main__":
    unittest.main(verbosity=2)
