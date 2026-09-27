#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import launch


class NativeStreamModeTests(unittest.TestCase):
    def test_print_and_rpc_disable_tty(self):
        self.assertTrue(launch.native_stream_mode(["-p", "hello"]))
        self.assertTrue(launch.native_stream_mode(["--mode", "rpc"]))

    def test_profiles_are_backend_scoped(self):
        vllm = launch.arguments(["--workspace", ".", "--profile", "same", "--backend", "vllm"])
        exl3 = launch.arguments(["--workspace", ".", "--profile", "same", "--backend", "exl3"])
        self.assertNotEqual(launch.profile_path(vllm), launch.profile_path(exl3))

    def test_profiles_are_workspace_mode_scoped(self):
        copied = launch.arguments(["--workspace", ".", "--profile", "same"])
        readonly = launch.arguments(["--workspace", ".", "--profile", "same",
                                     "--workspace-ro"])
        self.assertEqual(copied.workspace_mode, "copy")
        self.assertEqual(readonly.workspace_mode, "ro")
        self.assertNotEqual(launch.profile_path(copied), launch.profile_path(readonly))

    def test_direct_writable_host_workspace_is_rejected(self):
        with self.assertRaises(SystemExit):
            launch.arguments(["--workspace-rw"])

    def test_interactive_native_flags_keep_tty(self):
        self.assertFalse(launch.native_stream_mode(["-c"]))
        self.assertFalse(launch.native_stream_mode(["--model", "local"]))

    def test_mode_terminator_and_last_mode_follow_parser(self):
        self.assertFalse(launch.native_stream_mode(["--", "--mode", "rpc"]))
        self.assertFalse(launch.native_stream_mode(["--mode", "rpc", "--mode", "text"]))


class TerminalCommandTests(unittest.TestCase):
    @patch("launch.subprocess.run")
    def test_print_mode_uses_pipe_even_when_host_is_tty(self, run):
        run.return_value.returncode = 0
        stdin, stdout = Mock(), Mock()
        stdin.isatty.return_value = stdout.isatty.return_value = True
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            self.assertEqual(launch.terminal_command(Mock(agent="agent"), ["-p", "hello"]), 0)
        self.assertEqual(run.call_args.args[0][2], "-i")
    @patch("launch.subprocess.run")
    def test_print_mode_closes_unused_terminal_stdin(self, run):
        run.return_value.returncode = 0
        stdin, stdout = Mock(), Mock()
        stdin.isatty.return_value = stdout.isatty.return_value = True
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            launch.terminal_command(Mock(agent="agent"), ["-p", "hello"])
        self.assertIs(run.call_args.kwargs["stdin"], launch.subprocess.DEVNULL)

    @patch("launch.subprocess.run")
    def test_print_mode_preserves_piped_stdin(self, run):
        run.return_value.returncode = 0
        stdin, stdout = Mock(), Mock()
        stdin.isatty.return_value = stdout.isatty.return_value = False
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            launch.terminal_command(Mock(agent="agent"), ["-p", "hello"])
        self.assertIsNone(run.call_args.kwargs["stdin"])

    @patch("launch.subprocess.run")
    def test_rpc_preserves_terminal_stdin_for_protocol_input(self, run):
        run.return_value.returncode = 0
        stdin, stdout = Mock(), Mock()
        stdin.isatty.return_value = stdout.isatty.return_value = True
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            launch.terminal_command(Mock(agent="agent"), ["--mode", "rpc"])
        self.assertIsNone(run.call_args.kwargs["stdin"])

    @patch("launch.subprocess.run")
    def test_continuation_keeps_tty(self, run):
        run.return_value.returncode = 0
        stdin, stdout = Mock(), Mock()
        stdin.isatty.return_value = stdout.isatty.return_value = True
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout), \
             patch("launch.termios.tcgetattr", return_value=[]), \
             patch("launch.termios.tcsetattr"):
            self.assertEqual(launch.terminal_command(Mock(agent="agent"), ["-c"]), 0)
        self.assertEqual(run.call_args.args[0][2], "-it")


class RestoreTests(unittest.TestCase):
    @patch("launch.docker")
    def test_readonly_profile_restores_sessions_only(self, docker):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory)
            (previous / "sessions-session.tar").write_bytes(b"session archive")
            launch.restore(SimpleNamespace(agent="agent"), previous, "ro")
        calls = [call.args for call in docker.call_args_list]
        self.assertTrue(any("/sessions" in call for call in calls))
        self.assertFalse(any("/workspace" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
