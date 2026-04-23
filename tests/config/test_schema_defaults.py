"""配置 schema 默认值测试。"""

from elebot.config.schema import Config


def test_default_model_is_qwen3_6_plus() -> None:
    """默认模型固定为 qwen3_6_plus。"""
    cfg = Config()
    assert cfg.agents.defaults.model == "qwen3_6_plus"


def test_default_provider_is_dashscope() -> None:
    """默认 provider 固定为 dashscope。"""
    cfg = Config()
    assert cfg.agents.defaults.provider == "dashscope"
    assert cfg.get_provider_name() == "dashscope"


def test_reads_elebot_env_prefix(monkeypatch) -> None:
    """支持 ELEBOT_ 前缀读取配置。"""
    monkeypatch.setenv("ELEBOT_AGENTS__DEFAULTS__MODEL", "env/model")
    cfg = Config()
    assert cfg.agents.defaults.model == "env/model"


def test_ignores_legacy_nanobot_env_prefix(monkeypatch) -> None:
    """不再兼容 NANOBOT_ 前缀。"""
    monkeypatch.delenv("ELEBOT_AGENTS__DEFAULTS__MODEL", raising=False)
    monkeypatch.setenv("NANOBOT_AGENTS__DEFAULTS__MODEL", "legacy/model")
    cfg = Config()
    assert cfg.agents.defaults.model == "qwen3_6_plus"
