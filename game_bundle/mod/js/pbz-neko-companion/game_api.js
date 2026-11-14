"use strict";
// 只读游戏状态适配层。所有会随游戏版本变化的类名/字段集中在这里。
const UE = require("ue");
const puerts = require("puerts");
// 游戏自带 helper 可用则用；缺失时退回 UWorld/UObject 原生接口。
// 运行时不依赖任何第三方 Mod。
const TsHelper = (() => {
    try { return require("Library/TsHelper").default; } catch (_) { return null; }
})();
const moduleStartedAt = Date.now();
const EQUIPMENT_SETTLE_MS = 15000;

const gi = puerts.argv.getByName("GameInstance");
const initialWorld = (() => {
    try { return gi.GetWorld(); } catch (_) { return null; }
})();
const initialContext = initialWorld || gi;

function liveWorld() {
    return safe(() => gi.GetWorld(), null) || initialWorld;
}

function liveContext() {
    return liveWorld() || gi;
}

function safe(fn, fallback = null) {
    try { const v = fn(); return v === undefined ? fallback : v; }
    catch (_) { return fallback; }
}
function text(v) {
    if (v == null) return "";
    return safe(() => String(v), "") || "";
}
function num(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}
function arr(v) {
    if (!v) return [];
    const out = [];
    const n = safe(() => v.Num(), null);
    if (typeof n === "number") {
        for (let i = 0; i < n; i++) out.push(safe(() => v.Get(i), null));
    } else if (Array.isArray(v)) {
        return v.slice();
    } else if (typeof v[Symbol.iterator] === "function") {
        for (const x of v) out.push(x);
    }
    return out.filter(x => x != null);
}
function objName(o) {
    return text(safe(() => UE.KismetSystemLibrary.GetObjectName(o), ""))
        .replace(/_C_\d+$/, "").replace(/^Default__/, "");
}
function displayName(o, names = []) {
    for (const name of names) {
        const value = safe(() => o?.[name], null);
        if (value) {
            const plain = text(value);
            if (plain) return plain;
            const converted = text(safe(
                () => UE.KismetTextLibrary.Conv_TextToString(value), ""));
            if (converted) return converted;
        }
    }
    return "";
}
function isValid(o) { return !!o && safe(() => UE.KismetSystemLibrary.IsValid(o), false); }
function inspectKeys(object, limit = 120) {
    if (!object) return [];
    const found = new Set();
    const collect = (value) => {
        if (!value || (typeof value !== "object" && typeof value !== "function")) return;
        for (const key of safe(() => Object.keys(value), []) || []) found.add(key);
        for (const key of safe(() => Object.getOwnPropertyNames(value), []) || []) {
            if (!["constructor", "prototype", "__proto__", "caller", "arguments"].includes(key)) {
                found.add(key);
            }
        }
    };
    collect(object);
    collect(safe(() => Object.getPrototypeOf(object), null));
    return [...found].slice(0, limit);
}
function constructTag(name) {
    if (TsHelper && TsHelper.constructGameplayTag) {
        const hit = safe(() => TsHelper.constructGameplayTag(name), null);
        if (hit) return hit;
    }
    return safe(() => UE.GameplayTagLibrary.RequestGameplayTag(name), null);
}
function hasTag(asc, tag) {
    if (!asc) return false;
    const built = constructTag(tag);
    return !!built && !!safe(() => asc.HasMatchingGameplayTag(built), false);
}
function getSubsystem(cls) {
    if (TsHelper && TsHelper.getWorldSubsystem) {
        const hit = safe(
            () => TsHelper.getWorldSubsystem(liveContext(), cls.StaticClass()), null);
        if (hit) return hit;
    }
    const current = liveWorld();
    return safe(() => current?.GetSubsystem?.(cls.StaticClass()), null)
        || safe(() => gi?.GetSubsystem?.(cls.StaticClass()), null);
}
function getGameInstanceSubsystem(cls) {
    if (TsHelper && TsHelper.getGameInstanceSubsystem) {
        const hit = safe(() => TsHelper.getGameInstanceSubsystem(gi, cls.StaticClass()), null);
        if (hit) return hit;
    }
    return safe(() => gi?.GetSubsystem?.(cls.StaticClass()), null);
}
function bridgeDir() {
    const raw = safe(() => UE.BlueprintPathsLibrary.ProjectSavedDir(), "");
    const base = text(raw).replace(/\\/g, "/").replace(/\/+$/, "");
    return (base || "C:/PBZ") + "/NekoBridge";
}

