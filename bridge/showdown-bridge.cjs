#!/usr/bin/env node
"use strict";

const path = require("node:path");
const readline = require("node:readline");
const crypto = require("node:crypto");
const fs = require("node:fs");

const PROTOCOL_VERSION = "1.0.0";
const MAX_LINE_BYTES = 1024 * 1024;
const MAX_SESSIONS = 64;
const MAX_PREVIEW_ACTIONS = 4096;
const SESSION_ID = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/;
const SELECTOR_ID = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,239}$/;
const PLAYER_IDS = new Set(["p1", "p2"]);
const SODIUM_SEED = /^sodium,[0-9a-f]{64}$/;
const bridgeSource = fs.readFileSync(__filename, "utf8").replace(/\r\n?/g, "\n");
const bridgeSha256 = crypto.createHash("sha256").update(bridgeSource, "utf8").digest("hex");
const SET_FIELDS = new Set([
  "name", "species", "item", "ability", "moves", "nature", "gender", "evs", "ivs",
  "level", "shiny", "happiness", "pokeball", "hpType", "dynamaxLevel", "gigantamax", "teraType",
]);
const GENERATED_SET_FIELDS = [
  "species", "item", "ability", "moves", "nature", "gender", "evs", "ivs",
  "level", "shiny", "happiness", "pokeball", "hpType", "dynamaxLevel",
  "gigantamax", "teraType",
];
const REQUIRED_SET_FIELDS = ["species", "ability", "moves", "nature", "level"];
const STAT_IDS = new Set(["hp", "atk", "def", "spa", "spd", "spe"]);

if (process.argv.length !== 4) {
  process.stderr.write("usage: showdown-bridge.cjs <pokemon-showdown-root> <allowed-format-ids>\n");
  process.exit(64);
}

const showdownRoot = path.resolve(process.argv[2]);
const allowedFormatIds = new Set(process.argv[3].split(","));
if (!allowedFormatIds.size || [...allowedFormatIds].some(id => !/^[a-z0-9]{1,128}$/.test(id))) {
  process.stderr.write("allowed format IDs are invalid\n");
  process.exit(64);
}
let showdown;
let extractChannelMessages;
try {
  showdown = require(path.join(showdownRoot, "dist", "sim", "index.js"));
  ({extractChannelMessages} = require(path.join(showdownRoot, "dist", "sim", "battle.js")));
} catch (error) {
  process.stderr.write(`failed to load pinned Pokemon Showdown build: ${error.message}\n`);
  process.exit(78);
}

const {Battle, BattleStream, Dex, Teams, TeamValidator} = showdown;
const sessions = new Map();

class ProtocolError extends Error {
  constructor(code, message, details = undefined) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

function parseStrictJson(text) {
  let index = 0;
  let depth = 0;

  function fail(message) {
    throw new ProtocolError("INVALID_JSON", `${message} at offset ${index}`);
  }

  function whitespace() {
    while (index < text.length && /[\u0020\u000a\u000d\u0009]/.test(text[index])) index++;
  }

  function string() {
    const start = index;
    if (text[index++] !== '"') fail("expected string");
    let escaped = false;
    while (index < text.length) {
      const character = text[index++];
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === '"') {
        try {
          return JSON.parse(text.slice(start, index));
        } catch (_error) {
          fail("invalid string");
        }
      } else if (character.charCodeAt(0) < 0x20) {
        fail("unescaped control character");
      }
    }
    fail("unterminated string");
  }

  function value() {
    whitespace();
    if (++depth > 64) fail("maximum nesting depth exceeded");
    let result;
    const character = text[index];
    if (character === "{") {
      result = object();
    } else if (character === "[") {
      result = array();
    } else if (character === '"') {
      result = string();
    } else if (text.startsWith("true", index)) {
      index += 4;
      result = true;
    } else if (text.startsWith("false", index)) {
      index += 5;
      result = false;
    } else if (text.startsWith("null", index)) {
      index += 4;
      result = null;
    } else {
      const match = text.slice(index).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
      if (!match) fail("expected value");
      index += match[0].length;
      result = Number(match[0]);
      if (!Number.isFinite(result)) fail("non-finite number");
    }
    depth--;
    return result;
  }

  function object() {
    index++;
    const result = Object.create(null);
    const keys = new Set();
    whitespace();
    if (text[index] === "}") {
      index++;
      return result;
    }
    while (true) {
      whitespace();
      if (text[index] !== '"') fail("object key must be a string");
      const key = string();
      if (keys.has(key)) {
        throw new ProtocolError("DUPLICATE_JSON_KEY", `duplicate JSON key: ${key}`);
      }
      keys.add(key);
      whitespace();
      if (text[index++] !== ":") fail("expected colon");
      result[key] = value();
      whitespace();
      const separator = text[index++];
      if (separator === "}") return result;
      if (separator !== ",") fail("expected comma or object end");
    }
  }

