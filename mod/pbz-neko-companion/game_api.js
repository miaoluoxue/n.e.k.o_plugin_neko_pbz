"use strict";
// 只读游戏状态适配层。所有会随游戏版本变化的类名/字段集中在这里。
const UE = require("ue");
const puerts = require("puerts");
// 游戏自带 helper 可用则用；缺失时退回 UWorld/UObject 原生接口。
// 运行时不依赖任何第三方 Mod。
const TsHelper = (() => {
    try { return require("Library/TsHelper").default; } catch (_) { return null; }
})();

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

// ── 当前装备（只读装备槽，不碰背包）────────
function itemRef(v) {
    if (v == null) return null;
    if (typeof v === "string") return { id: v, name: v };
    const id = text(safe(() => v.ItemID, "") || safe(() => v.ID, "")
        || safe(() => v.WeaponID, "") || safe(() => v.RowName, ""));
    const name = text(safe(() => v.Name, "") || safe(() => v.DisplayName, "")
        || safe(() => v.WeaponName, "") || safe(() => v.ItemName, ""));
    if (!id && !name) return null;
    return {
        id: id || name, name: name || id,
        type: text(safe(() => v.WeaponType, "") || safe(() => v.Type, "")),
        category: text(safe(() => v.Category, "") || safe(() => v.ItemType, "")),
        tier: num(safe(() => v.Tier, null) ?? safe(() => v.UpgradeLevel, null)),
        soulcast_form: text(safe(() => v.SnapSoulName, "") || safe(() => v.SoulName, "")),
        charges: num(safe(() => v.Charge, null) ?? safe(() => v.Charges, null)),
        cooldown: num(safe(() => v.Cooldown, null)),
        count: num(safe(() => v.Count, null) ?? safe(() => v.CurrentAmount, null)
            ?? safe(() => v.Quantity, null) ?? safe(() => v.Num, null)),
        uses: num(safe(() => v.Uses, null) ?? safe(() => v.RemainingUses, null)
            ?? safe(() => v.CurrentUseCount, null)),
        max_uses: num(safe(() => v.MaxUses, null) ?? safe(() => v.MaxUseCount, null)),
        ready: safe(() => v.bReady, null),
        tags: text(safe(() => v.Tags, "")),
    };
}
function toList(v) {
    if (v == null) return [];
    if (typeof v === "string" || typeof v === "number") return [v];
    const list = arr(v);
    return list.length ? list : [v];
}
function refsFrom(sources, names, slotName) {
    for (const src of sources) {
        for (const name of names) {
            const list = toList(safe(() => src[name], null)).map(itemRef).filter(Boolean);
            if (list.length) {
                const seen = new Set();
                return list.filter(item => {
                    const key = item.id || item.name;
                    if (seen.has(key)) return false;
                    seen.add(key);
                    item.slot = slotName;
                    return true;
                });
            }
        }
    }
    return [];
}
function firstRef(objs) {
    const list = arr(objs).map(itemRef).filter(Boolean);
    return list.length ? list[0] : null;
}
function readEquipment(character) {
    const comps = [
        safe(() => character.EquipmentComponent, null),
        safe(() => character.EquipComponent, null),
        safe(() => character.PBZEquipmentComponent, null),
    ].filter(Boolean);
    const sources = [character, ...comps];
    let mainWeapons = refsFrom(sources, [
        "MainWeapons", "EquippedWeapons", "WeaponList", "Weapons",
        "MainWeaponSlots", "WeaponSlots",
    ], "main");
    let main = mainWeapons[0] || null;
    if (!main) {
        for (const src of sources) {
            main = firstRef([
                safe(() => src.MainWeapon, null),
                safe(() => src.CurrentWeapon, null),
                safe(() => src.Weapon, null),
            ]);
            if (!main) main = itemRef(safe(() => src.GetCurrentWeapon?.(), null));
            if (main) break;
        }
        if (main) mainWeapons = [main];
    }
    let secondary = firstRef([
        ...sources.map(src => safe(() => src.SecondaryWeapon, null)),
        ...sources.map(src => safe(() => src.SubWeapon, null)),
        ...sources.map(src => safe(() => src.OffhandWeapon, null)),
    ]);
    const edges = refsFrom(sources, [
        "PhantomEdges", "ShaChiWeapons", "ShaqiWeapons",
        "ShadowWeapons", "Armaments", "ShaqiWeaponSlots", "PhantomEdgeSlots",
    ], "edge");
    const accessories = refsFrom(sources, [
        "Accessories", "AccessorySlots", "EquippedAccessories",
    ], "accessory");
    const medicines = refsFrom(sources, [
        "Medicines", "MedicineSlots", "QuickItems", "QuickItemSlots",
        "ConsumableSlots", "QuickUseItems", "Potions", "BottleSlots",
    ], "medicine");
    return {
        main_weapon: main,
        main_weapons: mainWeapons,
        secondary_weapon: secondary,
        phantom_edges: edges,
        accessories,
        medicines,
    };
}

// ── 敌人扫描 ──────────────────────────────
let classCache = { ts: 0, classes: [] };
let bellCache = { ts: 0, classes: [] };
const CLASS_SKIP = /(Widget|Button|Component|Subsystem|Manager|FunctionLibrary|DataAsset|Anim|Camera|PlayerController|HUD|UI|Text|Image|Sound|Niagara|LevelSequence)/i;
const CLASS_HINT = /(Monster|Enemy|Boss|Mob|AICharacter|NPC)/i;
const EXPLICIT_ENEMY = ["PBZAICharacter", "PBZMonsterCharacter", "PBZEnemyCharacter"];
const EXPLICIT_BELL = ["PBZBellActor", "BellActor", "BP_Bell_C", "BP_BellBase_C"];

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
    const character = getLocalCharacter();
    const asc = getAsc(character);
    const vitals = readVitals(character, asc);
    const deadTag = hasTag(asc, "CharacterState.Death")
        || hasTag(asc, "CharacterState.Dead") || hasTag(asc, "State.Dead");
    const equipment = readEquipment(character);
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
        world: readWorld(character),
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
        },
    };
}

module.exports = {
    snapshot, bridgeDir, getLocalCharacter, liveWorld, liveContext,
    context: initialContext, gi,
};