function getLocalCharacter() {
    const current = liveWorld();
    const controller = safe(
        () => UE.GameplayStatics.GetPlayerController(current, 0), null);
    const candidates = [controller, current, gi];
    for (const target of candidates) {
        if (!target) continue;
        const character = safe(
            () => UE.PBZBlueprintFunctionLibrary.GetPBZLocalCharacter(target), null);
        if (isValid(character)) return character;
    }
    const pawn = safe(() => controller?.GetPawn?.(), null)
        || safe(() => controller?.K2_GetPawn?.(), null)
        || safe(() => UE.GameplayStatics.GetPlayerCharacter(current, 0), null);
    return isValid(pawn) ? pawn : null;
}
function getAsc(character) {
    return safe(() => UE.AbilitySystemBlueprintLibrary.GetAbilitySystemComponent(character), null);
}

// ── 生命 / 杀气 ────────────────────────────
const HP_PROPS = ["Health", "Hp", "HP", "CurrentHealth", "CurrentHp"];
const MAX_HP_PROPS = ["Health_Max", "MaxHealth", "MaxHp", "MaximumHealth"];
const SHACHI_PROPS = ["Shachi", "ShaChi", "ShaQi", "CurrentShachi", "Anger", "Rage"];
const MAX_SHACHI_PROPS = ["Shachi_Max", "ShaChi_Max", "ShaQi_Max",
    "MaxShachi", "Anger_Max", "Rage_Max"];

function directProp(obj, names) {
    for (const name of names) {
        const v = safe(() => obj[name], null);
        if (typeof v === "number") return v;
        if (v && typeof v === "object") {
            const cv = safe(() => v.CurrentValue, null);
            if (typeof cv === "number") return cv;
            const vv = safe(() => v.Value, null);
            if (typeof vv === "number") return vv;
        }
    }
    return null;
}
function readVitals(character, asc) {
    const attributeSet = safe(() => character.AttributeSetBase, null);
    const hp = directProp(attributeSet, HP_PROPS)
        ?? directProp(character, HP_PROPS)
        ?? safe(() => directProp(character.HealthComponent, HP_PROPS), null);
    const maxHp = directProp(attributeSet, MAX_HP_PROPS)
        ?? directProp(character, MAX_HP_PROPS)
        ?? safe(() => directProp(character.HealthComponent, MAX_HP_PROPS), null);
    let shachi = directProp(attributeSet, SHACHI_PROPS)
        ?? directProp(character, SHACHI_PROPS);
    let shachiMax = directProp(attributeSet, MAX_SHACHI_PROPS)
        ?? directProp(character, MAX_SHACHI_PROPS);
    if (shachi == null && asc) {
        // 部分版本把资源暴露在 ASC 上；只读常见字段，不做内存猜测。
        shachi = safe(() => directProp(asc, SHACHI_PROPS), null);
    }
    const percent = (hp != null && maxHp && maxHp > 0) ? hp / maxHp * 100 : null;
    return {
        hp, max_hp: maxHp, hp_percent: percent,
        shachi: { current: shachi, max: shachiMax,
                  percent: (shachi != null && shachiMax) ? shachi / shachiMax * 100 : null },
        probes: {
            hp: hp != null, max_hp: maxHp != null, shachi: shachi != null,
            asc: asc ? objName(asc.GetClass ? asc.GetClass() : asc) : "",
            attribute_set: attributeSet ? objName(attributeSet.GetClass()) : "",
        },
    };
}

