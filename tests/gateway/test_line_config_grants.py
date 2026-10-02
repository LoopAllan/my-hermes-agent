"""Config-only LINE grants remain profile/chat scoped (restored in PR #40)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform, PlatformConfig, load_gateway_config
from gateway.platform_registry import PlatformEntry, platform_registry
from gateway.session import SessionSource
from tests.gateway._plugin_adapter_loader import load_plugin_adapter
from tests.gateway.test_plugin_group_chat_authorization import _runner_for


@pytest.fixture
def line_entry(monkeypatch):
    module = load_plugin_adapter("line")
    captured = {}
    module.register(SimpleNamespace(register_platform=lambda **kw: captured.update(kw)))
    entry = PlatformEntry(**captured)
    monkeypatch.setitem(platform_registry._entries, "line", entry)
    for name in ("LINE_ALLOWED_GROUPS", "LINE_ALLOWED_ROOMS", "LINE_ALLOWED_USERS", "LINE_ALLOW_ALL_USERS",
                 "GATEWAY_ALLOW_ALL_USERS", "GATEWAY_ALLOWED_USERS"):
        monkeypatch.delenv(name, raising=False)
    return module


@pytest.mark.parametrize("placement", ["root", "gateway", "platforms"])
@pytest.mark.parametrize("opt_in", [True, False, "false"])
def test_yaml_to_config_only_group_room_grants(tmp_path, monkeypatch, line_entry, placement, opt_in):
    import hermes_yaml
    line = Platform("line")
    settings = {"enabled": True, "allowed_groups": ["C-ok"], "allowed_rooms": ["R-ok"],
                "authorize_allowed_chats": opt_in}
    config = ({"line": settings} if placement == "root" else
              {"gateway": {"platforms": {"line": settings}}} if placement == "gateway" else
              {"platforms": {"line": settings}})
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(hermes_yaml.safe_dump(config))
    loaded = load_gateway_config()
    extra = loaded.platforms[line].extra
    runner = _runner_for(line, extra=extra)
    runner.adapters[line].config = loaded.platforms[line]
    for kind, chat, expected in [("group", "C-ok", True), ("room", "R-ok", True),
                                 ("group", "R-ok", False), ("room", "C-ok", False),
                                 ("dm", "C-ok", False), ("group", "C-other", False)]:
        source = SessionSource(platform=line, chat_id=chat, chat_type=kind, user_id="U-unlisted")
        assert runner._is_user_authorized(source) is (expected and opt_in is True)


def test_secondary_profile_does_not_inherit_launch_grant(line_entry):
    line = Platform("line")
    runner = _runner_for(line, extra={"authorize_allowed_chats": True, "allowed_groups": ["C-shared"]})
    runner.adapters[line].config = runner.config.platforms[line]
    runner.config.multiplex_profiles = True
    runner._profile_adapters = {"worker": {line: SimpleNamespace(config=PlatformConfig(
        enabled=True, extra={"authorize_allowed_chats": False, "allowed_groups": ["C-shared"]}))}}
    source = SessionSource(platform=line, chat_id="C-shared", chat_type="group", user_id="U-other", profile="worker")
    assert runner._is_user_authorized(source) is False
    runner._profile_adapters["worker"][line].config.extra["authorize_allowed_chats"] = True
    assert runner._is_user_authorized(source) is True


@pytest.mark.asyncio
async def test_archive_only_after_authorization_before_mention_drop(tmp_path, line_entry):
    adapter = line_entry.LineAdapter(PlatformConfig(enabled=True, extra={
        "allowed_groups": ["C-ok"], "require_mention": True, "archive_unmentioned": True,
        "archive_path": str(tmp_path / "passive.jsonl"),
    }))
    adapter._bot_user_id = "U-bot"
    adapter._handle_message_event = AsyncMock()
    for chat in ("C-denied", "C-ok"):
        await adapter._dispatch_event({"type": "message", "source": {"type": "group", "groupId": chat,
            "userId": "U-other"}, "message": {"id": chat, "type": "text", "text": "passive"}})
    import json
    records = [json.loads(line) for line in (tmp_path / "passive.jsonl").read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["chat_id"] == "C-ok"
    assert records[0]["text"] == "passive"
    adapter._handle_message_event.assert_not_awaited()
