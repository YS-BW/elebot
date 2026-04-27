"""配置 schema 默认值测试。"""

from elebot.config.schema import Config


def test_default_model_is_deepseek_v4_flash() -> None:
    """默认模型固定为 deepseek-v4-flash。"""
    cfg = Config()
    assert cfg.agents.defaults.model == "deepseek-v4-flash"


def test_default_provider_is_deepseek() -> None:
    """默认 provider 固定为 deepseek。"""
    cfg = Config()
    assert cfg.agents.defaults.provider == "deepseek"


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
    assert cfg.agents.defaults.model == "deepseek-v4-flash"
