"""配置 schema 默认值测试。"""

from elebot.config.schema import Config


def test_default_model_is_mimo_v2_5() -> None:
    """默认模型固定为 mimo-v2.5。"""
    cfg = Config()
    assert cfg.agents.defaults.model == "mimo-v2.5"


def test_default_provider_is_xiaomi_mimo() -> None:
    """默认 provider 固定为 xiaomi_mimo。"""
    cfg = Config()
    assert cfg.agents.defaults.provider == "xiaomi_mimo"


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
    assert cfg.agents.defaults.model == "mimo-v2.5"


def test_weixin_channel_defaults() -> None:
    """个人微信 channel 默认配置应固定为文本版最小入口。"""
    cfg = Config()
    assert cfg.channels.weixin.enabled is False
    assert cfg.channels.weixin.allow_from == ["*"]
    assert cfg.channels.weixin.base_url == "https://ilinkai.weixin.qq.com"
    assert cfg.channels.weixin.token == ""
    assert cfg.channels.weixin.state_dir == ""
    assert cfg.channels.weixin.poll_timeout == 35


def test_transcription_defaults() -> None:
    """语音转写默认配置应固定为单一 qwen3-asr-flash 入口。"""
    cfg = Config()
    assert cfg.transcription.api_key == ""
    assert cfg.transcription.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
