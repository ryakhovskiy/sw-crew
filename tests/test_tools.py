"""Tests for sandboxed file and shell tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew.tools.files import PathEscapeError, list_files, read_file, write_file
from crew.tools.shell import run_bash

# -- File tools ---------------------------------------------------------------

class TestFileTools:
    def test_write_and_read(self, tmp_path: Path):
        write_file(tmp_path, "hello.txt", "world")
        assert read_file(tmp_path, "hello.txt") == "world"

    def test_write_nested(self, tmp_path: Path):
        write_file(tmp_path, "a/b/c.txt", "deep")
        assert read_file(tmp_path, "a/b/c.txt") == "deep"

    def test_list_files(self, tmp_path: Path):
        write_file(tmp_path, "file1.py", "x")
        (tmp_path / "subdir").mkdir()
        entries = list_files(tmp_path)
        assert "file1.py" in entries
        assert "subdir/" in entries

    def test_read_nonexistent(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            read_file(tmp_path, "nope.txt")

    def test_escape_dotdot(self, tmp_path: Path):
        with pytest.raises(PathEscapeError):
            read_file(tmp_path, "../../../etc/passwd")

    def test_escape_absolute(self, tmp_path: Path):
        with pytest.raises(PathEscapeError):
            # An absolute path outside workspace should be rejected
            write_file(tmp_path, "/tmp/evil.txt", "bad")


# -- Shell tools --------------------------------------------------------------

class TestShellTools:
    def test_echo(self, tmp_path: Path):
        stdout, stderr, rc = run_bash(tmp_path, "echo hello")
        assert "hello" in stdout
        assert rc == 0

    def test_cwd_is_workspace(self, tmp_path: Path):
        write_file(tmp_path, "marker.txt", "found")
        cmd = "type marker.txt" if Path("C:/").exists() else "cat marker.txt"
        stdout, _, rc = run_bash(tmp_path, cmd)
        assert "found" in stdout
        assert rc == 0

    def test_nonexistent_workspace(self):
        with pytest.raises(FileNotFoundError):
            run_bash(Path("/nonexistent/workspace"), "echo hi")
