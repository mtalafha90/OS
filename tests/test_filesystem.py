"""Tests for filesystem tools."""
from __future__ import annotations

import pytest

from llmos.tools.filesystem import (
    copy_path,
    create_directory,
    delete_path,
    get_disk_usage,
    list_directory,
    move_path,
    read_file,
    search_files,
    write_file,
)


def test_list_directory(tmp_path):
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.py").write_text("b")
    result = list_directory(str(tmp_path))
    assert "alpha.txt" in result
    assert "beta.py" in result


def test_list_directory_hidden_excluded(tmp_path):
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "visible.txt").write_text("y")
    result = list_directory(str(tmp_path), show_hidden=False)
    assert ".hidden" not in result
    assert "visible.txt" in result


def test_list_directory_hidden_included(tmp_path):
    (tmp_path / ".hidden").write_text("x")
    result = list_directory(str(tmp_path), show_hidden=True)
    assert ".hidden" in result


def test_list_directory_nonexistent():
    result = list_directory("/tmp/__nonexistent_dir_xyz__")
    assert "Error" in result


def test_list_directory_file_path(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hi")
    result = list_directory(str(f))
    assert "Error" in result


def test_read_file(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("line1\nline2\nline3\n")
    result = read_file(str(f))
    assert "line1" in result
    assert "line2" in result
    assert "line3" in result


def test_read_file_line_range(tmp_path):
    f = tmp_path / "range.txt"
    f.write_text("A\nB\nC\nD\n")
    result = read_file(str(f), start_line=2, end_line=3)
    assert "B" in result
    assert "C" in result
    assert "A" not in result
    assert "D" not in result


def test_read_file_nonexistent():
    result = read_file("/tmp/__no_such_file_xyz__.txt")
    assert "Error" in result


def test_write_file_creates(tmp_path):
    f = tmp_path / "out.txt"
    result = write_file(str(f), "hello world")
    assert "Wrote" in result or "Appended" in result
    assert f.read_text() == "hello world"


def test_write_file_overwrite(tmp_path):
    f = tmp_path / "over.txt"
    f.write_text("old")
    write_file(str(f), "new")
    assert f.read_text() == "new"


def test_write_file_append(tmp_path):
    f = tmp_path / "log.txt"
    write_file(str(f), "first\n")
    write_file(str(f), "second\n", append=True)
    assert f.read_text() == "first\nsecond\n"


def test_write_file_creates_parents(tmp_path):
    f = tmp_path / "a" / "b" / "c.txt"
    write_file(str(f), "deep")
    assert f.exists()
    assert f.read_text() == "deep"


def test_create_directory(tmp_path):
    newdir = tmp_path / "x" / "y" / "z"
    result = create_directory(str(newdir))
    assert newdir.is_dir()
    assert "Created" in result


def test_delete_file(tmp_path):
    f = tmp_path / "del.txt"
    f.write_text("gone")
    result = delete_path(str(f))
    assert not f.exists()
    assert "Deleted" in result


def test_delete_nonexistent():
    result = delete_path("/tmp/__no_such_path_xyz__")
    assert "Error" in result


def test_delete_dir_requires_recursive(tmp_path):
    d = tmp_path / "nonempty"
    d.mkdir()
    result = delete_path(str(d))
    assert "Error" in result or "recursive" in result.lower()


def test_delete_dir_recursive(tmp_path):
    d = tmp_path / "tree"
    d.mkdir()
    (d / "sub").mkdir()
    (d / "sub" / "f.txt").write_text("hi")
    result = delete_path(str(d), recursive=True)
    assert not d.exists()
    assert "Deleted" in result


def test_move_file(tmp_path):
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("content")
    result = move_path(str(src), str(dst))
    assert dst.exists()
    assert not src.exists()
    assert "Moved" in result


def test_move_nonexistent():
    result = move_path("/tmp/__no_such_src__", "/tmp/__dst__")
    assert "Error" in result


def test_copy_file(tmp_path):
    src = tmp_path / "orig.txt"
    dst = tmp_path / "copy.txt"
    src.write_text("original")
    result = copy_path(str(src), str(dst))
    assert dst.exists()
    assert dst.read_text() == "original"
    assert src.exists()


def test_search_files_by_name(tmp_path):
    (tmp_path / "alpha.py").write_text("x = 1")
    (tmp_path / "beta.txt").write_text("y = 2")
    result = search_files(str(tmp_path), name_pattern="*.py")
    assert "alpha.py" in result
    assert "beta.txt" not in result


def test_search_files_by_content(tmp_path):
    (tmp_path / "hay.txt").write_text("nothing useful here")
    (tmp_path / "needle.txt").write_text("the_needle is here")
    result = search_files(str(tmp_path), content_pattern="the_needle")
    assert "needle.txt" in result
    assert "hay.txt" not in result


def test_search_files_no_match(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    result = search_files(str(tmp_path), content_pattern="__no_match_xyz__")
    assert "No matches" in result


def test_get_disk_usage():
    result = get_disk_usage("/")
    assert "Total" in result
    assert "Used" in result
    assert "Free" in result
