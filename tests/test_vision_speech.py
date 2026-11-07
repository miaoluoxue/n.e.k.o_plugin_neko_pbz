from __future__ import annotations

from plugin.plugins.neko_pbz.core.host_speech import HostSpeech


class _Plugin:
    def __init__(self):
        self.calls = []
        self.ctx = type("Ctx", (), {"bus": None, "lanlan_name": ""})()

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
