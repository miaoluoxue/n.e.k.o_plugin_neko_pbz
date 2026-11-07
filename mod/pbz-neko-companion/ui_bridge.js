"use strict";
// 游戏内字幕 + 与 UE4SS Lua 的隐形容器握手（避开 PuerTS 不能读文件的问题）。
const UE = require("ue");
const puerts = require("puerts");

const gi = puerts.argv.getByName("GameInstance");
const READY = "PBZ_NEKO_READY|";
const MSG = "PBZ_NEKO_MSG|";
const CMD = "PBZ_NEKO_CMD|";

function safe(fn, fallback = null) {
    try { const v = fn(); return v === undefined ? fallback : v; }
    catch (_) { return fallback; }
}
function fontFor(widget, size) {
    try {
        const name = "Textstyle_Main_CN";
        const style = UE.SGameAIFunctionLibrary.GetClassDefaultObject(
            UE.Class.Load("/Game/PBZContent/UI/UINew/System/Character/" + name + "." + name + "_C"));
        if (style?.Font?.FontObject) widget.SetFont(style.Font);
    } catch (_) { /* 默认字体兜底 */ }
    const font = safe(() => widget.Font, null);
    if (font) { font.Size = size; widget.SetFont(font); }
}
function makeText(size) {
    const t = new UE.TextBlock(gi);
    fontFor(t, size);
    t.SetAutoWrapText(true);
    safe(() => t.SetJustification(UE.ETextJustify.Center), null);
    t.SetColorAndOpacity(new UE.SlateColor(
        new UE.LinearColor(0.95, 0.92, 0.86, 1),
        UE.ESlateColorStylingMode.UseColor_Specified));
    return t;
}

class Overlay {
    constructor(bridgeDir) {
        this.bridgeDir = bridgeDir;
        this.viewport = safe(() => UE.SubsystemBlueprintLibrary.GetEngineSubsystem(
            UE.GameViewportSubsystem.StaticClass()), null);
        this.border = null;
        this.text = null;
        this.slot = null;
        this.mailbox = null;
        this.mailSlot = null;
        this.expireAt = 0;
        this.hidden = false;
        this._create();
    }

    _create() {
        if (!this.viewport) throw new Error("viewport unavailable");
        this.text = makeText(17);
        this.border = UE.NewObject(UE.Border.StaticClass(), gi);
        this.border.SetPadding(new UE.Margin(16, 10, 16, 10));
        this.border.SetBrushColor(new UE.LinearColor(0.015, 0.018, 0.022, 0.72));
        this.border.SetContent(this.text);
        this.border.SetVisibility(UE.ESlateVisibility.Collapsed);
        this.slot = new UE.GameViewportWidgetSlot();
        this.slot.ZOrder = 900000;
        this.slot.bAutoRemoveOnWorldRemoved = true;
        this._layout();
        if (!this.viewport.AddWidget(this.border, this.slot)) {
            throw new Error("AddWidget failed");
        }

        this.mailbox = makeText(1);
        this.mailbox.SetText(UE.KismetTextLibrary.Conv_StringToText(READY + this.bridgeDir));
        this.mailbox.SetVisibility(UE.ESlateVisibility.Collapsed);
        this.mailSlot = new UE.GameViewportWidgetSlot();
        this.mailSlot.ZOrder = 900001;
        this.mailSlot.bAutoRemoveOnWorldRemoved = true;
        const m = new UE.Margin();
        m.Left = 2; m.Top = 2; m.Right = 60; m.Bottom = 20;
        this.mailSlot.Offsets = m;
        this.viewport.AddWidget(this.mailbox, this.mailSlot);
    }

    _layout() {
        const size = safe(() => UE.WidgetLayoutLibrary.GetViewportSize(gi), null);
        const w = Number(size?.X) || 1920;
        const h = Number(size?.Y) || 1080;
        const m = new UE.Margin();
        m.Left = Math.round(w * 0.20);
        m.Right = Math.round(w * 0.80);
        m.Top = Math.round(h - 168);
        m.Bottom = Math.round(h - 92);
        this.slot.Offsets = m;
    }

    show(line, ttl) {
        if (!this.border) return;
        this.text.SetText(UE.KismetTextLibrary.Conv_StringToText(String(line || "")));
        this.expireAt = Date.now() + Math.max(1500, (Number(ttl) || 6) * 1000);
        if (!this.hidden) this.border.SetVisibility(UE.ESlateVisibility.HitTestInvisible);
    }

    _readMailbox() {
        if (!this.mailbox) return;
        const raw = safe(() => this.mailbox.GetText().ToString(), "");
        if (!raw || raw.startsWith(READY)) return;
        if (raw.startsWith(MSG)) {
            const body = raw.slice(MSG.length);
            const sep = body.lastIndexOf("|");
            const line = sep >= 0 ? body.slice(0, sep) : body;
            const ttl = sep >= 0 ? Number(body.slice(sep + 1)) : 6;
            this.show(line, ttl);
            this.mailbox.SetText(UE.KismetTextLibrary.Conv_StringToText(READY + this.bridgeDir));
            return;
        }
        if (raw.startsWith(CMD) && raw.includes("toggle")) {
            this.hidden = !this.hidden;
            this.border.SetVisibility(this.hidden
                ? UE.ESlateVisibility.Collapsed
                : UE.ESlateVisibility.HitTestInvisible);
            this.mailbox.SetText(UE.KismetTextLibrary.Conv_StringToText(READY + this.bridgeDir));
        }
    }

    tick() {
        this._readMailbox();
        if (this.expireAt && Date.now() > this.expireAt) {
            this.expireAt = 0;
            if (this.border) this.border.SetVisibility(UE.ESlateVisibility.Collapsed);
        }
        this._layout();
    }

    stop() {
        try { if (this.border) this.viewport.RemoveWidget(this.border); } catch (_) {}
        try { if (this.mailbox) this.viewport.RemoveWidget(this.mailbox); } catch (_) {}
        this.border = this.text = this.slot = this.mailbox = this.mailSlot = null;
    }
}

module.exports = { Overlay };