  function array() {
    index++;
    const result = [];
    whitespace();
    if (text[index] === "]") {
      index++;
      return result;
    }
    while (true) {
      result.push(value());
      whitespace();
      const separator = text[index++];
      if (separator === "]") return result;
      if (separator !== ",") fail("expected comma or array end");
    }
  }

  const parsed = value();
  whitespace();
  if (index !== text.length) fail("trailing content");
  return parsed;
}

function assertObject(value, label, allowed, required = allowed) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProtocolError("INVALID_REQUEST", `${label} must be an object`);
  }
  const keys = Object.keys(value);
  const unknown = keys.filter(key => !allowed.includes(key));
  const missing = required.filter(key => !Object.hasOwn(value, key));
  if (unknown.length) {
    throw new ProtocolError("INVALID_REQUEST", `${label} has unknown fields: ${unknown.sort().join(", ")}`);
  }
  if (missing.length) {
    throw new ProtocolError("INVALID_REQUEST", `${label} is missing fields: ${missing.join(", ")}`);
  }
}

function assertString(value, label, maximum = 256) {
  if (typeof value !== "string" || !value || value.length > maximum || /[\u0000-\u001f\u007f]/.test(value)) {
    throw new ProtocolError("INVALID_REQUEST", `${label} must be a non-empty control-free string of at most ${maximum} characters`);
  }
  return value;
}

function assertTeam(team, label) {
  if (!Array.isArray(team) || team.length < 1 || team.length > 24) {
    throw new ProtocolError("INVALID_REQUEST", `${label} must contain 1 to 24 sets`);
  }
  for (let index = 0; index < team.length; index++) {
    const set = team[index];
    const setLabel = `${label}[${index}]`;
    if (set === null || typeof set !== "object" || Array.isArray(set)) {
      throw new ProtocolError("INVALID_REQUEST", `${label}[${index}] must be an object`);
    }
    const unknown = Object.keys(set).filter(key => !SET_FIELDS.has(key));
    const missing = REQUIRED_SET_FIELDS.filter(key => !Object.hasOwn(set, key));
    if (unknown.length || missing.length) {
      throw new ProtocolError(
        "INVALID_REQUEST",
        `${setLabel} fields differ: missing=${missing.sort().join(",")}; unknown=${unknown.sort().join(",")}`,
      );
    }
    for (const field of ["species", "ability", "nature"]) assertString(set[field], `${setLabel}.${field}`, 128);
    for (const field of ["name", "item", "pokeball", "hpType", "teraType"]) {
      if (Object.hasOwn(set, field)) assertString(set[field], `${setLabel}.${field}`, 128);
    }
    if (Object.hasOwn(set, "gender") && !["M", "F", "N"].includes(set.gender)) {
      throw new ProtocolError("INVALID_REQUEST", `${setLabel}.gender must be M, F, or N`);
    }
    if (!Array.isArray(set.moves) || set.moves.length < 1 || set.moves.length > 4) {
      throw new ProtocolError("INVALID_REQUEST", `${setLabel}.moves must contain 1 to 4 moves`);
    }
    set.moves.forEach((move, moveIndex) => assertString(move, `${setLabel}.moves[${moveIndex}]`, 128));
    for (const [field, maximum] of [["evs", 65535], ["ivs", 31]]) {
      if (!Object.hasOwn(set, field)) continue;
      const stats = set[field];
      if (stats === null || typeof stats !== "object" || Array.isArray(stats)) {
        throw new ProtocolError("INVALID_REQUEST", `${setLabel}.${field} must be an object`);
      }
      const unknownStats = Object.keys(stats).filter(key => !STAT_IDS.has(key));
      if (unknownStats.length) throw new ProtocolError("INVALID_REQUEST", `${setLabel}.${field} has unknown stats`);
      for (const [stat, amount] of Object.entries(stats)) {
        if (!Number.isInteger(amount) || amount < 0 || amount > maximum) {
          throw new ProtocolError("INVALID_REQUEST", `${setLabel}.${field}.${stat} is outside its integer range`);
        }
      }
    }
    for (const [field, minimum, maximum] of [["level", 1, 9999], ["happiness", 0, 255], ["dynamaxLevel", 0, 10]]) {
      if (Object.hasOwn(set, field) && (!Number.isInteger(set[field]) || set[field] < minimum || set[field] > maximum)) {
        throw new ProtocolError("INVALID_REQUEST", `${setLabel}.${field} is outside its integer range`);
      }
    }
    for (const field of ["shiny", "gigantamax"]) {
      if (Object.hasOwn(set, field) && typeof set[field] !== "boolean") {
        throw new ProtocolError("INVALID_REQUEST", `${setLabel}.${field} must be boolean`);
      }
    }
  }
}

function assertSeed(seed) {
  if (typeof seed !== "string" || !SODIUM_SEED.test(seed)) {
    throw new ProtocolError("INVALID_REQUEST", "seed must be sodium followed by a 32-byte lowercase hex seed");
  }
  return seed;
}