// ── 当前装备（只读装备槽，不碰背包持有量）────────
// 反射链已由运行中的 PBZBackPackSubsystem 确认：
// MainWeapons / CurrentMainWeaponID / ShaqiWeapons / CurrentShaqiWeaponIndex
// Accessories / TopMedicineID / BottomMedicineID。
function scalarText(v) {
    if (v == null) return "";
    if (typeof v === "string") return v.trim();
    if (typeof v === "number") return String(v);
    if (typeof v === "boolean") return "";
    const direct = text(v);
    if (direct && !/^\[object\s/i.test(direct) && direct !== "None") return direct.trim();
    return "";
}
function idText(v) {
    if (v == null) return "";
    if (Array.isArray(v) || safe(() => v.Num?.(), null) != null) {
        const list = arr(v);
        if (list.length) return idText(list[0]);
    }
    const direct = scalarText(v);
    if (direct) return direct;
    for (const name of [
        "ID", "Id", "ItemID", "WeaponID", "ShaChiWeaponID", "ShaqiWeaponID",
        "AccessoryID", "MedicineID", "Key", "Value",
    ]) {
        const found = scalarText(safe(() => v?.[name], null));
        if (found) return found;
    }
    return "";
}
function idsFrom(v) {
    if (v == null) return [];
    const out = [];
    if (typeof v === "string" || typeof v === "number") {
        const id = idText(v);
        return id ? [id] : [];
    }
    const list = arr(v);
    if (list.length) {
        for (const entry of list) {
            const id = idText(entry);
            if (id) out.push(id);
        }
    } else if (sequenceValues(v).length) {
        for (const entry of sequenceValues(v)) {
            const id = idText(entry);
            if (id) out.push(id);
        }
    } else {
        const id = idText(v);
        if (id) out.push(id);
    }
    return [...new Set(out)].filter(id => id !== "None");
}
function localizeKey(key) {
    const raw = scalarText(key);
    if (!raw) return "";
    const built = safe(
        () => UE.PBZBlueprintFunctionLibrary.MakeTextByKey(raw), null);
    return text(safe(() => UE.KismetTextLibrary.Conv_TextToString(built), "")) || raw;
}
function localizedValue(v) {
    if (v == null) return "";
    const key = scalarText(safe(() => v?.Key, null));
    if (key) return localizeKey(key);
    const textValue = text(
        safe(() => UE.KismetTextLibrary.Conv_TextToString(v), ""));
    if (textValue) return textValue;
    return scalarText(v);
}
function rowName(row, names) {
    for (const name of names) {
        const value = localizedValue(safe(() => row?.[name], null));
        if (value) return value;
    }
    return "";
}
function rowLevel(row) {
    return num(safe(() => row?.Level, null)
        ?? safe(() => row?.CurrentLevel, null)
        ?? safe(() => row?.UpgradeLevel, null)
        ?? safe(() => row?.Tier, null));
}
function equipmentLevel(backpack, category, id, row) {
    const mapName = {
        main_weapon: "MainWeaponInfos",
        phantom_edge: "ShaqiWeaponInfos",
        accessory: "Accessories",
        medicine: "MedicineInfos",
    }[category];
    const instance = mapName
        ? safe(() => backpack?.[mapName]?.Get(id), null)
        : null;
    const current = num(safe(() => instance?.WeaponLevel, null)
        ?? safe(() => instance?.ShaChiWeaponLevel, null)
        ?? safe(() => instance?.CurrentLevel, null)
        ?? safe(() => instance?.Level, null)
        ?? safe(() => instance?.UpgradeLevel, null)
        ?? safe(() => instance?.Tier, null));
    return current != null ? current : rowLevel(row);
}
function rowFor(backpack, category, id) {
    if (!backpack || !id) return null;
    if (category === "main_weapon") {
        return safe(() => backpack.GetMainWeaponTableData(id), null);
    }
    if (category === "phantom_edge") {
        return safe(() => backpack.GetShaqiWeaponTableData(id), null);
    }
    if (category === "accessory") {
        return safe(() => backpack.GetAccessoryData(id), null)
            || safe(() => UE.PBZBackPackSubsystem.GetAccessoryData(id), null);
    }
    if (category === "medicine") {
        return safe(() => backpack.GetMedicineData(id), null)
            || safe(() => UE.PBZBackPackSubsystem.GetMedicineData(id), null);
    }
    return null;
}
function equipmentItem(backpack, category, id, slot, slotIndex, active) {
    const key = idText(id);
    if (!key) return null;
    const row = rowFor(backpack, category, key);
    const names = category === "accessory" ? ["AccessoryName", "Name", "DisplayName"]
        : ["WeaponName", "MedicineName", "Name", "DisplayName"];
    const type = text(safe(() => row?.WeaponType, "")
        || safe(() => row?.AccessoryType, "")
        || safe(() => row?.MedicineType, "")
        || safe(() => row?.Type, ""));
    return {
        id: key,
        name: rowName(row, names) || key,
        category,
        type,
        tier: equipmentLevel(backpack, category, key, row),
        slot,
        slot_index: slotIndex,
        active: active === true,
        resolved: !!row,
    };
}
function equippedIds(backpack, propertyName) {
    return idsFrom(safe(() => backpack?.[propertyName], null));
}
function readEquipment(backpack) {
    const mainIds = equippedIds(backpack, "MainWeapons");
    const currentMainId = scalarText(
        safe(() => backpack?.CurrentMainWeaponID, null));
    if (currentMainId && !mainIds.includes(currentMainId)) mainIds.unshift(currentMainId);
    const currentWeaponIndex = num(safe(() => backpack?.CurrentWeaponIndex, null));
    const mainWeapons = mainIds.map((id, index) => equipmentItem(
        backpack, "main_weapon", id,
        index === 0 ? "primary" : "secondary",
        index,
        id === currentMainId
            || (!currentMainId && currentWeaponIndex === index),
    )).filter(Boolean);

    const edgeIds = equippedIds(backpack, "ShaqiWeapons");
    const currentEdgeIndex = num(
        safe(() => backpack?.CurrentShaqiWeaponIndex, null));
    const edges = edgeIds.map((id, index) => equipmentItem(
        backpack, "phantom_edge", id, "edge", index,
        currentEdgeIndex === index,
    )).filter(Boolean);

    // Accessories 是 39 件已获得饰品的 TMap；AssemblyAccessory 才是当前
    // 6 个饰品装配槽（未装配槽为 "None"）。绝不能把前者当已装备列表。
    const accessories = equippedIds(backpack, "AssemblyAccessory").map((id, index) =>
        equipmentItem(backpack, "accessory", id, "accessory", index, true)
    ).filter(Boolean);

    const medicines = [];
    for (const [slot, field] of [
        ["top", "TopMedicineID"],
        ["bottom", "BottomMedicineID"],
    ]) {
        const raw = safe(() => backpack?.[field], null);
        for (const id of idsFrom(raw)) {
            const item = equipmentItem(
                backpack, "medicine", id, slot, medicines.length, true);
            if (item && !medicines.some(existing => existing.id === item.id
                && existing.slot === item.slot)) {
                medicines.push(item);
            }
        }
    }

    return {
        main_weapon: mainWeapons.find(item => item.active) || mainWeapons[0] || null,
        main_weapons: mainWeapons,
        secondary_weapon: mainWeapons[1] || null,
        phantom_edges: edges,
        accessories,
        medicines,
    };
}
function emptyEquipment() {
    return {
        main_weapon: null,
        main_weapons: [],
        secondary_weapon: null,
        phantom_edges: [],
        accessories: [],
        medicines: [],
    };
}
function probeEquipmentValue(v) {
    if (v == null) return null;
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
        return v;
    }
    const ids = idsFrom(v);
    if (ids.length) return ids;
    const direct = scalarText(v);
    return direct || `[${typeof v}]`;
}
function inspectContainer(v, limit = 80) {
    if (v == null) return null;
    return {
        type: typeof v,
        num: safe(() => v.Num?.(), null),
        length: safe(() => v.length, null),
        iterable: safe(() => typeof v[Symbol.iterator] === "function", false),
        keys: inspectKeys(v, limit),
    };
}
function sequenceValues(v, limit = 64) {
    if (v == null) return [];
    if (Array.isArray(v)) return v.slice(0, limit);
    const out = [];
    if (safe(() => typeof v[Symbol.iterator] === "function", false)) {
        safe(() => {
            for (const value of v) {
                out.push(value);
                if (out.length >= limit) break;
            }
        }, null);
    }
    if (out.length) return out;
    const count = num(safe(() => v.Num?.(), null));
    if (count != null) {
        for (let index = 0; index < Math.min(count, limit); index++) {
            const value = safe(() => v.Get(index), null);
            if (value != null) out.push(value);
        }
    }
    return out;
}
function probeSequence(v, limit = 64) {
    return sequenceValues(v, limit).map(value => {
        if (typeof value === "string" || typeof value === "number"
            || typeof value === "boolean") return value;
        if (Array.isArray(value)) {
            return {
                value: scalarText(value[0]),
                pair_value_shape: inspectContainer(value[1], 80),
            };
        }
        const tag = scalarText(safe(() => value?.TagName, null));
        const key = scalarText(safe(() => value?.Key, null));
        const direct = scalarText(value);
        return {
            value: tag || key || direct || null,
            keys: inspectKeys(value, 16),
        };
    });
}

