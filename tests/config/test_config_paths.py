from pathlib import Path

from elebot.config.loader import get_config_path
from elebot.config.paths import (
    get_cli_history_path,
    get_data_dir,
    get_logs_dir,
    get_media_dir,
    get_runtime_subdir,
    get_workspace_path,
    is_default_workspace,
)


def test_default_config_path_under_elebot_home(monkeypatch) -> None:
    monkeypatch.setattr("elebot.config.loader._current_config_path", None)
    assert get_config_path() == Path.home() / ".elebot" / "config.json"


def test_runtime_dirs_follow_config_path(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-a" / "config.json"
    monkeypatch.setattr("elebot.config.paths.get_config_path", lambda: config_file)

    assert get_data_dir() == config_file.parent
    assert get_runtime_subdir("cron") == config_file.parent / "cron"
    assert get_logs_dir() == config_file.parent / "logs"


def test_media_dir_supports_channel_namespace(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-b" / "config.json"
    monkeypatch.setattr("elebot.config.paths.get_config_path", lambda: config_file)

    assert get_media_dir() == config_file.parent / "media"
    assert get_media_dir("telegram") == config_file.parent / "media" / "telegram"

def test_shared_paths_remain_global() -> None:
    assert get_cli_history_path() == Path.home() / ".elebot" / "history" / "cli_history"


def test_workspace_path_is_explicitly_resolved() -> None:
    assert get_workspace_path() == Path.home() / ".elebot" / "workspace"
    assert get_workspace_path("~/custom-workspace") == Path.home() / "custom-workspace"


def test_is_default_workspace_distinguishes_default_and_custom_paths() -> None:
    assert is_default_workspace(None) is True
    assert is_default_workspace(Path.home() / ".elebot" / "workspace") is True
    assert is_default_workspace("~/custom-workspace") is False
