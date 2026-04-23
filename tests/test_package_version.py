from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import tomllib


def test_source_checkout_import_uses_pyproject_version_without_metadata() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    expected = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    script = textwrap.dedent(
        f"""
        import sys
        import types

        sys.path.insert(0, {str(repo_root)!r})
        fake = types.ModuleType("elebot.facade")
        fake.Elebot = object
        fake.RunResult = object
        sys.modules["elebot.facade"] = fake

        import elebot

        print(elebot.__version__)
        """
    )

    proc = subprocess.run(
        [sys.executable, "-S", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == expected


def test_source_checkout_exports_elebot_facade_without_metadata() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = textwrap.dedent(
        f"""
        import sys
        import types

        sys.path.insert(0, {str(repo_root)!r})
        fake = types.ModuleType("elebot.facade")
        fake.Elebot = object
        fake.RunResult = object
        sys.modules["elebot.facade"] = fake

        import elebot

        print(",".join(elebot.__all__))
        print(elebot.Elebot is fake.Elebot)
        """
    )

    proc = subprocess.run(
        [sys.executable, "-S", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert lines == ["Elebot,RunResult", "True"]


def test_module_entrypoint_calls_cli_app(monkeypatch) -> None:
    import elebot.__main__ as module

    called: list[str] = []

    monkeypatch.setattr(module, "cli_app", lambda: called.append("ok"))

    module.main()

    assert called == ["ok"]