function assertFormat(formatId) {
  assertString(formatId, "format_id", 128);
  if (!allowedFormatIds.has(formatId)) {
    throw new ProtocolError("UNBOUND_FORMAT", `format is not bound by the dependency manifest: ${formatId}`);
  }
  const format = Dex.formats.get(formatId);
  if (!format.exists) throw new ProtocolError("UNKNOWN_FORMAT", `unknown format: ${formatId}`);
  return format;
}

function validateTeam(formatId, team) {
  const problems = new TeamValidator(formatId).validateTeam(team);
  return problems ? [...problems] : [];
}

function canonicalChoiceInput(session, player, choice) {
  const liveState = JSON.stringify(session.stream.battle.toJSON());
  const clone = Battle.fromJSON(liveState);
  const side = clone[player];
  if (!side || !side.choose(choice) || !side.isChoiceDone()) {
    throw new ProtocolError(
      "CHOICE_REJECTED",
      `choice could not be canonicalized for ${player}`,
    );
  }
  const canonical = side.getChoice();
  if (!canonical || JSON.stringify(session.stream.battle.toJSON()) !== liveState) {
    session.poisoned = "choice canonicalization violated live-state isolation";
    throw new ProtocolError("SESSION_POISONED", session.poisoned);
  }
  return `>${player} ${canonical}`;
}

function assertGenerationSeeds(value) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 512) {
    throw new ProtocolError("INVALID_REQUEST", "seeds must contain 1 to 512 Showdown seeds");
  }
  return value.map((seed, seedIndex) => {
    if (!Array.isArray(seed) || seed.length !== 4 || seed.some(part => (
      !Number.isInteger(part) || part < 0 || part > 0xffff
    ))) {
      throw new ProtocolError(
        "INVALID_REQUEST",
        `seeds[${seedIndex}] must contain four integers between 0 and 65535`,
      );
    }
    return [...seed];
  });
}

function normalizeGeneratedTeam(rawTeam) {
  if (!Array.isArray(rawTeam) || rawTeam.length !== 6) {
    throw new ProtocolError("GENERATOR_DRIFT", "random-team generator did not return six sets");
  }
  const seenItems = new Set();
  const team = rawTeam.map(rawSet => {
    const set = {};
    for (const field of GENERATED_SET_FIELDS) {
      if (Object.hasOwn(rawSet, field)) set[field] = rawSet[field];
    }
    set.nature = set.nature || "Serious";
    for (const field of ["item", "pokeball", "hpType", "teraType"]) {
      if (set[field] === "") delete set[field];
    }
    if (set.item) {
      const itemId = Dex.toID(set.item);
      if (seenItems.has(itemId)) {
        delete set.item;
      } else {
        seenItems.add(itemId);
      }
    }
    return set;
  });
  assertTeam(team, "generated_team");
  return team;
}

function normalizeLines(text) {
  return text.split("\n").filter(line => line !== "").map(line => (
    /^\|t:\|\d+$/.test(line) ? "|t:|0" : line
  ));
}

function handleOutput(session, type, rawData) {
  const data = Array.isArray(rawData) ? rawData.join("\n") : rawData;
  if (type === "update") {
    const channels = extractChannelMessages(data, [0, 1, 2]);
    session.publicLog.push(...normalizeLines(channels[0].join("\n")));
    session.visibleLogs.p1.push(...normalizeLines(channels[1].join("\n")));
    session.visibleLogs.p2.push(...normalizeLines(channels[2].join("\n")));
    return;
  }
  if (type === "sideupdate") {
    const newline = data.indexOf("\n");
    const player = newline < 0 ? data : data.slice(0, newline);
    const sideData = newline < 0 ? "" : data.slice(newline + 1);
    if (!PLAYER_IDS.has(player)) return;
    const lines = normalizeLines(sideData);
    session.visibleLogs[player].push(...lines);
    for (const line of lines) {
      if (line.startsWith("|request|")) {
        const payload = line.slice("|request|".length);
        session.requests[player] = payload ? parseStrictJson(payload) : null;
      }
    }
    return;
  }
  if (type === "end") {
    session.end = parseStrictJson(data);
  }
}

function bindOutput(session) {
  session.stream.pushMessage = (type, data) => {
    try {
      handleOutput(session, type, data);
    } catch (error) {
      session.poisoned = error?.message || "Showdown output processing failed";
      throw error;
    }
  };
}

function permutations(size, chosenSize) {
  const output = [];
  function visit(prefix, remaining) {
    if (prefix.length === chosenSize) {
      output.push(`team ${prefix.join("")}`);
      return;
    }
    for (const value of remaining) {
      visit([...prefix, value], remaining.filter(candidate => candidate !== value));
    }
  }
  visit([], Array.from({length: size}, (_unused, index) => index + 1));
  return output;
}

function switchActions(request) {
  const pokemon = request?.side?.pokemon;
  if (!Array.isArray(pokemon)) return [];
  const reviving = Boolean(pokemon[0]?.reviving);
  const actions = [];
  for (let index = 0; index < pokemon.length; index++) {
    const entry = pokemon[index];
    const fainted = typeof entry.condition === "string" && entry.condition.endsWith(" fnt");
    if ((reviving && fainted) || (!reviving && !entry.active && !fainted)) {
      actions.push(`switch ${index + 1}`);
    }
  }
  return actions;
}