// ── 敌人扫描 ──────────────────────────────
let classCache = { ts: 0, classes: [] };
let bellCache = { ts: 0, classes: [] };
let networkClassCache = null;
const CLASS_SKIP = /(Widget|Button|Component|Subsystem|Manager|FunctionLibrary|DataAsset|Anim|Camera|PlayerController|HUD|UI|Text|Image|Sound|Niagara|LevelSequence)/i;
const CLASS_HINT = /(Monster|Enemy|Boss|Mob|AICharacter|NPC)/i;
const EXPLICIT_ENEMY = ["PBZAICharacter", "PBZMonsterCharacter", "PBZEnemyCharacter"];
const EXPLICIT_BELL = ["PBZBellActor", "BellActor", "BP_Bell_C", "BP_BellBase_C"];

function discoverNetworkClasses() {
    if (networkClassCache) return networkClassCache;
    const keys = safe(() => Object.keys(UE), []) || [];
    networkClassCache = keys.filter(name => /(Http|WebSocket|Websocket|Socket|Tcp)/i.test(name))
        .filter(name => !CLASS_SKIP.test(name))
        .slice(0, 40);
    return networkClassCache;
}

function discoverClasses() {
    if (Date.now() - classCache.ts < 30000 && classCache.classes.length) return classCache.classes;
    const found = [];
    const keys = safe(() => Object.keys(UE), []) || [];
    const names = [...EXPLICIT_ENEMY, ...keys.filter(n => CLASS_HINT.test(n))];
    for (const name of [...new Set(names)]) {
        if (!CLASS_HINT.test(name) || CLASS_SKIP.test(name)) continue;
        const T = safe(() => UE[name], null);
        if (!T || !T.StaticClass) continue;
        const out = puerts.$ref(UE.NewArray(UE.Actor));
        const ok = safe(() => UE.GameplayStatics.GetAllActorsOfClass(
            liveContext(), T.StaticClass(), out), false);
        if (!ok) continue;
        const list = arr(safe(() => puerts.$unref(out), null));
        if (list.length) found.push({ name, cls: T, count: list.length });
        if (found.length >= 12) break;
    }
    classCache = { ts: Date.now(), classes: found };
    return found;
}
function discoverBellClasses() {
    if (Date.now() - bellCache.ts < 30000 && bellCache.classes.length) return bellCache.classes;
    const found = [];
    const keys = safe(() => Object.keys(UE), []) || [];
    const names = [...EXPLICIT_BELL, ...keys.filter(n => /(Bell|Checkpoint|SavePoint)/i.test(n))];
    for (const name of [...new Set(names)]) {
        if (CLASS_SKIP.test(name)) continue;
        const T = safe(() => UE[name], null);
        if (!T || !T.StaticClass) continue;
        const out = puerts.$ref(UE.NewArray(UE.Actor));
        if (!safe(() => UE.GameplayStatics.GetAllActorsOfClass(
            liveContext(), T.StaticClass(), out), false)) continue;
        const list = arr(safe(() => puerts.$unref(out), null));
        if (list.length) found.push({ name, cls: T, count: list.length });
        if (found.length >= 8) break;
    }
    bellCache = { ts: Date.now(), classes: found };
    return found;
}
function directionOf(player, pawn, target) {
    const f = safe(() => pawn.GetActorForwardVector(), null);
    if (!f) return "";
    const dx = target.X - player.X, dy = target.Y - player.Y;
    const len = Math.hypot(dx, dy) || 1;
    const dot = (dx / len) * f.X + (dy / len) * f.Y;
    const cross = f.X * (dy / len) - f.Y * (dx / len);
    if (Math.abs(dot) < 0.38) return cross > 0 ? "right" : "left";
    return dot > 0 ? (cross > 0.28 ? "front_right" : cross < -0.28 ? "front_left" : "front")
        : (cross > 0.28 ? "right" : cross < -0.28 ? "left" : "behind");
}
function scanEnemies(character) {
    if (!character) return { enemies: [], boss: null, diagnostics: [] };
    const player = safe(() => character.K2_GetActorLocation(), null);
    if (!player) return { enemies: [], boss: null, diagnostics: [] };
    const out = [];
    const diagnostics = [];
    for (const entry of discoverClasses()) {
        diagnostics.push({ name: entry.name, count: entry.count });
        const actors = puerts.$ref(UE.NewArray(UE.Actor));
        safe(() => UE.GameplayStatics.GetAllActorsOfClass(
            liveContext(), entry.cls.StaticClass(), actors), null);
        for (const actor of arr(safe(() => puerts.$unref(actors), null))) {
            if (!isValid(actor)) continue;
            const loc = safe(() => actor.K2_GetActorLocation(), null);
            if (!loc) continue;
            const dist = Math.hypot(loc.X - player.X, loc.Y - player.Y, loc.Z - player.Z) / 100;
            if (dist > 45) continue;
            const name = displayName(actor, [
                "MonsterName", "EnemyName", "DisplayName", "CharacterName",
                "BossName", "Name",
            ]) || objName(actor);
            const vitals = readVitals(actor, getAsc(actor));
            out.push({
                id: name, name, archetype: "",
                distance: Math.round(dist * 10) / 10,
                direction: directionOf(player, character, loc),
                hp_percent: vitals.hp_percent,
                is_elite: /Elite|精英/i.test(name),
                is_boss: /Boss|BossName/i.test(name) || /Boss/i.test(entry.name),
                phase: num(safe(() => actor.BossPhase, null)
                    ?? safe(() => actor.CurrentPhase, null)
                    ?? safe(() => actor.Phase, null)
                    ?? safe(() => actor.PhaseIndex, null)),
                aggro: true, line_of_sight: true,
            });
            if (out.length >= 12) break;
        }
        if (out.length >= 12) break;
    }
    out.sort((a, b) => a.distance - b.distance);
    const boss = out.find(e => e.is_boss) || null;
    return { enemies: out, boss, diagnostics };
}

