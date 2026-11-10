"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const path = require("node:path");

class ArrayLike {
    constructor(values) {
        this.values = values;
    }

    Num() {
        return this.values.length;
    }

    Get(index) {
        return this.values[index];
    }
}
class MapLike {
    constructor(entries) {
        this.entries = entries;
    }

    Get(key) {
        return this.entries[key] || null;
    }
}

const localized = {
    Weapon_001: "黑伤",
    Weapon_017: "红妆鬼斩",
    PhantomEdges_014: "追命锁镰",
    PhantomEdges_001: "巨凶斧",
    Item_Accessory_019: "珍玩妖织",
    Item_Medicine_001: "药葫芦",
    Item_Medicine_005: "慈花甘露",
};

const mainRows = {
    Weapon_001: { WeaponName: { Key: "Weapon_001" }, Level: 3 },
    Weapon_017: { WeaponName: { Key: "Weapon_017" }, Level: 5 },
};
const edgeRows = {
    PhantomEdges_014: { WeaponName: { Key: "PhantomEdges_014" }, Level: 2 },
    PhantomEdges_001: { WeaponName: { Key: "PhantomEdges_001" }, Level: 1 },
};
const accessoryRows = {
    Item_Accessory_019: { AccessoryName: { Key: "Item_Accessory_019" } },
};
const medicineRows = {
    Item_Medicine_001: { Name: { Key: "Item_Medicine_001" } },
    Item_Medicine_005: { Name: { Key: "Item_Medicine_005" } },
};

const world = {
    GetSubsystem() {
        return null;
    },
};
const character = {
    AttributeSetBase: {
        Health: 800,
        Health_Max: 1000,
        Shachi: 300,
        Shachi_Max: 600,
        GetClass() {
            return { ClassName: "BasicAttributeSet" };
        },
    },
    K2_GetActorLocation() {
        return { X: 0, Y: 0, Z: 0 };
    },
    CharacterMovement: { MovementMode: 1 },
    GetClass() {
        return { ClassName: "BP_Renewal_Hun_C" };
    },
};
const backpack = {
    CurrentWeaponIndex: 0,
    CurrentMainWeaponID: "Weapon_017",
    MainWeapons: new ArrayLike(["Weapon_001", "Weapon_017"]),
    CurrentShaqiWeaponIndex: 1,
    ShaqiWeapons: new ArrayLike(["PhantomEdges_014", "PhantomEdges_001"]),
    MainWeaponInfos: new MapLike({
        Weapon_001: { WeaponLevel: 3 },
        Weapon_017: { WeaponLevel: 7 },
    }),
    ShaqiWeaponInfos: new MapLike({
        PhantomEdges_014: { ShaChiWeaponLevel: 2 },
        PhantomEdges_001: { ShaChiWeaponLevel: 4 },
    }),
    Accessories: new MapLike({
        AC_Attack: { CurrentLevel: 0 },
        Item_Accessory_019: { CurrentLevel: 1 },
    }),
    AssemblyAccessory: new ArrayLike(["Item_Accessory_019", "None"]),
    MedicineInfos: new MapLike({
        Item_Medicine_001: { CurrentLevel: 5 },
        Item_Medicine_005: { CurrentLevel: 2 },
    }),
    TopMedicineID: "Item_Medicine_001",
    BottomMedicineID: "Item_Medicine_005",
    GetMainWeaponTableData(id) {
        return mainRows[id] || null;
    },
    GetShaqiWeaponTableData(id) {
        return edgeRows[id] || null;
    },
    GetAccessoryData(id) {
        return accessoryRows[id] || null;
    },
    GetMedicineData(id) {
        return medicineRows[id] || null;
    },
    GetClass() {
        return { ClassName: "PBZBackPackSubsystem" };
    },
};
const gameInstance = {
    GetWorld() {
        return world;
    },
    GetSubsystem() {
        return null;
    },
};

const UE = {
    KismetSystemLibrary: {
        IsValid(value) {
            return !!value;
        },
        GetObjectName(value) {
            return value?.ClassName || "";
        },
    },
    KismetTextLibrary: {
        Conv_TextToString(value) {
            return value?.Value || "";
        },
    },
    PBZBlueprintFunctionLibrary: {
        GetPBZLocalCharacter() {
            return character;
        },
        MakeTextByKey(key) {
            return { Value: localized[key] || key };
        },
        GetPBZNarrativeComp() {
            return null;
        },
    },
    PBZBackPackSubsystem: {
        GetBackPackSubsytemByContextObject() {
            return backpack;
        },
    },
    AbilitySystemBlueprintLibrary: {
        GetAbilitySystemComponent() {
            return null;
        },
    },
    GameplayStatics: {
        GetPlayerController() {
            return null;
        },
        GetPlayerCharacter() {
            return character;
        },
        GetPlayerCameraManager() {
            return null;
        },
        IsGamePaused() {
            return false;
        },
        GetCurrentLevelName() {
            return "PBZ_Ximeng_WP";
        },
    },
    BlueprintPathsLibrary: {
        ProjectSavedDir() {
            return "C:/PBZ/ProjectPBZ/Saved/";
        },
    },
};
const puerts = {
    argv: {
        getByName() {
            return gameInstance;
        },
    },
};

const originalLoad = Module._load;
Module._load = function load(request, parent, isMain) {
    if (request === "ue") return UE;
    if (request === "puerts") return puerts;
    if (request === "Library/TsHelper") throw new Error("not installed");
    return originalLoad.call(this, request, parent, isMain);
};

try {
    const apiPath = path.join(
        __dirname, "..", "game_bundle", "mod", "js",
        "pbz-neko-companion", "game_api.js");
    delete require.cache[require.resolve(apiPath)];
    const realNow = Date.now;
    let api;
    let state;
    try {
        const baseNow = realNow();
        let offset = 20000;
        Date.now = () => baseNow + offset;
        api = require(apiPath);
        offset = 40000;
        state = api.snapshot({ safeMode: true });
    } finally {
        Date.now = realNow;
    }
    const equipment = state.player.equipment;

    assert.equal(equipment.main_weapon.id, "Weapon_017");
    assert.equal(equipment.main_weapon.name, "红妆鬼斩");
    assert.equal(equipment.main_weapon.tier, 7);
    assert.deepEqual(
        equipment.main_weapons.map(item => item.name),
        ["黑伤", "红妆鬼斩"],
    );
    assert.equal(equipment.secondary_weapon.name, "红妆鬼斩");
    assert.deepEqual(
        equipment.phantom_edges.map(item => [item.name, item.tier, item.active]),
        [["追命锁镰", 2, false], ["巨凶斧", 4, true]],
    );
    assert.equal(equipment.accessories[0].name, "珍玩妖织");
    assert.equal(equipment.accessories[0].tier, 1);
    assert.deepEqual(
        equipment.medicines.map(item => [item.name, item.tier, item.slot]),
        [["药葫芦", 5, "top"], ["慈花甘露", 2, "bottom"]],
    );
    assert.equal(state.capabilities.equipment.main_weapon, true);
    assert.equal(state.capabilities.equipment.phantom_edges, 2);
    console.log("game_api equipment test passed");
} finally {
    Module._load = originalLoad;
}
