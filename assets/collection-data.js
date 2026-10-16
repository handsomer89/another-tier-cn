/** Personal collection data. This module intentionally has no DOM dependencies. */
export const COLLECTION_APP = 'another-tier-cn-collection';
export const COLLECTION_SCHEMA_VERSION = 1;
export const COLLECTION_STORAGE_KEY = 'another-tier-cn:collection:v1';
export const MAX_IMPORT_BYTES = 2 * 1024 * 1024;
export const COLLECTION_STATUSES = Object.freeze(['unowned', 'owned', 'awakened']);

const statusSet = new Set(COLLECTION_STATUSES);
const dangerousKeys = new Set(['__proto__', 'prototype', 'constructor']);
const slugPattern = /^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$/;
const owns = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

export class CollectionDataError extends Error {
  constructor(code, message, cause) {
    super(message);
    this.name = 'CollectionDataError';
    this.code = code;
    if (cause !== undefined) this.cause = cause;
  }
}

function failure(code, message, cause) {
  return new CollectionDataError(code, message, cause);
}

function plainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
}

function validSlug(slug) {
  return typeof slug === 'string' && slugPattern.test(slug) && !dangerousKeys.has(slug);
}

function readCatalog(catalog) {
  if (!plainObject(catalog) || !Array.isArray(catalog.characters)
      || typeof catalog.catalogVersion !== 'string' || !catalog.catalogVersion) {
    throw failure('INVALID_CATALOG', '角色目录格式不正确。');
  }
  const characters = new Map();
  for (const character of catalog.characters) {
    if (!plainObject(character) || !validSlug(character.slug) || characters.has(character.slug)) {
      throw failure('INVALID_CATALOG', '角色目录含有无效或重复的角色标识。');
    }
    characters.set(character.slug, { slug: character.slug, canSA: character.canSA === true });
  }
  return { catalogVersion: catalog.catalogVersion, characters };
}

function cleanCharacters(source) {
  const result = Object.create(null);
  for (const [slug, status] of Object.entries(source)) result[slug] = status;
  return result;
}

function completeCharacters(source, catalog) {
  const result = cleanCharacters(source);
  for (const slug of catalog.characters.keys()) {
    if (!owns(result, slug)) result[slug] = 'unowned';
  }
  return result;
}

function immutableSnapshot(characters, catalogVersion, updatedAt) {
  return Object.freeze({
    app: COLLECTION_APP,
    schemaVersion: COLLECTION_SCHEMA_VERSION,
    catalogVersion,
    updatedAt,
    characters: Object.freeze(cleanCharacters(characters)),
  });
}

function findCatalogCorrections(characters, catalog) {
  const corrections = [];
  for (const [slug, character] of catalog.characters) {
    if (character.canSA !== true && characters[slug] === 'awakened') {
      corrections.push(Object.freeze({ slug, from: 'awakened', to: 'owned' }));
    }
  }
  return Object.freeze(corrections);
}

function normalizeCharacters(source, catalog) {
  const characters = completeCharacters(source, catalog);
  const corrections = findCatalogCorrections(characters, catalog);
  for (const correction of corrections) characters[correction.slug] = correction.to;
  return { characters, corrections };
}

/** Resolve a legal display status without changing a snapshot or its old slugs. */
export function getCharacterStatus(character, snapshotOrCharacters) {
  const characters = snapshotOrCharacters?.characters ?? snapshotOrCharacters ?? {};
  const value = owns(characters, character.slug) ? characters[character.slug] : 'unowned';
  const status = statusSet.has(value) ? value : 'unowned';
  return status === 'awakened' && character.canSA !== true ? 'owned' : status;
}

/** Global statistics always use the complete current catalog. */
export function getCollectionStats(catalog, snapshotOrCharacters) {
  const known = readCatalog(catalog);
  const stats = { total: known.characters.size, owned: 0, awakened: 0, canSA: 0,
    counts: { unowned: 0, owned: 0, awakened: 0 } };
  for (const character of known.characters.values()) {
    const status = getCharacterStatus(character, snapshotOrCharacters);
    stats.counts[status] += 1;
    if (status !== 'unowned') stats.owned += 1;
    if (status === 'awakened') stats.awakened += 1;
    if (character.canSA) stats.canSA += 1;
  }
  return Object.freeze({ ...stats, counts: Object.freeze(stats.counts) });
}

function rejectDangerousKeys(root) {
  // An iterative scan also handles maliciously deep, but otherwise valid, JSON.
  const queue = [root];
  while (queue.length) {
    const value = queue.pop();
    if (value === null || typeof value !== 'object') continue;
    for (const key of Object.keys(value)) {
      if (dangerousKeys.has(key)) throw failure('DANGEROUS_KEY', '数据包含不安全的对象键，已拒绝读取。');
      if (value[key] !== null && typeof value[key] === 'object') queue.push(value[key]);
    }
  }
}

