"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(
    __dirname, "..", "game_bundle", "mod", "js",
    "pbz-neko-companion", "main.js"), "utf8");

function runMod(options = {}) {
    const writes = {};
    const UE = {
        EasyCsv: {
            SaveStringToFile(body, slot) {
                const name = path.basename(slot);
                writes[name] = String(body);
                return !(options.failState && name === "state");
            },
        },
    };
    const moduleObject = { exports: {} };
    const context = {
        require(name) {
            if (name === "ue") return UE;
            if (name === "./game_api") {
                return {
                    bridgeDir: () => "C:/NekoBridge",
                    snapshot: () => ({
                        version: 1,
                        player: { hp_percent: 91 },
                        world: { id: "XiGu" },
                    }),
                };
            }
            if (name === "./ui_bridge") {
                return {
                    Overlay: class {
                        constructor() {
                            throw new Error("overlay unavailable");
                        }
                    },
                };
            }
            return require(name);
        },
        module: moduleObject,
        exports: moduleObject.exports,
        console: { log() {}, error() {} },
        setInterval: () => 1,
        clearInterval() {},
        setTimeout: () => 1,
        Date,
        JSON,
        String,
        Number,
        Boolean,
        Array,
        Object,
        Error,
    };

    vm.runInNewContext(source, context, { filename: "main.js" });
    return writes;
}

const writes = runMod();
assert.ok(writes.state, "state.json must be written even when overlay setup fails");
assert.ok(writes.mod_status, "mod status must be reported");
assert.ok(writes.game_heartbeat, "game heartbeat must be reported");
const state = JSON.parse(writes.state);
assert.strictEqual(state.player.hp_percent, 91);
assert.strictEqual(state.game.overlay_ready, false);
assert.match(state.game.overlay_error, /overlay unavailable/);

const failedWrites = runMod({ failState: true });
const failedStatus = JSON.parse(failedWrites.mod_status);
assert.strictEqual(
    failedStatus.state_ready,
    false,
    "mod must not report ready when state.json was not written",
);
assert.match(failedStatus.error, /state\.json write failed/);
const failedHeartbeat = JSON.parse(failedWrites.game_heartbeat);
assert.strictEqual(failedHeartbeat.status, "degraded");

console.log("mod runtime behavior ok");
