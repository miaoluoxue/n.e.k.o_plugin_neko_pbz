from __future__ import annotations

from plugin.plugins.neko_pbz.core.host_speech import HostSpeech


class _Plugin:
    def __init__(self, lanlan_name=""):
        self.calls = []
        self.ctx = type("Ctx", (), {"bus": None, "lanlan_name": lanlan_name})()

    def push_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"submitted": True}


def test_speak_image_sends_host_vision_parts():
    plugin = _Plugin()
    speech = HostSpeech(plugin, voice_enabled=True)
    ok = speech.speak_image("看画面", b"jpeg-bytes", "image/jpeg",
                            fallback="看到了", line_id="v1")
    assert ok and speech.waiting
    call = plugin.calls[-1]
    assert call["ai_behavior"] == "respond"
    assert call["visibility"] == []
    assert [p["type"] for p in call["parts"]] == ["text", "image"]
    assert call["parts"][1]["data"] == b"jpeg-bytes"
    assert call["parts"][1]["mime"] == "image/jpeg"


def test_note_vision_is_context_only():
    plugin = _Plugin()
    speech = HostSpeech(plugin, voice_enabled=True)
    assert speech.note_vision("观察结果", b"img", "image/jpeg")
    call = plugin.calls[-1]
    assert call["ai_behavior"] == "read"
    assert call["visibility"] == []
    assert call["parts"][1]["type"] == "image"


def test_event_prompt_is_llm_only_by_default():
    plugin = _Plugin()
    speech = HostSpeech(plugin, voice_enabled=True)
    assert speech.speak("事件事实", fallback="喵")
    call = plugin.calls[-1]
    assert call["ai_behavior"] == "respond"
    assert call["visibility"] == []


def test_prompt_can_be_shown_only_with_explicit_debug_switch():
    plugin = _Plugin()
    speech = HostSpeech(
        plugin, voice_enabled=True, show_prompt_in_chat=True)
    assert speech.speak("事件事实", fallback="喵")
    call = plugin.calls[-1]
    assert call["ai_behavior"] == "respond"
    assert call["visibility"] == ["chat"]


def test_push_carries_target_lanlan_for_multi_character_sessions():
    plugin = _Plugin("YUI")
    speech = HostSpeech(plugin, voice_enabled=True)
    assert speech.note_context("场景上下文")
    assert plugin.calls[-1]["target_lanlan"] == "YUI"


def test_target_lanlan_env_fallback(monkeypatch):
    plugin = _Plugin()
    monkeypatch.setenv("NEKO_TARGET_LANLAN", "Neko")
    speech = HostSpeech(plugin, voice_enabled=True)
    assert speech.note_context("场景上下文")
    assert plugin.calls[-1]["target_lanlan"] == "Neko"


def test_urgent_priority_can_replace_a_normal_pending_reply():
    plugin = _Plugin()
    speech = HostSpeech(plugin, voice_enabled=True)
    assert speech.speak("普通事件", line_id="normal", priority="P1")
    assert speech.speak("紧急事件", line_id="urgent", priority="P0")
    assert speech.pending_id == "urgent"
    assert speech.pending_priority == "P0"
    assert not speech.speak("后续普通事件", priority="P1")
