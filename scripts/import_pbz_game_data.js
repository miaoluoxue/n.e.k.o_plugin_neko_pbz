#!/usr/bin/env node
"use strict";

/**
 * Refresh the PBZ knowledge seeds from data already present in the game install.
 *
 * This is a developer tool. The plugin never imports or executes game/mod files at
 * runtime. Point it at a PBZ installation with PBZModLoader and UE4SSQuestGuide:
 *
 *   node scripts/import_pbz_game_data.js
 *   node scripts/import_pbz_game_data.js --game "D:/Games/PBZ"
 *
 * The generated JSON keeps compact facts and source references, not a copied copy
 * of the installed JavaScript or its long-form guide text.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "..");
const DEFAULT_GAME_ROOT = "E:/SteamLibrary/steamapps/common/PBZ";

function parseArgs(argv) {
  let gameRoot = process.env.PBZ_GAME_ROOT || DEFAULT_GAME_ROOT;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--game" && argv[i + 1]) {
      gameRoot = argv[i + 1];
      i += 1;
    }
  }
  return { gameRoot: path.resolve(gameRoot) };
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function loadGameModule(filePath) {
  delete require.cache[require.resolve(filePath)];
  return require(filePath);
}

function writeJson(name, payload) {
  const outPath = path.join(PROJECT_ROOT, "data", "knowledge", name);
  fs.writeFileSync(outPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  return outPath;
}

function normalizeName(value) {
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase("zh-CN")
    .replace(/\[[^\]]*\]|【[^】]*】|\([^)]*\)|（[^）]*）/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, "");
}

function safeSegment(value, fallback = "entry") {
  const text = String(value || "")
    .normalize("NFKC")
    .replace(/[^A-Za-z0-9_.-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 96);
  return text || fallback;
}

function shortHash(value) {
  return crypto.createHash("sha1").update(String(value)).digest("hex").slice(0, 12);
}

function uniqueStrings(values) {
  const out = [];
  const seen = new Set();
  for (const value of values || []) {
    const text = String(value || "").trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
  }
  return out;
}

function entityIndex(entities) {
  const byId = new Map();
  const byName = new Map();
  for (const entity of entities) {
    if (!entity || !entity.id) continue;
    byId.set(entity.id, entity);
    const names = [entity.name, ...(entity.aliases || [])];
    for (const name of names) {
      const key = normalizeName(name);
      if (!key) continue;
      const bucket = byName.get(key) || [];
      bucket.push(entity);
      byName.set(key, bucket);
    }
  }
  return { byId, byName };
}

function findNamedEntity(index, name, options = {}) {
  const key = normalizeName(name);
  if (!key) return null;
  const exact = index.byName.get(key) || [];
  if (exact.length) {
    const canonical = exact.filter((entity) => normalizeName(entity.name) === key);
    if (canonical.length) return canonical[0];
    if (exact.length === 1) return exact[0];
  }
  if (options.exactOnly) return null;

  const candidates = new Map();
  for (const [known, entities] of index.byName) {
    if (known.length < 2) continue;
    if (known.includes(key) || key.includes(known)) {
      for (const entity of entities) candidates.set(entity.id, entity);
    }
  }
  return candidates.size === 1 ? [...candidates.values()][0] : null;
}

function findBossEntity(index, name) {
  const exact = findNamedEntity(index, name, { exactOnly: true });
  if (exact) return exact;

  // Boss variants often prefix a title ("组织猎杀者：追命"), while generic
  // enemy families ("鬼差") must stay separate. A unique suffix match handles
  // the former without collapsing distinct 鬼差 bosses into one entity.
  const key = normalizeName(name);
  const candidates = new Map();
  for (const [known, entities] of index.byName) {
    if (known.length < 2 || !key.endsWith(known)) continue;
    for (const entity of entities) candidates.set(entity.id, entity);
  }
  return candidates.size === 1 ? [...candidates.values()][0] : null;
}

function mergeAliases(entity, aliases) {
  return uniqueStrings([...(entity.aliases || []), ...(aliases || [])]);
}

function extractObjectLiteral(source, marker) {
  const markerAt = source.indexOf(marker);
  if (markerAt < 0) throw new Error(`Missing marker: ${marker}`);
  const start = source.indexOf("{", markerAt);
  if (start < 0) throw new Error(`Missing object after: ${marker}`);

  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < source.length; i += 1) {
    const ch = source[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === "\"") inString = false;
      continue;
    }
    if (ch === "\"") {
      inString = true;
      continue;
    }
    if (ch === "{") depth += 1;
    if (ch === "}") {
      depth -= 1;
      if (depth === 0) return JSON.parse(source.slice(start, i + 1));
    }
  }
  throw new Error(`Unclosed object after: ${marker}`);
}

function inferWorldLabels(catalog, chapters) {
  const labels = new Map();
  for (const quest of catalog.quests || []) {
    for (const step of quest.steps || []) {
      for (const point of step.points || []) {
        if (point.world && point.worldLabel) labels.set(point.world, point.worldLabel);
      }
    }
  }
  for (const chapter of catalog.chapters || []) {
    if (chapter.world && chapter.name) labels.set(chapter.world, chapter.name);
  }
  for (const file of chapters) {
    if (file.world && file.region && (
      !labels.has(file.world) || /^第.+章$/.test(labels.get(file.world))
    )) {
      labels.set(file.world, file.region);
    }
  }
  return labels;
}

function compactQuestStep(step, labels) {
  const consequences = step.consequences || {};
  const rewards = uniqueStrings(
    (step.rewards || []).map((reward) => reward && reward.name),
  );
  const targets = [];
  const seenTargets = new Set();
  for (const point of step.points || []) {
    if (!point || !point.position) continue;
    const key = `${point.world}|${point.label || point.name}|${point.position.join(",")}`;
    if (seenTargets.has(key)) continue;
    seenTargets.add(key);
    targets.push({
      label: point.label || point.name || "",
      world: point.world || "",
      world_label: labels.get(point.world) || point.worldLabel || "",
      position_cm: point.position,
    });
  }
  return {
    id: String(step.id || ""),
    title: String(step.title || ""),
    instruction: String(step.instruction || ""),
    location: String(step.location || ""),
    world: String(step.world || ""),
    world_label: labels.get(step.world) || "",
    prerequisites: uniqueStrings(step.prerequisites),
    failure_note: String(consequences.failureNote || ""),
    rewards,
    targets,
  };
}

function buildKnowledge(args) {
  const guideDir = path.join(
    args.gameRoot,
    "ProjectPBZ",
    "Content",
    "JavaScript",
    "UE4SSQuestGuide",
    "guide",
  );
  const mapHelperPath = path.join(
    args.gameRoot,
    "ProjectPBZ",
    "PBZModLoader",
    "mods",
    "pbz-map-helper",
    "map-helper.js",
  );

  for (const required of [
    path.join(guideDir, "QuestGuideCatalog.js"),
    path.join(guideDir, "QuestGuideBossData.js"),
    path.join(guideDir, "QuestGuideNpcData.js"),
    mapHelperPath,
  ]) {
    if (!fs.existsSync(required)) throw new Error(`Missing source: ${required}`);
  }

  const catalog = loadGameModule(path.join(guideDir, "QuestGuideCatalog.js"));
  const bossData = loadGameModule(path.join(guideDir, "QuestGuideBossData.js"));
  const npcData = loadGameModule(path.join(guideDir, "QuestGuideNpcData.js"));
  const chapterFiles = fs.readdirSync(guideDir)
    .filter((name) => /^QuestGuideChapter\d+\.js$/.test(name))
    .sort((a, b) => Number(a.match(/\d+/)[0]) - Number(b.match(/\d+/)[0]))
    .map((name, index) => ({
      ...loadGameModule(path.join(guideDir, name)),
      __fileName: name,
      __ordinal: index + 1,
    }));
  const labels = inferWorldLabels(catalog, chapterFiles);

  const existing = [];
  for (const fileName of [
    "seed.json",
    "seed_bosses.json",
    "seed_equipment.json",
    "seed_world.json",
  ]) {
    const filePath = path.join(PROJECT_ROOT, "data", "knowledge", fileName);
    if (!fs.existsSync(filePath)) continue;
    existing.push(...(readJson(filePath).entities || []));
  }
  const existingIndex = entityIndex(existing);

  // ── items and equipment ────────────────────────────────────────────────
  const mapHelperSource = fs.readFileSync(mapHelperPath, "utf8");
  const itemCatalog = extractObjectLiteral(mapHelperSource, "const PBZ_ITEM_NAMES =");
  const catalogByGameKey = new Map();
  for (const [catalogKey, value] of Object.entries(itemCatalog)) {
    if (!value || !value.name || !value.key) continue;
    const bucket = catalogByGameKey.get(value.key) || {
      gameKey: value.key,
      name: value.name,
      category: value.category || "道具",
      catalogKeys: [],
      aliases: [],
    };
    bucket.catalogKeys.push(catalogKey);
    bucket.aliases.push(value.name);
    catalogByGameKey.set(value.key, bucket);
  }

  const typeByCategory = {
    "武器": "weapon",
    "影之武装": "phantom_edge",
    "饰品": "accessory",
    "药瓶": "medicine",
    "道具": "item",
  };
  const curatedItemIndex = entityIndex(
    existing.filter((entity) => [
      "weapon", "phantom_edge", "accessory", "medicine", "item",
    ].includes(entity.type)),
  );
  const itemEntities = [];
  const itemNameIndex = [];
  for (const item of catalogByGameKey.values()) {
    const type = typeByCategory[item.category] || "item";
    const curated = findNamedEntity(curatedItemIndex, item.name, { exactOnly: true });
    const entity = {
      id: curated?.id || `game.${type}.${safeSegment(item.gameKey)}`,
      type,
      name: item.name,
      aliases: uniqueStrings([
        ...(curated?.aliases || []),
        ...item.aliases.slice(1),
      ]),
      spoiler_level: type === "item" ? 2 : 1,
      confidence: Math.max(Number(curated?.confidence || 0), 0.9),
      source: curated?.source || "pbz_item_catalog",
      facts: {
        ...(curated?.facts || {}),
        category: item.category,
        game_key: item.gameKey,
        catalog_keys: uniqueStrings(item.catalogKeys),
        acquisition_hints: curated?.facts?.acquisition_hints || [],
        note: "名称与分类来自安装包物品目录；效果、数值与获取条件需以游戏内说明为准。",
        source_refs: uniqueStrings([
          ...(curated?.facts?.source_refs || []),
          "pbz_item_catalog",
        ]),
      },
    };
    itemEntities.push(entity);
    itemNameIndex.push(entity);
  }
  const itemIndex = entityIndex(itemNameIndex);

  // ── bosses ─────────────────────────────────────────────────────────────
  const guideBossCards = [];
  for (const file of chapterFiles) {
    for (const section of file.sections || []) {
      for (const card of section.cards || []) {
        if (card.type === "首") {
          guideBossCards.push({
            title: card.title || "",
            note: card.note || "",
            chapter: file.chapter || file.name || "",
            chapterName: file.name || "",
            section: section.title || "",
          });
        }
      }
    }
  }

  const bossEntities = [];
  const bossIds = new Set();
  function upsertBoss(name, payload) {
    const existingBoss = findBossEntity(existingIndex, name);
    const id = existingBoss?.id || `boss.guide.${shortHash(normalizeName(name))}`;
    let entity = bossEntities.find((entry) => entry.id === id);
    if (!entity) {
      const base = existingBoss ? JSON.parse(JSON.stringify(existingBoss)) : {
        id,
        type: "boss",
        name,
        aliases: [],
        region: "",
        spoiler_level: 2,
        confidence: 0.65,
        source: "questguide",
        facts: { category: "Boss" },
      };
      base.type = "boss";
      base.spoiler_level = Math.max(2, Number(base.spoiler_level || 1));
      base.facts = { ...(base.facts || {}) };
      entity = base;
      bossEntities.push(entity);
      bossIds.add(id);
    }
    entity.aliases = mergeAliases(entity, [name, ...(payload.aliases || [])]);
    const newFacts = {
      ...(payload.facts || {}),
    };
    entity.facts = { ...(entity.facts || {}), ...newFacts };
    entity.region = entity.region || payload.region || "";
    entity.confidence = Math.max(
      Number(entity.confidence || 0),
      Number(payload.confidence || 0),
    );
    entity.facts.source_refs = uniqueStrings([
      ...(entity.facts.source_refs || []),
      ...(payload.sourceRefs || []),
    ]);
    if (payload.summary) entity.facts.summary = payload.summary;
  }

  for (const boss of bossData) {
    const worldLabel = labels.get(boss.world) || boss.world || "";
    const hint = String(boss.evidence?.hint || "").replace(/\s+/g, " ").trim();
    upsertBoss(boss.name, {
      region: worldLabel,
      confidence: boss.evidence ? 0.82 : 0.7,
      sourceRefs: [boss.evidence?.source || "questguide_boss_data"],
      summary: hint || "首领战斗区域",
      facts: {
        map_world: boss.world || "",
        map_world_label: worldLabel,
        map_position_cm: boss.position || null,
        boss_group: hint,
        guide_battle_id: boss.id || "",
        guide_battle_kind: boss.kind || "",
      },
    });
  }

  for (const card of guideBossCards) {
    upsertBoss(card.title, {
      region: card.chapterName || "",
      confidence: card.note ? 0.7 : 0.6,
      sourceRefs: ["questguide_chapters"],
      summary: card.note || card.section,
      facts: {
        guide_note: card.note,
        guide_chapter: card.chapter,
        guide_section: card.section,
      },
    });
  }
  bossEntities.sort((a, b) => a.id.localeCompare(b.id));

  // ── quests ─────────────────────────────────────────────────────────────
  const questEntities = [];
  const questById = new Map();
  for (const quest of catalog.quests || []) {
    const steps = (quest.steps || []).map((step) => compactQuestStep(step, labels));
    const guideNotes = [];
    const rewards = [];
    for (const supplement of quest.supplements || []) {
      rewards.push(supplement.reward);
      for (const step of supplement.steps || []) guideNotes.push(step);
    }
    const worlds = uniqueStrings(quest.worlds);
    const entity = {
      id: `quest.${safeSegment(quest.id, shortHash(quest.name))}`,
      type: "quest",
      name: quest.name || quest.id,
      aliases: uniqueStrings([quest.id]),
      region: worlds.map((world) => labels.get(world) || world).join(" / "),
      spoiler_level: 2,
      confidence: 0.76,
      source: "questguide_catalog",
      facts: {
        category: "任务",
        quest_type: quest.type || "",
        quest_id: quest.id || "",
        worlds,
        world_labels: worlds.map((world) => labels.get(world) || world),
        step_count: steps.length,
        summary: steps[0]?.instruction || quest.name || "",
        steps,
        guide_notes: uniqueStrings(guideNotes),
        rewards: uniqueStrings(rewards),
        source_refs: [
          "questguide_catalog",
          quest.evidence?.sourceAsset || "",
          ...(quest.supplements || []).map((item) => item.source || ""),
        ].filter(Boolean),
      },
    };
    questEntities.push(entity);
    questById.set(String(quest.id), entity);
  }
  for (const guide of catalog.unboundGuides || []) {
    const entity = {
      id: `quest.guide.${shortHash(normalizeName(guide.name))}`,
      type: "quest",
      name: guide.name || "未绑定任务",
      aliases: uniqueStrings([guide.nativeCandidate]),
      region: "",
      spoiler_level: 2,
      confidence: 0.58,
      source: "questguide_unbound_guide",
      facts: {
        category: "任务（攻略来源）",
        quest_type: "Guide",
        summary: (guide.steps || [])[0] || "",
        steps: (guide.steps || []).map((step, index) => ({
          id: String(index + 1),
          instruction: step,
        })),
        guide_notes: uniqueStrings(guide.notes),
        source_refs: uniqueStrings([guide.source, guide.nativeIdentity]),
        evidence_warning: guide.evidenceDistinction || "",
      },
    };
    questEntities.push(entity);
    if (guide.nativeCandidate) questById.set(guide.nativeCandidate, entity);
  }
  questEntities.sort((a, b) => a.id.localeCompare(b.id));

  // ── chapter cards, collectibles, bells and route summaries ─────────────
  const guideEntities = [];
  const chapterCards = [];
  const worldStats = new Map();
  const cardTypeToType = {
    "铃": "bell",
    "书": "collectible",
    "花": "collectible",
    "琥": "collectible",
    "珀": "collectible",
    "石": "collectible",
    "钥": "collectible",
    "宝": "collectible",
    "魂": "collectible",
    "说": "collectible",
    "战": "guide",
  };

  for (const file of chapterFiles) {
    const chapterNo = Number(
      String(file.chapter || file.name || file.__ordinal).match(/\d+/)?.[0] || 0,
    );
    const inferredWorld = file.world
      || catalog.chapters?.[chapterNo - 1]?.world
      || "";
    const chapterName = file.name || file.region || labels.get(inferredWorld) || `第${chapterNo}章`;
    const worldLabel = labels.get(inferredWorld) || file.region || inferredWorld;
    const stats = worldStats.get(inferredWorld) || { chapterNames: [], cards: 0 };
    stats.chapterNames.push(chapterName);

    for (const section of file.sections || []) {
      const sectionCards = section.cards || [];
      stats.cards += sectionCards.length;
      chapterCards.push(...sectionCards.map((card) => ({ file, chapterNo, inferredWorld, chapterName, section, card })));

      guideEntities.push({
        id: `route.${safeSegment(file.chapter || chapterNo)}.${safeSegment(section.id, shortHash(section.title))}`,
        type: "route",
        name: section.title || `路线 ${section.number || ""}`,
        aliases: [],
        region: worldLabel,
        spoiler_level: 1,
        confidence: 0.72,
        source: "questguide_chapters",
        facts: {
          category: "探索路线",
          chapter: chapterName,
          world: inferredWorld,
          world_label: worldLabel,
          section_number: section.number || null,
          return_visit: Boolean(file.returnVisit),
          card_count: sectionCards.length,
          summary: `本章节共 ${sectionCards.length} 个探索/收集节点`,
          steps: sectionCards.map((card) => ({
            kind: card.type || "",
            title: card.title || "",
            note: card.note || "",
          })),
          source_refs: ["questguide_chapters"],
        },
      });
    }
    worldStats.set(inferredWorld, stats);
  }
  for (const [world, label] of labels.entries()) {
    if (!worldStats.has(world)) {
      worldStats.set(world, { chapterNames: [], cards: 0 });
    }
    if (!label) labels.set(world, world);
  }

  const sectionLocation = new Map();
  for (const cardItem of chapterCards) {
    const { file, chapterNo, inferredWorld, chapterName, section, card } = cardItem;
    const worldLabel = labels.get(inferredWorld) || file.region || inferredWorld;
    const note = String(card.note || "").trim();
    const location = {
      chapter: chapterName,
      section: section.title || "",
      world: inferredWorld,
      world_label: worldLabel,
      note,
    };
    sectionLocation.set(`${safeSegment(file.chapter || chapterNo)}.${safeSegment(card.key)}`, {
      file,
      chapterNo,
      inferredWorld,
      chapterName,
      section,
      card,
      worldLabel,
      note,
      location,
    });

    // Enrich the matching quest instead of creating a second quest result.
    if (card.quest && questById.has(String(card.quest))) {
      const quest = questById.get(String(card.quest));
      const guideNote = [section.title, card.title, note].filter(Boolean).join(" · ");
      quest.facts.guide_notes = uniqueStrings([
        ...(quest.facts.guide_notes || []),
        guideNote,
      ]);
      continue;
    }

    // Enrich an item with its known acquisition location(s).
    if (["武", "影", "饰", "药", "魂"].includes(card.type)) {
      const item = findNamedEntity(itemIndex, card.title);
      if (item) {
        item.facts.acquisition_hints = uniqueStrings([
          ...(item.facts.acquisition_hints || []),
          [chapterName, section.title, note].filter(Boolean).join(" · "),
        ]);
        item.facts.source_refs = uniqueStrings([
          ...(item.facts.source_refs || []),
          "questguide_chapters",
        ]);
        continue;
      }
    }

    if (card.type === "首") continue;

    const type = cardTypeToType[card.type] || "guide";
    const binding = card.binding && typeof card.binding === "object" ? card.binding : {};
    const spoilerLevel = type === "bell" || type === "route" ? 1 : 2;
    guideEntities.push({
      id: `${type}.chapter${chapterNo}.${safeSegment(card.key, shortHash(card.title + note))}`,
      type,
      name: card.title || `${card.type || "探索"}条目`,
      aliases: [],
      region: worldLabel,
      spoiler_level: spoilerLevel,
      confidence: note ? 0.72 : 0.62,
      source: "questguide_chapters",
      facts: {
        category: {
          bell: "铃铛",
          collectible: "收集物",
          guide: "挑战/玩法",
        }[type] || "探索",
        card_type: card.type || "",
        chapter: chapterName,
        section: section.title || "",
        world: inferredWorld,
        world_label: worldLabel,
        summary: note || section.title || "",
        note,
        quest: card.quest || "",
        return_visit: Boolean(file.returnVisit),
        position_cm: binding.position || null,
        item_id: binding.itemId || "",
        source_refs: ["questguide_chapters"],
      },
    });
  }

  // Add source locations to all item entities after every chapter has been read.
  itemEntities.sort((a, b) => a.id.localeCompare(b.id));

  // ── NPC index ──────────────────────────────────────────────────────────
  const npcEntities = [];
  for (const person of npcData.people || []) {
    const worldLabel = labels.get(npcData.world) || npcData.world || "";
    npcEntities.push({
      id: `npc.${safeSegment(npcData.world)}.${safeSegment(person.id, shortHash(person.name))}`,
      type: "npc",
      name: person.name || "NPC",
      aliases: uniqueStrings([person.sourceAsset]),
      region: worldLabel,
      spoiler_level: person.relevant ? 2 : 1,
      confidence: 0.7,
      source: "questguide_npc_data",
      facts: {
        category: "NPC",
        world: npcData.world || "",
        world_label: worldLabel,
        location: person.location || "",
        purpose: person.purpose || "",
        summary: person.purpose || person.location || "",
        relevant: Boolean(person.relevant),
        source_asset: person.sourceAsset || "",
        topics: person.topics || [],
        source_refs: ["questguide_npc_data"],
      },
    });
  }

  // ── region coverage ────────────────────────────────────────────────────
  const regionEntities = [];
  const regionIndex = entityIndex(
    existing.filter((entity) => entity.type === "region"),
  );
  for (const [world, stats] of worldStats.entries()) {
    const label = labels.get(world) || world || "未知区域";
    const matched = findNamedEntity(regionIndex, label);
    const chapter = catalog.chapters?.find((item) => item.world === world);
    const entity = matched
      ? JSON.parse(JSON.stringify(matched))
      : {
        id: `region.${safeSegment(world || label)}`,
        type: "region",
        name: label,
        aliases: [],
        region: "",
        spoiler_level: 1,
        confidence: 0.7,
        source: "questguide_chapters",
        facts: { category: "区域" },
      };
    entity.facts = {
      ...(entity.facts || {}),
      world_id: world,
      chapter_names: uniqueStrings(stats.chapterNames),
      guide_card_count: stats.cards,
      reference_total: chapter?.referenceTotal ?? null,
      content_breakdown: chapter?.counts || {},
      source_refs: uniqueStrings([
        ...(entity.facts?.source_refs || []),
        "questguide_chapters",
      ]),
    };
    entity.confidence = Math.max(Number(entity.confidence || 0), 0.72);
    regionEntities.push(entity);
  }
  regionEntities.sort((a, b) => a.id.localeCompare(b.id));

  // Apply every successful item-name match back to the catalog entities that
  // already contain the source note. This keeps duplicates out of search.
  for (const locationEntry of sectionLocation.values()) {
    const { card, location } = locationEntry;
    if (!["武", "影", "饰", "药", "魂"].includes(card.type)) continue;
    const item = findNamedEntity(itemIndex, card.title);
    if (!item) continue;
    item.facts.acquisition_hints = uniqueStrings([
      ...(item.facts.acquisition_hints || []),
      [location.chapter, location.section, location.note].filter(Boolean).join(" · "),
    ]);
  }
  for (const item of itemEntities) {
    if (item.facts.acquisition_hints.length) {
      item.facts.source_refs = uniqueStrings([
        ...(item.facts.source_refs || []),
        "questguide_chapters",
      ]);
    }
    if (!item.facts.summary) {
      item.facts.summary = item.facts.acquisition_hints[0]
        || item.facts.tip
        || item.facts.use
        || item.facts.note;
    }
  }

  const sourceMetadata = {
    version: 1,
    imported_at: new Date().toISOString(),
    game_root_hint: "<PBZ installation>",
    sources: [
      {
        name: "PBZModLoader pbz-map-helper item catalog",
        kind: "installed_mod_data",
        gives: "物品键、名称、分类",
        confidence: 0.9,
      },
      {
        name: "UE4SSQuestGuide QuestGuideBossData 0.6.7",
        kind: "installed_mod_data",
        gives: "29 个首领战区域、地图、世界与奖励条件",
        confidence: 0.82,
      },
      {
        name: "UE4SSQuestGuide QuestGuideCatalog",
        kind: "installed_mod_data",
        gives: "66 条任务、216 个步骤、357 个目标点、区域检查表",
        confidence: 0.76,
      },
      {
        name: "UE4SSQuestGuide chapters 1-9",
        kind: "installed_mod_data",
        gives: "1054 个探索卡片、铃铛/收集物/首领地点的紧凑攻略事实",
        confidence: 0.72,
      },
      {
        name: "UE4SSQuestGuide NPC roster",
        kind: "installed_mod_data",
        gives: "溪谷 NPC 位置、用途与对话节点",
        confidence: 0.7,
      },
    ],
    policy: "只保留结构化事实与短说明；不把安装包脚本、长攻略全文或二进制资源复制进插件。",
  };

  return {
    items: itemEntities,
    bosses: bossEntities,
    quests: questEntities,
    guide: guideEntities,
    npcs: npcEntities,
    regions: regionEntities,
    sourceMetadata,
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const data = buildKnowledge(args);
  const files = [
    writeJson("seed_game_catalog.json", {
      version: 2,
      source: "PBZ installation item catalog; names/categories and short acquisition hints only",
      entities: data.items,
      relations: [],
    }),
    writeJson("seed_game_bosses.json", {
      version: 1,
      source: "PBZ quest-guide boss locations and compact chapter notes",
      entities: data.bosses,
      relations: [],
    }),
    writeJson("seed_game_quests.json", {
      version: 1,
      source: "PBZ quest-guide catalog; compact steps, targets, warnings and rewards",
      entities: data.quests,
      relations: [],
    }),
    writeJson("seed_game_guide.json", {
      version: 1,
      source: "PBZ chapter guide cards; compact exploration and collection facts",
      entities: data.guide,
      relations: [],
    }),
    writeJson("seed_game_npcs.json", {
      version: 1,
      source: "PBZ quest-guide NPC roster",
      entities: data.npcs,
      relations: [],
    }),
    writeJson("seed_game_regions.json", {
      version: 1,
      source: "PBZ quest-guide world and coverage metadata",
      entities: data.regions,
      relations: [],
    }),
  ];
  fs.writeFileSync(
    path.join(PROJECT_ROOT, "data", "knowledge", "sources.json"),
    `${JSON.stringify(data.sourceMetadata, null, 2)}\n`,
    "utf8",
  );

  console.log(JSON.stringify({
    ok: true,
    counts: {
      items: data.items.length,
      bosses: data.bosses.length,
      quests: data.quests.length,
      guide: data.guide.length,
      npcs: data.npcs.length,
      regions: data.regions.length,
    },
    files,
  }, null, 2));
}

try {
  main();
} catch (error) {
  console.error(error.stack || error.message);
  process.exitCode = 1;
}
