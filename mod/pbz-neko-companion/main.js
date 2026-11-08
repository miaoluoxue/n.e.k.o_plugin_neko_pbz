"use strict";
// PBZ Neko Companion: 只读状态 + 字幕。游戏原文件不改。
const UE = require("ue");
const api = require("./game_api");
const { Overlay } = require("./ui_bridge");

const bridge = api.bridgeDir();
let seq = 0;
let overlay = null;
let timer = null;
let heartbeatAt = 0;
let lastError = "";
let overlayError = "";

function writeFile(name, body) {
    if (!UE.EasyCsv || typeof UE.EasyCsv.SaveStringToFile !== "function") return false;
    const slot = String(name || "").replace(/\.json$/i, "").replace(/[^A-Za-z0-9_.-]/g, "_");
    return UE.EasyCsv.SaveStringToFile(String(body || ""), bridge + "/" + slot) === true;
}

function ensureOverlay() {
    if (overlay) return;
    try {
        overlay = new Overlay(bridge);
    } catch (error) {
        overlayError = String(error && error.stack || error);
    }
}

function writeStatus(stateReady) {
    writeFile("mod_status.json", JSON.stringify({
        version: 1,
        ts: Date.now() / 1000,
        state_ready: stateReady,
        overlay_ready: !!overlay?.ready,
        overlay_error: overlay?.overlayError || overlayError,
        error: lastError,
    }));
}

function tick() {
    try {
        ensureOverlay();
        if (overlay) overlay.tick();
        let state;
        try {
            state = api.snapshot();
        } catch (error) {
            lastError = String(error && error.stack || error);
            writeStatus(false);
            return;
        }
        state.seq = ++seq;
        state.game = {
            ...(state.game || {}),
            overlay_ready: !!overlay?.ready,
            overlay_error: overlay?.overlayError || overlayError,
            mod_ready: true,
        };
        if (!writeFile("state.json", JSON.stringify(state))) {
            lastError = "state.json write failed";
        } else {
            lastError = "";
        }
        writeStatus(true);
        if (Date.now() - heartbeatAt > 2000) {
            heartbeatAt = Date.now();
            writeFile("game_heartbeat", JSON.stringify({
                version: 1, ts: Date.now() / 1000, game_seq: seq,
                plugin_seq: 0, status: lastError ? "degraded" : "ok",
                error: lastError,
                overlay_ready: !!overlay?.ready,
                overlay_error: overlay?.overlayError || overlayError,
            }));
        }
    } catch (error) {
        lastError = String(error && error.stack || error);
        writeStatus(false);
        console.error("[NekoPBZ] tick failed: " + lastError);
    }
}

try {
    ensureOverlay();
    tick();
    timer = setInterval(tick, 250);
    console.log("[NekoPBZ] ready bridge=" + bridge +
        " overlay=" + !!overlay?.ready + " overlayError=" + overlayError);
} catch (error) {
    lastError = String(error && error.stack || error);
    console.error("[NekoPBZ] start failed: " + lastError);
}

function stop() {
    if (timer !== null) { clearInterval(timer); timer = null; }
    try { overlay?.stop(); } catch (_) {}
    overlay = null;
    console.log("[NekoPBZ] stopped");
}

module.exports = { stop };
