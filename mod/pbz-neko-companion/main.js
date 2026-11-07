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

function writeFile(name, body) {
    return !!UE.EasyCsv.SaveStringToFile(body, bridge + "/" + name);
}

function tick() {
    try {
        const state = api.snapshot();
        state.seq = ++seq;
        writeFile("state.json", JSON.stringify(state));
        if (overlay) overlay.tick();
        if (Date.now() - heartbeatAt > 2000) {
            heartbeatAt = Date.now();
            writeFile("heartbeat.json", JSON.stringify({
                version: 1, ts: Date.now() / 1000, game_seq: seq,
                plugin_seq: 0, status: lastError ? "degraded" : "ok",
                error: lastError,
            }));
        }
    } catch (error) {
        lastError = String(error && error.stack || error);
        console.error("[NekoPBZ] tick failed: " + lastError);
    }
}

try {
    overlay = new Overlay(bridge);
    tick();
    timer = setInterval(tick, 250);
    console.log("[NekoPBZ] ready bridge=" + bridge +
        " overlay=" + !!overlay);
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