// ── 铃铛 / 任务 / 世界 ────────────────────
function readBell(character, safeMode = false) {
    const manager = getSubsystem(UE.BellManager);
    if (!manager) return { near: false, activated: false, id: "", name: "", distance: null };
    const activated = arr(safe(() => manager.ActivateBellIDs, null)).map(text);
    let nearby = null;
    if (character && !safeMode) {
        const player = safe(() => character.K2_GetActorLocation(), null);
        if (player) {
            for (const entry of discoverBellClasses()) {
                const actors = puerts.$ref(UE.NewArray(UE.Actor));
                safe(() => UE.GameplayStatics.GetAllActorsOfClass(
                    liveContext(), entry.cls.StaticClass(), actors), null);
                for (const a of arr(safe(() => puerts.$unref(actors), null))) {
                    const loc = safe(() => a.K2_GetActorLocation(), null);
                    if (!loc) continue;
                    const d = Math.hypot(loc.X - player.X, loc.Y - player.Y, loc.Z - player.Z) / 100;
                    if (!nearby || d < nearby.distance) nearby = { id: objName(a), distance: d };
                }
            }
        }
    }
    const id = nearby ? nearby.id : "";
    let name = id;
    if (id) {
        const data = safe(() => UE.BellManager.GetBellData(id), null);
        name = displayName(data, [
            "BellName", "DisplayName", "Name", "BellTitle",
        ]) || name;
    }
    return {
        near: !!nearby && nearby.distance <= 8,
        activated: id ? activated.includes(id) : false,
        id, name,
        distance: nearby ? Math.round(nearby.distance * 10) / 10 : null,
        activated_ids: activated.slice(0, 32),
    };
}
function readWorld() {
    const map = getSubsystem(UE.MapSubsystem);
    return {
        id: text(safe(() => map?.GetCurrentMapID?.(), "")),
        name: text(safe(() => map?.GetCurrentMapName?.(), "")
            || safe(() => UE.GameplayStatics.GetCurrentLevelName(liveContext()), "")),
        layer: null,
    };
}
function readQuests() {
    const narrative = safe(
        () => UE.PBZBlueprintFunctionLibrary.GetPBZNarrativeComp(liveContext()), null);
    if (!narrative) return [];
    const out = [];
    for (const quest of arr(safe(() => narrative.QuestList, null))) {
        if (!quest || safe(() => quest.bIsTutorial, false)) continue;
        const tasks = [];
        for (const branch of arr(safe(() => quest.Branches, null))) {
            for (const task of arr(safe(() => branch.QuestTasks, null))) {
                tasks.push({
                    current: num(safe(() => task.CurrentProgress, null)),
                    required: num(safe(() => task.RequiredQuantity, null)),
                    complete: safe(() => task.IsComplete?.(), null),
                    name: displayName(task, [
                        "TaskName", "DisplayName", "Name", "Description",
                        "TaskDescription", "TaskDesc",
                    ]),
                });
            }
        }
        out.push({
            id: objName(quest),
            name: text(safe(() => UE.KismetTextLibrary.Conv_TextToString(quest.GetQuestName()), "")),
            description: displayName(quest, [
                "QuestDescription", "Description", "QuestDesc",
            ]),
            state: safe(() => quest.IsQuestComplete?.(), false) ? "completed" : "active",
            tasks,
        });
        if (out.length >= 6) break;
    }
    return out;
}
function readSave() {
    const save = getGameInstanceSubsystem(UE.PBZSaveLoadSubsystem);
    return {
        slot: text(safe(() => save?.CurrentSlotName, "") || safe(() => save?.CurrentSaveName, "")
            || safe(() => save?.CurrentSlotIndex, "")),
    };
}