function permutationCount(size, chosenSize) {
  let count = 1;
  for (let index = 0; index < chosenSize; index++) {
    count *= size - index;
    if (count > MAX_PREVIEW_ACTIONS) return count;
  }
  return count;
}

function legalActions(request, formatId) {
  if (!request || request.wait) return [];
  if (request.teamPreview) {
    const size = request.side?.pokemon?.length;
    const chosen = request.maxChosenTeamSize ?? size;
    const ruleTable = Dex.formats.getRuleTable(assertFormat(formatId));
    const minimum = ruleTable.minTeamSize;
    const maximum = ruleTable.maxTeamSize;
    const picked = ruleTable.pickedTeamSize ?? size;
    if (
      !Number.isInteger(size) || !Number.isInteger(chosen) ||
      !Number.isInteger(minimum) || !Number.isInteger(maximum) || !Number.isInteger(picked) ||
      size < minimum || size > maximum || chosen !== picked || chosen < 1 || chosen > size ||
      permutationCount(size, chosen) > MAX_PREVIEW_ACTIONS
    ) {
      throw new ProtocolError("FORMAT_DRIFT", "team preview differs from the bound effective format constraints");
    }
    return permutations(size, chosen);
  }
  if (Array.isArray(request.forceSwitch)) return switchActions(request);
  if (!Array.isArray(request.active) || !request.active[0]) return [];
  const active = request.active[0];
  const actions = [];
  if (Array.isArray(active.moves)) {
    active.moves.forEach((move, index) => {
      if (move.disabled) return;
      const number = index + 1;
      actions.push(`move ${number}`);
      if (active.canMegaEvo) actions.push(`move ${number} mega`);
      if (active.canUltraBurst) actions.push(`move ${number} ultra`);
      if (active.canDynamax) actions.push(`move ${number} dynamax`);
      if (active.canTerastallize) actions.push(`move ${number} terastallize`);
      if (Array.isArray(active.canZMove) && active.canZMove[index]) actions.push(`move ${number} zmove`);
    });
  }
  if (!active.trapped) actions.push(...switchActions(request));
  return actions;
}

function sessionSummary(session) {
  const battle = session.stream.battle;
  return {
    session_id: session.id,
    format_id: session.formatId,
    revision: session.revision,
    ended: Boolean(battle?.ended),
    winner: battle?.ended ? (battle.winner || null) : null,
    turn: battle?.turn || 0,
  };
}

function replayDocument(session) {
  const battle = session.stream.battle;
  return {
    schema_version: "1.0.0",
    format_id: session.formatId,
    seed: session.seed,
    input_log: [...battle.inputLog],
    public_log: [...session.publicLog],
    ended: Boolean(battle.ended),
    winner: battle.ended ? (battle.winner || null) : null,
    turns: battle.turn,
    score: battle.ended && session.end ? [...session.end.score] : null,
  };
}

function validateReplayInputLog(inputLog) {
  if (!Array.isArray(inputLog) || inputLog.length < 3 || inputLog.length > 10000) {
    throw new ProtocolError("INVALID_REPLAY", "input_log must contain 3 to 10000 commands");
  }
  inputLog.forEach((line, index) => assertString(line, `input_log[${index}]`, MAX_LINE_BYTES));

  if (!inputLog[0].startsWith(">start ")) {
    throw new ProtocolError("INVALID_REPLAY", "input_log must start with >start");
  }
  const start = parseStrictJson(inputLog[0].slice(">start ".length));
  assertObject(start, "input_log start", ["formatid", "seed"]);
  const format = assertFormat(start.formatid);
  const seed = assertSeed(start.seed);

  for (const [index, player] of ["p1", "p2"].entries()) {
    const prefix = `>player ${player} `;
    if (!inputLog[index + 1].startsWith(prefix)) {
      throw new ProtocolError("INVALID_REPLAY", `input_log command ${index + 1} must define ${player}`);
    }
    const playerData = parseStrictJson(inputLog[index + 1].slice(prefix.length));
    assertObject(playerData, `input_log ${player}`, ["name", "team"]);
    assertString(playerData.name, `input_log ${player}.name`, 64);
    const packed = assertString(playerData.team, `input_log ${player}.team`, MAX_LINE_BYTES);
    const team = Teams.unpack(packed);
    if (!team) throw new ProtocolError("INVALID_REPLAY", `input_log ${player} team cannot be unpacked`);
    const normalizedTeam = team.map(set => {
      const normalized = {...set};
      for (const field of Object.keys(normalized)) {
        if (normalized[field] === undefined) delete normalized[field];
      }
      for (const field of ["name", "item", "pokeball", "hpType", "teraType"]) {
        if (normalized[field] === "") delete normalized[field];
      }
      if (!Object.hasOwn(normalized, "level")) normalized.level = 100;
      return normalized;
    });
    assertTeam(normalizedTeam, `input_log ${player}.team`);
    const problems = validateTeam(format.id, team);
    if (problems.length) {
      throw new ProtocolError("INVALID_REPLAY", `input_log ${player} team is invalid`, {player, problems});
    }
  }

  for (let index = 3; index < inputLog.length; index++) {
    const match = inputLog[index].match(/^>(p1|p2) (.+)$/);
    if (!match) throw new ProtocolError("INVALID_REPLAY", `input_log command ${index} is not a player choice`);
    assertString(match[2], `input_log[${index}] choice`, 256);
  }
  return {format, seed};
}