function parseBackup(text) {
  if (typeof text !== 'string') throw failure('INVALID_INPUT', '请选择 UTF-8 JSON 数据文件。');
  if (text.length > MAX_IMPORT_BYTES || new TextEncoder().encode(text).byteLength > MAX_IMPORT_BYTES) {
    throw failure('FILE_TOO_LARGE', '数据文件不能超过 2 MiB。');
  }
  let parsed;
  try {
    parsed = JSON.parse(text.replace(/^\uFEFF/, ''));
  } catch (cause) {
    throw failure('INVALID_JSON', '数据不是有效的 JSON 文件。', cause);
  }
  rejectDangerousKeys(parsed);
  if (!plainObject(parsed) || parsed.app !== COLLECTION_APP) {
    throw failure('INVALID_APP', '这不是本网站的图鉴备份。');
  }
  if (parsed.schemaVersion !== COLLECTION_SCHEMA_VERSION) {
    throw failure('UNSUPPORTED_VERSION', '不支持该数据结构版本，请使用兼容的网站版本。');
  }
  if (typeof parsed.catalogVersion !== 'string' || !parsed.catalogVersion || parsed.catalogVersion.length > 200
      || typeof parsed.updatedAt !== 'string' || parsed.updatedAt.length > 64
      || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/.test(parsed.updatedAt)
      || !Number.isFinite(Date.parse(parsed.updatedAt)) || !plainObject(parsed.characters)) {
    throw failure('INVALID_STRUCTURE', '备份的目录版本、更新时间或角色记录格式不正确。');
  }
  const characters = Object.create(null);
  for (const [slug, status] of Object.entries(parsed.characters)) {
    if (!validSlug(slug)) throw failure('INVALID_SLUG', '备份包含无效的角色标识。');
    if (!statusSet.has(status)) throw failure('INVALID_STATUS', `角色 ${slug} 的状态不合法。`);
    characters[slug] = status;
  }
  return { ...parsed, characters };
}

function prepareParsed(parsed, catalog) {
  const { characters, corrections } = normalizeCharacters(parsed.characters, catalog);
  const counts = { unowned: 0, owned: 0, awakened: 0 };
  let importedKnownCount = 0;
  let unknownCount = 0;
  for (const slug of Object.keys(parsed.characters)) {
    if (catalog.characters.has(slug)) importedKnownCount += 1;
    else unknownCount += 1;
  }
  for (const slug of catalog.characters.keys()) counts[characters[slug]] += 1;
  return Object.freeze({
    snapshot: immutableSnapshot(characters, catalog.catalogVersion, parsed.updatedAt),
    sourceCatalogVersion: parsed.catalogVersion,
    corrections,
    summary: Object.freeze({
      knownCount: catalog.characters.size,
      importedKnownCount,
      unknownCount,
      recordCount: Object.keys(parsed.characters).length,
      counts: Object.freeze(counts),
    }),
  });
}

/** Read-only backup parsing and preview. No storage or application state is changed. */
export function validateCollectionBackup(text, catalog) {
  return prepareParsed(parseBackup(text), readCatalog(catalog));
}

/**
 * Create a local collection store. Passing null deliberately disables storage;
 * omitting storage resolves globalThis.localStorage inside a guarded read.
 * Mutations return {ok,error?}; failed writes never update the active snapshot.
 */
