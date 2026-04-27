"""Tests for the restructured MemoryStore — pure file I/O layer."""

import json

import pytest

from elebot.agent.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


class TestMemoryStoreBasicIO:
    def test_read_memory_returns_empty_when_missing(self, store):
        assert store.read_memory() == ""

    def test_write_and_read_memory(self, store):
        store.write_memory("hello")
        assert store.read_memory() == "hello"

    def test_read_soul_returns_empty_when_missing(self, store):
        assert store.read_soul() == ""

    def test_write_and_read_soul(self, store):
        store.write_soul("soul content")
        assert store.read_soul() == "soul content"

    def test_read_user_returns_empty_when_missing(self, store):
        assert store.read_user() == ""

    def test_write_and_read_user(self, store):
        store.write_user("user content")
        assert store.read_user() == "user content"

    def test_get_memory_context_returns_empty_when_missing(self, store):
        assert store.get_memory_context() == ""

    def test_get_memory_context_returns_formatted_content(self, store):
        store.write_memory("important fact")
        ctx = store.get_memory_context()
        assert "长期记忆" in ctx
        assert "important fact" in ctx


class TestHistoryWithCursor:
    def test_append_history_returns_cursor(self, store):
        cursor = store.append_history("event 1")
        assert cursor == 1
        cursor2 = store.append_history("event 2")
        assert cursor2 == 2

    def test_append_history_includes_cursor_in_file(self, store):
        store.append_history("event 1")
        content = store.read_file(store.history_file)
        data = json.loads(content)
        assert data["cursor"] == 1

    def test_cursor_persists_across_appends(self, store):
        store.append_history("event 1")
        store.append_history("event 2")
        cursor = store.append_history("event 3")
        assert cursor == 3

    def test_read_unprocessed_history(self, store):
        store.append_history("event 1")
        store.append_history("event 2")
        store.append_history("event 3")
        entries = store.read_unprocessed_history(since_cursor=1)
        assert len(entries) == 2
        assert entries[0]["cursor"] == 2

    def test_read_unprocessed_history_returns_all_when_cursor_zero(self, store):
        store.append_history("event 1")
        store.append_history("event 2")
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 2

    def test_compact_history_drops_oldest(self, tmp_path):
        store = MemoryStore(tmp_path, max_history_entries=2)
        store.append_history("event 1")
        store.append_history("event 2")
        store.append_history("event 3")
        store.append_history("event 4")
        store.append_history("event 5")
        store.compact_history()
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 2
        assert entries[0]["cursor"] in {4, 5}


class TestDreamCursor:
    def test_initial_cursor_is_zero(self, store):
        assert store.get_last_dream_cursor() == 0

    def test_set_and_get_cursor(self, store):
        store.set_last_dream_cursor(5)
        assert store.get_last_dream_cursor() == 5

    def test_cursor_persists(self, store):
        store.set_last_dream_cursor(3)
        store2 = MemoryStore(store.workspace)
        assert store2.get_last_dream_cursor() == 3


class TestLegacyHistoryCleanup:
    def test_read_unprocessed_history_handles_entries_without_cursor(self, store):
        """JSONL entries with cursor=1 are correctly parsed and returned."""
        store.history_file.write_text(
            '{"cursor": 1, "timestamp": "2026-03-30 14:30", "content": "Old event"}\n',
            encoding="utf-8")
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["cursor"] == 1

    def test_init_removes_legacy_history_and_backup_files(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "HISTORY.md").write_text("legacy", encoding="utf-8")
        (memory_dir / "HISTORY.md.bak").write_text("backup", encoding="utf-8")
        (memory_dir / "HISTORY.md.bak.2").write_text("backup2", encoding="utf-8")

        MemoryStore(tmp_path)

        assert not (memory_dir / "HISTORY.md").exists()
        assert not (memory_dir / "HISTORY.md.bak").exists()
        assert not (memory_dir / "HISTORY.md.bak.2").exists()

    def test_init_keeps_current_history_jsonl_while_removing_legacy_files(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        history_file = memory_dir / "history.jsonl"
        history_file.write_text(
            '{"cursor": 7, "timestamp": "2026-04-01 12:00", "content": "existing"}\n',
            encoding="utf-8",
        )
        (memory_dir / "HISTORY.md").write_text("legacy", encoding="utf-8")
        (memory_dir / "HISTORY.md.bak").write_text("backup", encoding="utf-8")

        store = MemoryStore(tmp_path)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["cursor"] == 7
        assert entries[0]["content"] == "existing"
        assert not (memory_dir / "HISTORY.md").exists()
        assert not (memory_dir / "HISTORY.md.bak").exists()


class TestDreamHistoryOwnerApi:
    def test_show_dream_version_reports_never_run_before_init(self, store):
        result = store.show_dream_version()

        assert result.status == "never_run"

    def test_list_and_show_dream_versions_after_commit(self, store):
        store.git.init()
        store.write_soul("updated soul")
        sha = store.git.auto_commit("dream: latest, 1 change(s)")

        versions = store.list_dream_versions()
        result = store.show_dream_version()

        assert versions[0].sha == sha
        assert result.status == "ok"
        assert result.commit is not None
        assert result.commit.sha == sha
        assert "SOUL.md" in result.changed_files

    def test_restore_dream_version_returns_new_safe_commit(self, store):
        store.git.init()
        store.write_soul("updated soul")
        sha = store.git.auto_commit("dream: latest, 1 change(s)")

        result = store.restore_dream_version(sha)

        assert result.status == "ok"
        assert result.new_sha is not None
        assert "SOUL.md" in result.changed_files