function replayExpectationSelectors(value) {
  if (!Array.isArray(value) || value.length > 256) {
    throw new ProtocolError("INVALID_REQUEST", "selectors must contain at most 256 entries");
  }
  const ids = new Set();
  return value.map((raw, index) => {
    assertObject(raw, `selectors[${index}]`, ["selector_id", "player", "revision", "pointer"]);
    const selectorId = assertString(raw.selector_id, `selectors[${index}].selector_id`, 240);
    if (!SELECTOR_ID.test(selectorId) || ids.has(selectorId)) {
      throw new ProtocolError("INVALID_REQUEST", "selector IDs must be unique stable IDs");
    }
    ids.add(selectorId);
    const player = assertString(raw.player, `selectors[${index}].player`, 2);
    if (!PLAYER_IDS.has(player)) {
      throw new ProtocolError("INVALID_REQUEST", "selector player must be p1 or p2");
    }
    if (!Number.isSafeInteger(raw.revision) || raw.revision < 0 || raw.revision > 9999) {
      throw new ProtocolError("INVALID_REQUEST", "selector revision must be between 0 and 9999");
    }
    const pointer = assertString(raw.pointer, `selectors[${index}].pointer`, 1024);
    if (!pointer.startsWith("/")) {
      throw new ProtocolError("INVALID_REQUEST", "selector pointer must be a JSON pointer");
    }
    return {selector_id: selectorId, player, revision: raw.revision, pointer};
  });
}

function resolveJsonPointer(value, pointer) {
  let current = value;
  for (const encoded of pointer.slice(1).split("/")) {
    const token = encoded.replace(/~1/g, "/").replace(/~0/g, "~");
    if (/~(?![01])/u.test(encoded)) {
      throw new ProtocolError("INVALID_REQUEST", `invalid JSON pointer escape: ${pointer}`);
    }
    if (Array.isArray(current)) {
      if (!/^(?:0|[1-9][0-9]*)$/.test(token)) {
        throw new ProtocolError("EXPECTATION_PATH_MISSING", `array path is invalid: ${pointer}`);
      }
      const index = Number(token);
      if (!Number.isSafeInteger(index) || index >= current.length) {
        throw new ProtocolError("EXPECTATION_PATH_MISSING", `array path is absent: ${pointer}`);
      }
      current = current[index];
    } else if (current !== null && typeof current === "object" && Object.hasOwn(current, token)) {
      current = current[token];
    } else {
      throw new ProtocolError("EXPECTATION_PATH_MISSING", `object path is absent: ${pointer}`);
    }
  }
  return current;
}

function observation(session, player, since) {
  const log = session.visibleLogs[player];
  if (!Number.isInteger(since) || since < 0 || since > log.length) {
    throw new ProtocolError("INVALID_REQUEST", `since must be between 0 and ${log.length}`);
  }
  return {
    schema_version: "1.0.0",
    ...sessionSummary(session),
    player,
    request: session.requests[player],
    legal_actions: legalActions(session.requests[player], session.formatId),
    visible_log: log.slice(since),
    next_sequence: log.length,
  };
}

function getSession(params, allowPoisoned = false) {
  const id = assertString(params.session_id, "session_id", 128);
  const session = sessions.get(id);
  if (!session) throw new ProtocolError("SESSION_NOT_FOUND", `unknown session: ${id}`);
  if (session.poisoned && !allowPoisoned) {
    throw new ProtocolError("SESSION_POISONED", session.poisoned);
  }
  return session;
}