export function createCollectionStore(catalog, suppliedStorage) {
  const known = readCatalog(catalog);
  const previews = new WeakMap();
  let storage;
  let storageError = null;
  try {
    storage = suppliedStorage === undefined ? globalThis.localStorage : suppliedStorage;
    if (!storage || typeof storage.getItem !== 'function' || typeof storage.setItem !== 'function') {
      throw new Error('localStorage is unavailable');
    }
  } catch (cause) {
    storageError = failure('STORAGE_UNAVAILABLE', '当前浏览器无法使用本地保存；你仍可导出可恢复的数据。', cause);
  }
  let snapshot = immutableSnapshot(completeCharacters({}, known), known.catalogVersion, new Date().toISOString());
  // Never let a caller skip reading a possibly existing record and overwrite it.
  let blocked = true;
  let recoverableRaw = null;
  let pendingCorrections = Object.freeze([]);

  function result(ok, details = {}) {
    return { ok, snapshot, blocked, corrections: pendingCorrections, ...details };
  }

  function persist(candidate) {
    if (storageError) return storageError;
    try {
      storage.setItem(COLLECTION_STORAGE_KEY, JSON.stringify(candidate));
      return null;
    } catch (cause) {
      return failure('SAVE_FAILED', '本地保存失败，原记录未被替换。请检查浏览器存储空间或权限，并导出备份。', cause);
    }
  }

  function readStoredRaw() {
    if (storageError) throw storageError;
    try {
      return storage.getItem(COLLECTION_STORAGE_KEY);
    } catch (cause) {
      throw failure('READ_FAILED', '无法读取本地记录；为保护原数据，已暂停保存。你仍可导出当前可恢复的数据。', cause);
    }
  }

  function rejectRaw(raw, error) {
    blocked = true;
    recoverableRaw = raw;
    return result(false, { error, warning: '浏览器中的图鉴记录无法读取，已保留原始内容。请导出可恢复的数据，或通过确认导入恢复。' });
  }

  function preservedStatusWarning() {
    return pendingCorrections.length
      ? '部分角色的星导状态不适用于当前目录，页面按“拥有”显示；原始星导记录已保留，以兼容更新的角色目录。'
      : undefined;
  }

  function adoptRaw(raw) {
    if (raw === null) {
      snapshot = immutableSnapshot(completeCharacters({}, known), known.catalogVersion, new Date().toISOString());
      blocked = false;
      recoverableRaw = null;
      pendingCorrections = Object.freeze([]);
      return result(true);
    }
    let parsed;
    try {
      parsed = parseBackup(raw);
    } catch (error) {
      return rejectRaw(raw, error);
    }
    // An older tab may not know that a newer catalog has enabled awakening.
    // Resolve display through getCharacterStatus; only a confirmed import repairs records.
    snapshot = immutableSnapshot(completeCharacters(parsed.characters, known), known.catalogVersion, parsed.updatedAt);
    blocked = false;
    recoverableRaw = raw;
    pendingCorrections = findCatalogCorrections(snapshot.characters, known);
    return result(true, { warning: preservedStatusWarning() });
  }

  const store = {
    load() {
      let raw;
      try {
        raw = readStoredRaw();
      } catch (error) {
        blocked = true;
        return result(false, { error });
      }
      return adoptRaw(raw);
    },

    getStatus(slug) {
      const character = known.characters.get(slug);
      return character ? getCharacterStatus(character, snapshot) : (snapshot.characters[slug] ?? 'unowned');
    },

    getStats() {
      return getCollectionStats(catalog, snapshot);
    },

    exportSnapshot() {
      return immutableSnapshot(completeCharacters(snapshot.characters, known), known.catalogVersion, snapshot.updatedAt);
    },

    getRecoverableRaw() {
      return recoverableRaw;
    },

    setStatus(slug, status) {
      const character = known.characters.get(slug);
      if (!character || !statusSet.has(status) || (status === 'awakened' && !character.canSA)) {
        return result(false, { error: failure('INVALID_STATUS', '该角色不能使用所选状态。') });
      }
      if (blocked) return result(false, { error: failure('PROTECTED_RECORD', '原记录尚未安全读取，已阻止覆盖。请先导出备份，或使用“导入数据”确认恢复。') });
      let raw;
      try {
        raw = readStoredRaw();
      } catch (error) {
        blocked = true;
        return result(false, { error });
      }
      let latestCharacters;
      try {
        latestCharacters = raw === null ? {} : parseBackup(raw).characters;
      } catch (error) {
        return rejectRaw(raw, error);
      }
      // Rebase on the latest stored record even when storage events have not run.
      // This prevents stale sequential edits; localStorage itself has no atomic CAS.
      const characters = completeCharacters(latestCharacters, known);
      characters[slug] = status;
      const candidate = immutableSnapshot(characters, known.catalogVersion, new Date().toISOString());
      const error = persist(candidate);
      if (error) return result(false, { error });
      snapshot = candidate;
      recoverableRaw = JSON.stringify(snapshot);
      pendingCorrections = findCatalogCorrections(snapshot.characters, known);
      return result(true, { warning: preservedStatusWarning() });
    },

    prepareImport(text) {
      const preview = prepareParsed(parseBackup(text), known);
      previews.set(preview, preview.snapshot);
      return preview;
    },

    commitImport(preview) {
      if (!preview || !previews.has(preview)) {
        return result(false, { error: failure('INVALID_PREVIEW', '请先选择并预览有效的备份文件。') });
      }
      const prepared = previews.get(preview);
      const candidate = immutableSnapshot(prepared.characters, known.catalogVersion, new Date().toISOString());
      const error = persist(candidate);
      if (error) return result(false, { error });
      snapshot = candidate;
      blocked = false;
      recoverableRaw = JSON.stringify(snapshot);
      pendingCorrections = preview.corrections;
      previews.delete(preview);
      return result(true);
    },

    /** Feed storage-event newValue here, including null when the key is removed. */
    acceptExternal(raw) {
      return adoptRaw(raw);
    },
  };
  return Object.freeze(store);
}