function snapshot(options = {}) {
    const safeMode = options.safeMode === true;
    const includeRuntimeProbe = safeMode && options.includeRuntimeProbe === true;
    const character = getLocalCharacter();
    const asc = getAsc(character);
    const vitals = readVitals(character, asc);
    const deadTag = hasTag(asc, "CharacterState.Death")
        || hasTag(asc, "CharacterState.Dead") || hasTag(asc, "State.Dead");
    const world = readWorld(character);
    const attributeSet = safe(() => character?.AttributeSetBase, null);
    const backpack = safe(
        () => UE.PBZBackPackSubsystem.GetBackPackSubsytemByContextObject(liveContext()), null);
    // PBZMainStart 早于武器 DataAsset 缓存完成。过早读取 TArray/TMap 槽位或
    // 调用表数据接口会让 PuerTS 把未就绪对象传给原生代码，导致进程级崩溃。
    const equipmentReady = !!character
        && Date.now() - moduleStartedAt >= EQUIPMENT_SETTLE_MS
        && !!(world.name || world.id);
    const equipment = equipmentReady ? readEquipment(backpack) : emptyEquipment();
    const scanned = safeMode
        ? { enemies: [], boss: null, diagnostics: [] }
        : scanEnemies(character);
    const camera = safe(
        () => UE.GameplayStatics.GetPlayerCameraManager(liveContext(), 0), null);
    const rot = safe(() => camera.GetCameraRotation(), null);
    const pos = safe(() => character?.K2_GetActorLocation(), null);
    return {
        version: 1,
        seq: 0,
        ts: Date.now() / 1000,
        game_version: "CL-302256",
        game: {
            running: true,
            paused: safe(() => UE.GameplayStatics.IsGamePaused(liveContext()), false),
            cutscene: false,
            menu_open: false,
        },
        world,
        save: readSave(),
        player: {
            name: objName(character),
            hp: vitals.hp, max_hp: vitals.max_hp, hp_percent: vitals.hp_percent,
            pos: pos ? [pos.X, pos.Y, pos.Z] : null,
            yaw: rot ? rot.Yaw : null,
            in_combat: hasTag(asc, "CharacterState.InCombat"),
            movement: text(safe(() => character?.CharacterMovement?.MovementMode, "")),
            interacting: "",
            dead: deadTag || (vitals.hp_percent != null && vitals.hp_percent <= 0),
            status_effects: [
                hasTag(asc, "CharacterState.StatusInfliction") ? "status" : null,
            ].filter(Boolean),
            shachi: vitals.shachi,
            equipment,
        },
        enemies: scanned.enemies,
        boss: scanned.boss,
        quests: readQuests(),
        bell: readBell(character, safeMode),
        capabilities: {
            safe_mode: safeMode,
            network_classes: discoverNetworkClasses(),
            character: !!character,
            asc: !!asc,
            vitals: vitals.probes,
            enemy_classes: scanned.diagnostics,
            equipment: {
                main_weapon: !!equipment.main_weapon,
                main_weapons: equipment.main_weapons.length,
                secondary_weapon: !!equipment.secondary_weapon,
                phantom_edges: equipment.phantom_edges.length,
                accessories: equipment.accessories.length,
                medicines: equipment.medicines.length,
            },
            runtime_probe: includeRuntimeProbe ? {
                character_class: character ? objName(character.GetClass()) : "",
                character_keys: inspectKeys(character),
                attribute_set_class: attributeSet ? objName(attributeSet.GetClass()) : "",
                attribute_set_keys: inspectKeys(attributeSet),
                backpack_class: backpack ? objName(backpack.GetClass()) : "",
                backpack_keys: inspectKeys(backpack),
                backpack_values: backpack && equipmentReady ? {
                    current_weapon_index: probeEquipmentValue(
                        safe(() => backpack.CurrentWeaponIndex, null)),
                    current_main_weapon_id: probeEquipmentValue(
                        safe(() => backpack.CurrentMainWeaponID, null)),
                    main_weapons: probeEquipmentValue(
                        safe(() => backpack.MainWeapons, null)),
                    current_shaqi_weapon_index: probeEquipmentValue(
                        safe(() => backpack.CurrentShaqiWeaponIndex, null)),
                    shaqi_weapons: probeEquipmentValue(
                        safe(() => backpack.ShaqiWeapons, null)),
                    accessories: probeEquipmentValue(
                        safe(() => backpack.Accessories, null)),
                    top_medicine_id: probeEquipmentValue(
                        safe(() => backpack.TopMedicineID, null)),
                    bottom_medicine_id: probeEquipmentValue(
                        safe(() => backpack.BottomMedicineID, null)),
                    accessories_shape: inspectContainer(
                        safe(() => backpack.Accessories, null)),
                    accessories_sample: probeSequence(
                        safe(() => backpack.Accessories, null), 12),
                    assembly_accessory: probeEquipmentValue(
                        safe(() => backpack.AssemblyAccessory, null)),
                    assembly_accessory_shape: inspectContainer(
                        safe(() => backpack.AssemblyAccessory, null)),
                    assembly_accessory_sample: probeSequence(
                        safe(() => backpack.AssemblyAccessory, null), 12),
                    current_main_info_shape: inspectContainer(safe(
                        () => backpack.MainWeaponInfos.Get(scalarText(
                            safe(() => backpack.CurrentMainWeaponID, null))),
                        null)),
                    current_main_table_shape: inspectContainer(
                        rowFor(backpack, "main_weapon", scalarText(
                            safe(() => backpack.CurrentMainWeaponID, null)))),
                    current_main_level_data_shape: inspectContainer(safe(
                        () => backpack.GetMainWeaponLevelData(scalarText(
                            safe(() => backpack.CurrentMainWeaponID, null))),
                        null)),
                    current_edge_info_shape: inspectContainer(safe(() => {
                        const ids = equippedIds(backpack, "ShaqiWeapons");
                        const index = num(safe(
                            () => backpack.CurrentShaqiWeaponIndex, null));
                        return ids[index || 0]
                            ? backpack.ShaqiWeaponInfos.Get(ids[index || 0])
                            : null;
                    }, null)),
                    medicine_infos_shape: inspectContainer(
                        safe(() => backpack.MedicineInfos, null)),
                    accessory_slot_tags: probeEquipmentValue(
                        safe(() => backpack.AccessorySlotTags, null)),
                    accessory_slot_tags_shape: inspectContainer(
                        safe(() => backpack.AccessorySlotTags, null)),
                    accessory_slot_tag_values: probeSequence(
                        safe(() => backpack.AccessorySlotTags, null), 12),
                    accessory_infos_result_shape: inspectContainer(
                        safe(() => backpack.GetAccessoryInfos(), null)),
                    accessory_infos_result_sample: probeSequence(
                        safe(() => backpack.GetAccessoryInfos(), null), 12),
                    accessory_equipped_snapshot: probeEquipmentValue(
                        safe(() => backpack.EquippedSnapshot, null)),
                    accessory_equipped_snapshot_shape: inspectContainer(
                        safe(() => backpack.EquippedSnapshot, null)),
                    has_equipped_snapshot: safe(
                        () => backpack.bHasEquippedSnapshot, null),
                    top_medicine_row_shape: inspectContainer(
                        rowFor(backpack, "medicine", scalarText(
                            safe(() => backpack.TopMedicineID, null)))),
                    top_medicine_map_row_shape: inspectContainer(safe(
                        () => backpack.MedicineInfos.Get(scalarText(
                            safe(() => backpack.TopMedicineID, null))), null)),
                    top_medicine_static_row_shape: inspectContainer(safe(
                        () => UE.PBZBackPackSubsystem.GetMedicineData(
                            scalarText(safe(() => backpack.TopMedicineID, null))),
                        null)),
                } : { deferred: !equipmentReady },
            } : null,
        },
    };
}

module.exports = {
    snapshot, bridgeDir, getLocalCharacter, liveWorld, liveContext,
    context: initialContext, gi,
};