async function dispatch(method, params) {
  if (method === "hello") {
    assertObject(params, "params", [], []);
    return {
      protocol_version: PROTOCOL_VERSION,
      bridge_sha256: bridgeSha256,
      node_version: `v${process.versions.node}`,
      showdown_root: showdownRoot,
      allowed_format_ids: [...allowedFormatIds].sort(),
      session_capacity: MAX_SESSIONS,
    };
  }

  if (method === "describe_format") {
    assertObject(params, "params", ["format_id"]);
    const format = assertFormat(params.format_id);
    const ruleTable = Dex.formats.getRuleTable(format);
    return {
      id: format.id,
      name: format.name,
      mod: format.mod,
      game_type: format.gameType || "singles",
      ruleset: [...format.ruleset],
      rule_table: [...ruleTable.keys()].sort(),
      team_constraints: {
        min_team_size: ruleTable.minTeamSize,
        max_team_size: ruleTable.maxTeamSize,
        picked_team_size: ruleTable.pickedTeamSize,
        max_move_count: ruleTable.maxMoveCount,
        min_source_gen: ruleTable.minSourceGen,
        min_level: ruleTable.minLevel,
        max_level: ruleTable.maxLevel,
        default_level: ruleTable.defaultLevel,
        adjust_level: ruleTable.adjustLevel,
        ev_limit: ruleTable.evLimit,
      },
    };
  }

  if (method === "validate_team") {
    assertObject(params, "params", ["format_id", "team"]);
    const format = assertFormat(params.format_id);
    assertTeam(params.team, "team");
    const problems = validateTeam(format.id, params.team);
    return {valid: problems.length === 0, problems};
  }

  if (method === "generate_random_teams") {
    assertObject(
      params,
      "params",
      ["generation_format_id", "target_format_id", "seeds"],
    );
    const generationFormat = assertFormat(params.generation_format_id);
    const targetFormat = assertFormat(params.target_format_id);
    if (
      generationFormat.mod !== targetFormat.mod ||
      (generationFormat.gameType || "singles") !== "singles" ||
      (targetFormat.gameType || "singles") !== "singles"
    ) {
      throw new ProtocolError(
        "FORMAT_INCOMPATIBLE",
        "generation and target formats must use the same singles mod",
      );
    }
    const seeds = assertGenerationSeeds(params.seeds);
    const candidates = seeds.map(seed => {
      const team = normalizeGeneratedTeam(
        Teams.generate(generationFormat.id, {seed}),
      );
      const problems = validateTeam(targetFormat.id, team);
      return {
        generation_seed: seed,
        // TeamValidator mutates its input and restores absent strings as "".
        // Emit a fresh bridge-safe copy after validation.
        team: normalizeGeneratedTeam(team),
        problems,
      };
    });
    return {
      generation_format_id: generationFormat.id,
      target_format_id: targetFormat.id,
      candidates,
    };
  }

  if (method === "create_session") {
    assertObject(params, "params", ["session_id", "format_id", "seed", "players"]);
    const id = assertString(params.session_id, "session_id", 128);
    if (!SESSION_ID.test(id)) throw new ProtocolError("INVALID_REQUEST", "session_id has an invalid format");
    if (sessions.has(id)) throw new ProtocolError("SESSION_EXISTS", `session already exists: ${id}`);
    if (sessions.size >= MAX_SESSIONS) throw new ProtocolError("SESSION_CAPACITY", "session capacity reached");
    const format = assertFormat(params.format_id);
    const seed = assertSeed(params.seed);
    assertObject(params.players, "players", ["p1", "p2"]);
    const packed = {};
    for (const player of ["p1", "p2"]) {
      assertObject(params.players[player], `players.${player}`, ["name", "team"]);
      assertString(params.players[player].name, `players.${player}.name`, 64);
      assertTeam(params.players[player].team, `players.${player}.team`);
      const problems = validateTeam(format.id, params.players[player].team);
      if (problems.length) throw new ProtocolError("TEAM_INVALID", `${player} team is invalid`, {player, problems});
      packed[player] = Teams.pack(params.players[player].team);
    }
    const stream = new BattleStream({noCatch: true, keepAlive: true});
    const session = {
      id,
      formatId: format.id,
      seed,
      stream,
      revision: 0,
      publicLog: [],
      visibleLogs: {p1: [], p2: []},
      requests: {p1: null, p2: null},
      end: null,
      poisoned: null,
    };
    bindOutput(session);
    try {
      await stream.write(`>start ${JSON.stringify({formatid: format.id, seed, strictChoices: true})}`);
      for (const player of ["p1", "p2"]) {
        await stream.write(`>player ${player} ${JSON.stringify({name: params.players[player].name, team: packed[player]})}`);
      }
    } catch (error) {
      try {
        await stream.writeEnd();
      } catch (_closeError) {
        // The original parse/output failure is the authoritative error.
      }
      if (session.poisoned) throw new ProtocolError("SESSION_POISONED", session.poisoned);
      throw error;
    }
    sessions.set(id, session);
    return sessionSummary(session);
  }

  if (method === "observe") {
    assertObject(params, "params", ["session_id", "player", "since"]);
    const session = getSession(params);
    const player = assertString(params.player, "player", 2);
    if (!PLAYER_IDS.has(player)) throw new ProtocolError("INVALID_REQUEST", "player must be p1 or p2");
    return observation(session, player, params.since);
  }

  if (method === "choose" || method === "choose_with_replay_input") {
    assertObject(params, "params", ["session_id", "player", "choice"]);
    const session = getSession(params);
    const player = assertString(params.player, "player", 2);
    if (!PLAYER_IDS.has(player)) throw new ProtocolError("INVALID_REQUEST", "player must be p1 or p2");
    const choice = assertString(params.choice, "choice", 256);
    if (session.stream.battle.ended) throw new ProtocolError("BATTLE_ENDED", "battle already ended");
    const pendingRequest = session.requests[player];
    if (!pendingRequest) {
      throw new ProtocolError("CHOICE_UNAVAILABLE", `${player} has no pending request`);
    }
    const replayInput = method === "choose_with_replay_input" ?
      canonicalChoiceInput(session, player, choice) : null;
    // Consume before writing so a synchronously emitted next request replaces
    // null instead of being erased after the accepted choice returns.
    session.requests[player] = null;
    try {
      await session.stream.write(`>${player} ${choice}`);
    } catch (error) {
      if (session.requests[player] === null) session.requests[player] = pendingRequest;
      if (session.poisoned) throw new ProtocolError("SESSION_POISONED", session.poisoned);
      throw new ProtocolError("CHOICE_REJECTED", error.message);
    }
    session.revision++;
    const summary = sessionSummary(session);
    return method === "choose" ? summary : {summary, replay_input: replayInput};
  }

  if (method === "damage_sample") {
    assertObject(params, "params", ["session_id", "attacker", "move"]);
    const session = getSession(params);
    const attacker = assertString(params.attacker, "attacker", 2);
    if (!PLAYER_IDS.has(attacker)) throw new ProtocolError("INVALID_REQUEST", "attacker must be p1 or p2");
    const move = assertString(params.move, "move", 128);
    const liveBattle = session.stream.battle;
    const liveSeedBefore = liveBattle.prng.getSeed();
    const liveStateBefore = JSON.stringify(liveBattle.toJSON());
    const clone = Battle.fromJSON(liveStateBefore);
    const sourceSide = clone[attacker];
    const targetSide = clone[attacker === "p1" ? "p2" : "p1"];
    const source = sourceSide?.active?.[0];
    const target = targetSide?.active?.[0];
    if (!source || !target) throw new ProtocolError("DAMAGE_UNAVAILABLE", "both active Pokemon are required");
    const moveId = Dex.toID ? Dex.toID(move) : move.toLowerCase().replace(/[^a-z0-9]+/g, "");
    if (!source.moveSlots.some(slot => slot.id === moveId)) {
      throw new ProtocolError("MOVE_UNAVAILABLE", `${source.name} does not know ${move}`);
    }
    let result;
    try {
      const seedBefore = clone.prng.getSeed();
      let activeMove = clone.dex.getActiveMove(moveId);
      const baseTarget = activeMove.target;
      clone.setActiveMove(activeMove, source, target);
      clone.singleEvent("ModifyType", activeMove, null, source, target, activeMove, activeMove);
      clone.singleEvent("ModifyMove", activeMove, null, source, target, activeMove, activeMove);
      activeMove = clone.runEvent("ModifyType", source, target, activeMove, activeMove);
      activeMove = clone.runEvent("ModifyMove", source, target, activeMove, activeMove);
      if (!activeMove) throw new ProtocolError("DAMAGE_UNAVAILABLE", "move modification prevented damage inspection");
      if (activeMove.target !== baseTarget) {
        throw new ProtocolError("DAMAGE_UNAVAILABLE", "move modification changed the target and requires full move execution");
      }
      const damage = clone.actions.getDamage(source, target, activeMove, true);
      const normalizedDamage = typeof damage === "number" ? damage : null;
      const damageStatus = typeof damage === "number" ? "value" : damage === false ? "blocked" : damage === null ? "silent_failure" : "non_damaging";
      result = {
        session_id: session.id,
        revision: session.revision,
        attacker,
        source: source.species.name,
        target: target.species.name,
        move_id: moveId,
        move_type: activeMove.type,
        move_category: activeMove.category,
        damage: normalizedDamage,
        damage_status: damageStatus,
        target_max_hp: target.maxhp,
        target_current_hp: target.hp,
        clone_seed_before: seedBefore,
        clone_seed_after: clone.prng.getSeed(),
        live_seed_before: liveSeedBefore,
        live_seed_after: liveBattle.prng.getSeed(),
      };
    } finally {
      if (JSON.stringify(liveBattle.toJSON()) !== liveStateBefore) {
        session.poisoned = "damage inspection mutated the live battle state";
        throw new ProtocolError("SESSION_POISONED", session.poisoned);
      }
    }
    return result;
  }

  if (method === "export_replay") {
    assertObject(params, "params", ["session_id", "allow_incomplete"]);
    const session = getSession(params);
    if (typeof params.allow_incomplete !== "boolean") {
      throw new ProtocolError("INVALID_REQUEST", "allow_incomplete must be boolean");
    }
    if (!session.stream.battle.ended && !params.allow_incomplete) {
      throw new ProtocolError("REPLAY_INCOMPLETE", "battle must end before Replay export unless explicitly allowed");
    }
    return replayDocument(session);
  }

  if (method === "replay_input_log") {
    assertObject(params, "params", ["input_log"]);
    const inputLog = params.input_log;
    const {format, seed} = validateReplayInputLog(inputLog);
    const stream = new BattleStream({noCatch: true, keepAlive: true});
    const session = {
      id: "replay",
      formatId: format.id,
      seed,
      stream,
      revision: 0,
      publicLog: [],
      visibleLogs: {p1: [], p2: []},
      requests: {p1: null, p2: null},
      end: null,
      poisoned: null,
    };
    bindOutput(session);
    try {
      await stream.write(`>start ${JSON.stringify({formatid: format.id, seed, strictChoices: true})}`);
      for (const line of inputLog.slice(1)) await stream.write(line);
      return replayDocument(session);
    } catch (error) {
      throw new ProtocolError("INVALID_REPLAY", error.message || "Replay execution failed");
    } finally {
      await stream.writeEnd();
    }
  }

  if (method === "resolve_replay_expectations") {
    assertObject(params, "params", ["input_log", "selectors"]);
    const inputLog = params.input_log;
    const selectors = replayExpectationSelectors(params.selectors);
    const {format, seed} = validateReplayInputLog(inputLog);
    const stream = new BattleStream({noCatch: true, keepAlive: true});
    const session = {
      id: "replay-expectations",
      formatId: format.id,
      seed,
      stream,
      revision: 0,
      publicLog: [],
      visibleLogs: {p1: [], p2: []},
      requests: {p1: null, p2: null},
      end: null,
      poisoned: null,
    };
    bindOutput(session);
    const expectations = [];
    try {
      await stream.write(`>start ${JSON.stringify({formatid: format.id, seed, strictChoices: true})}`);
      await stream.write(inputLog[1]);
      await stream.write(inputLog[2]);
      for (let revision = 0; revision < inputLog.length - 3; revision++) {
        const line = inputLog[revision + 3];
        const match = line.match(/^>(p1|p2) (.+)$/);
        const player = match[1];
        const choice = match[2];
        session.revision = revision;
        const selected = selectors.filter(selector => (
          selector.revision === revision && selector.player === player
        ));
        if (selected.length) {
          const snapshot = observation(
            session,
            player,
            0,
          );
          for (const selector of selected) {
            expectations.push({
              selector_id: selector.selector_id,
              value: resolveJsonPointer(snapshot, selector.pointer),
            });
          }
        }
        if (!session.requests[player]) {
          throw new ProtocolError("INVALID_REPLAY", `${player} has no request at revision ${revision}`);
        }
        const canonical = canonicalChoiceInput(session, player, choice);
        if (canonical !== line) {
          throw new ProtocolError("INVALID_REPLAY", `choice is not canonical at revision ${revision}`);
        }
        session.requests[player] = null;
        await stream.write(line);
      }
      session.revision = inputLog.length - 3;
      if (expectations.length !== selectors.length) {
        throw new ProtocolError("EXPECTATION_PATH_MISSING", "one or more selectors did not reach a player decision");
      }
      return {replay: replayDocument(session), expectations};
    } catch (error) {
      if (error instanceof ProtocolError) throw error;
      throw new ProtocolError("INVALID_REPLAY", error.message || "Replay execution failed");
    } finally {
      await stream.writeEnd();
    }
  }

  if (method === "close_session") {
    assertObject(params, "params", ["session_id"]);
    const session = getSession(params, true);
    try {
      await session.stream.writeEnd();
    } finally {
      sessions.delete(session.id);
    }
    return {session_id: session.id, closed: true};
  }

  throw new ProtocolError("UNKNOWN_METHOD", `unknown method: ${method}`);
}

