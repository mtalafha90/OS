"""Tests for Config loading, saving, and defaults."""
from __future__ import annotations

import os

import pytest

from llmos.config import DEFAULT_SYSTEM_PROMPT, Config


def test_config_defaults():
    cfg = Config()
    assert cfg.ollama_url == "http://localhost:11434"
    assert cfg.model == "llama3.2"
    assert cfg.max_history == 50
    assert cfg.show_tool_calls is True
    assert cfg.request_timeout == 120.0


def test_config_load_nonexistent_returns_defaults():
    cfg = Config.load(path="/tmp/__nonexistent_llmos_config_xyz__.yaml")
    assert cfg.model == "llama3.2"
    assert cfg.ollama_url == "http://localhost:11434"


def test_config_save_and_reload(tmp_path):
    cfg = Config(model="llama3.1", max_history=100, request_timeout=60.0)
    save_path = str(tmp_path / "config.yaml")
    cfg.save(path=save_path)

    assert os.path.exists(save_path)

    loaded = Config.load(path=save_path)
    assert loaded.model == "llama3.1"
    assert loaded.max_history == 100
    assert loaded.request_timeout == 60.0


def test_config_save_excludes_system_prompt(tmp_path):
    cfg = Config()
    save_path = str(tmp_path / "config.yaml")
    cfg.save(path=save_path)

    with open(save_path) as f:
        content = f.read()

    assert "system_prompt" not in content


def test_default_system_prompt_has_placeholders():
    for placeholder in ("{hostname}", "{user}", "{cwd}", "{os_release}", "{gpu_info}"):
        assert placeholder in DEFAULT_SYSTEM_PROMPT


def test_system_prompt_format():
    cfg = Config()
    formatted = cfg.system_prompt.format(
        hostname="testhost",
        user="tester",
        cwd="/home/tester",
        os_release="Ubuntu 24.04 LTS",
        gpu_info="NVIDIA A100",
    )
    assert "testhost" in formatted
    assert "tester" in formatted
    assert "Ubuntu 24.04" in formatted
    assert "NVIDIA A100" in formatted


def test_config_custom_values():
    cfg = Config(
        ollama_url="http://192.168.1.10:11434",
        model="mistral",
        max_history=20,
        show_tool_calls=False,
        request_timeout=30.0,
    )
    assert cfg.ollama_url == "http://192.168.1.10:11434"
    assert cfg.model == "mistral"
    assert cfg.max_history == 20
    assert cfg.show_tool_calls is False
    assert cfg.request_timeout == 30.0