function response(requestId, ok, payload) {
  const envelope = {protocol_version: PROTOCOL_VERSION, request_id: requestId, ok};
  if (ok) envelope.result = payload;
  else envelope.error = payload;
  process.stdout.write(`${JSON.stringify(envelope)}\n`);
}

const input = readline.createInterface({input: process.stdin, crlfDelay: Infinity, terminal: false});
let chain = Promise.resolve();
input.on("line", line => {
  chain = chain.then(async () => {
    let requestId = null;
    try {
      if (Buffer.byteLength(line, "utf8") > MAX_LINE_BYTES) throw new ProtocolError("REQUEST_TOO_LARGE", "request line exceeds 1 MiB");
      const request = parseStrictJson(line);
      assertObject(request, "request", ["protocol_version", "request_id", "method", "params"]);
      requestId = request.request_id;
      if (!Number.isSafeInteger(requestId) || requestId < 0) throw new ProtocolError("INVALID_REQUEST", "request_id must be a non-negative safe integer");
      if (request.protocol_version !== PROTOCOL_VERSION) throw new ProtocolError("PROTOCOL_MISMATCH", `expected protocol ${PROTOCOL_VERSION}`);
      const method = assertString(request.method, "method", 64);
      const result = await dispatch(method, request.params);
      response(requestId, true, result);
    } catch (error) {
      const protocolError = error instanceof ProtocolError ? error : new ProtocolError("INTERNAL_ERROR", error.message || "internal error");
      const payload = {code: protocolError.code, message: protocolError.message};
      if (protocolError.details !== undefined) payload.details = protocolError.details;
      response(requestId, false, payload);
    }
  });
});

input.on("close", () => {
  chain.finally(() => process.exit(0));
});
