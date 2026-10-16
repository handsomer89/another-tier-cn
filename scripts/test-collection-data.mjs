#!/usr/bin/env node
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

// The static website has no package.json; import this browser module as ESM.
const moduleText = await readFile(new URL('../assets/collection-data.js', import.meta.url), 'utf8');
const {
  createCollectionStore, validateCollectionBackup, getCharacterStatus,
  COLLECTION_APP, COLLECTION_STORAGE_KEY, MAX_IMPORT_BYTES,
} = await import(`data:text/javascript;base64,${Buffer.from(moduleText).toString('base64')}`);

const catalog = { catalogVersion: '2026-10-test', characters: [
  { slug: 'aldo', canSA: true }, { slug: 'suzette', canSA: true }, { slug: 'suzette-as', canSA: false },
] };
function backup(characters = {}, fields = {}) {
  return JSON.stringify({ app: COLLECTION_APP, schemaVersion: 1, catalogVersion: 'older-catalog',
    updatedAt: '2026-10-15T12:00:00.000Z', characters, ...fields });
}
function memoryStorage(raw = null) {
  return { raw, writes: 0, failRead: false, failWrite: false,
    getItem(key) { assert.equal(key, COLLECTION_STORAGE_KEY); if (this.failRead) throw Error('read denied'); return this.raw; },
    setItem(key, value) { assert.equal(key, COLLECTION_STORAGE_KEY); if (this.failWrite) throw Error('quota'); this.raw = value; this.writes += 1; },
  };
}
function rejectsBackup(raw, code) {
  assert.throws(() => validateCollectionBackup(raw, catalog), error => error.code === code);
}

// First visit, full snapshot export, persistent mutations, independent forms.
const storage = memoryStorage();
const store = createCollectionStore(catalog, storage);
assert.equal(store.setStatus('aldo', 'owned').error.code, 'PROTECTED_RECORD');
assert.equal(storage.writes, 0);
assert.equal(store.load().ok, true);
assert.equal(storage.writes, 0);
assert.deepEqual({ ...store.exportSnapshot().characters }, { aldo: 'unowned', suzette: 'unowned', 'suzette-as': 'unowned' });
assert.equal(store.setStatus('suzette', 'awakened').ok, true);
assert.equal(store.setStatus('suzette-as', 'awakened').ok, false);
assert.equal(store.setStatus('suzette-as', 'owned').ok, true);
assert.equal(store.getStatus('suzette'), 'awakened');
assert.equal(store.getStats().owned, 2);
assert.equal(store.getStats().awakened, 1);
assert.equal(store.getStats().canSA, 2);
const reloaded = createCollectionStore(catalog, storage);
assert.equal(reloaded.load().ok, true);
assert.equal(reloaded.getStatus('suzette'), 'awakened');

// Preview is read-only; replacement resets omitted current forms and keeps old slugs.
const beforePreview = storage.raw;
const preview = store.prepareImport(backup({ aldo: 'owned', 'suzette-as': 'awakened', 'future-form': 'awakened' }));
assert.equal(storage.raw, beforePreview);
assert.equal(store.getStatus('suzette'), 'awakened');
assert.equal(preview.summary.knownCount, 3);
assert.equal(preview.summary.importedKnownCount, 2);
assert.equal(preview.summary.unknownCount, 1);
assert.equal(preview.corrections.length, 1);
assert.deepEqual(preview.summary.counts, { unowned: 1, owned: 2, awakened: 0 });
assert.equal(store.commitImport({ ...preview }).ok, false);
storage.failWrite = true;
assert.equal(store.commitImport(preview).ok, false);
assert.equal(store.getStatus('suzette'), 'awakened');
assert.equal(storage.raw, beforePreview);
storage.failWrite = false;
assert.equal(store.commitImport(preview).ok, true);
assert.equal(store.getStatus('suzette'), 'unowned');
assert.equal(store.getStatus('suzette-as'), 'owned');
assert.equal(store.exportSnapshot().characters['future-form'], 'awakened');
assert.equal(store.commitImport(preview).ok, false);

// Malformed, incompatible and dangerous data never reaches an active store.
rejectsBackup('{broken', 'INVALID_JSON');
rejectsBackup(backup({}, { schemaVersion: 2 }), 'UNSUPPORTED_VERSION');
rejectsBackup(backup({}, { app: 'unrelated-app' }), 'INVALID_APP');
rejectsBackup(backup({ aldo: true }), 'INVALID_STATUS');
rejectsBackup(backup({ 'not a slug': 'owned' }), 'INVALID_SLUG');
rejectsBackup(backup({}, { updatedAt: 'yesterday' }), 'INVALID_STRUCTURE');
rejectsBackup(backup({}, { characters: [] }), 'INVALID_STRUCTURE');
rejectsBackup(backup({}) .replace('"characters":{}', '"characters":{"__proto__":"owned"}'), 'DANGEROUS_KEY');
rejectsBackup(backup({}, { metadata: { nested: { constructor: 'bad' } } }), 'DANGEROUS_KEY');
rejectsBackup(backup({}) + ' '.repeat(MAX_IMPORT_BYTES), 'FILE_TOO_LARGE');
rejectsBackup(backup({}, { metadata: '中'.repeat(Math.ceil(MAX_IMPORT_BYTES / 3)) }), 'FILE_TOO_LARGE');
assert.equal(Object.prototype.polluted, undefined);
assert.equal(validateCollectionBackup('\uFEFF' + backup(), catalog).summary.knownCount, 3);

// Broken and unreadable records are protected until an explicit valid import.
const damagedStorage = memoryStorage('{corrupted');
const damaged = createCollectionStore(catalog, damagedStorage);
assert.equal(damaged.load().ok, false);
assert.equal(damaged.getRecoverableRaw(), '{corrupted');
assert.equal(damaged.setStatus('aldo', 'owned').error.code, 'PROTECTED_RECORD');
assert.equal(damagedStorage.raw, '{corrupted');
assert.equal(damagedStorage.writes, 0);
assert.equal(damaged.commitImport(damaged.prepareImport(backup({ aldo: 'owned' }))).ok, true);
assert.equal(damaged.getStatus('aldo'), 'owned');
damagedStorage.failRead = true;
assert.equal(damaged.load().error.code, 'READ_FAILED');
assert.equal(damaged.getStatus('aldo'), 'owned');
assert.equal(damaged.setStatus('aldo', 'unowned').ok, false);

// Failed ordinary writes preserve the last usable snapshot and export.
storage.failWrite = true;
const beforeWrite = store.exportSnapshot();
assert.equal(store.setStatus('aldo', 'unowned').error.code, 'SAVE_FAILED');
assert.deepEqual(store.exportSnapshot(), beforeWrite);
storage.failWrite = false;

// Catalog growth and temporary removals preserve ownership by stable slug.
const newCatalog = { catalogVersion: 'new', characters: [...catalog.characters, { slug: 'new-form', canSA: true }] };
const upgraded = createCollectionStore(newCatalog, storage);
assert.equal(upgraded.load().ok, true);
assert.equal(upgraded.getStatus('new-form'), 'unowned');
assert.equal(upgraded.getStatus('aldo'), 'owned');
assert.equal(upgraded.exportSnapshot().characters['future-form'], 'awakened');
const removed = createCollectionStore({ catalogVersion: 'trimmed', characters: [] }, storage);
assert.equal(removed.load().ok, true);
assert.equal(removed.exportSnapshot().characters.aldo, 'owned');

// Stale tabs preserve sequential edits even before any storage event is delivered.
const sharedStorage = memoryStorage(backup({ 'older-form': 'awakened' }));
const firstTab = createCollectionStore(catalog, sharedStorage);
const secondTab = createCollectionStore(catalog, sharedStorage);
assert.equal(firstTab.load().ok, true);
assert.equal(secondTab.load().ok, true);
assert.equal(firstTab.setStatus('aldo', 'owned').ok, true);
assert.equal(secondTab.getStatus('aldo'), 'unowned'); // No event or reload yet.
assert.equal(secondTab.setStatus('suzette', 'awakened').ok, true);
assert.equal(firstTab.setStatus('suzette-as', 'owned').ok, true);
assert.deepEqual(JSON.parse(sharedStorage.raw).characters, {
  'older-form': 'awakened', aldo: 'owned', suzette: 'awakened', 'suzette-as': 'owned',
});
assert.equal(sharedStorage.writes, 3);

// A newer tab can enable awakening while an older catalog is still open.
const awakeningCatalog = { catalogVersion: 'new-awakening', characters: catalog.characters.map(
  character => ({ ...character, canSA: true }),
) };
const awakeningStorage = memoryStorage();
const olderTab = createCollectionStore(catalog, awakeningStorage);
const newerTab = createCollectionStore(awakeningCatalog, awakeningStorage);
assert.equal(olderTab.load().ok, true);
assert.equal(newerTab.load().ok, true);
assert.equal(newerTab.setStatus('suzette-as', 'awakened').ok, true);
const newerRaw = awakeningStorage.raw;
const olderLoad = olderTab.load();
assert.equal(olderLoad.ok, true);
assert.match(olderLoad.warning, /原始星导记录已保留/);
assert.equal(olderLoad.corrections.length, 1);
assert.equal(awakeningStorage.raw, newerRaw);
assert.equal(awakeningStorage.writes, 1); // Loading must never repair storage.
assert.equal(olderTab.getStatus('suzette-as'), 'owned');
assert.equal(olderTab.exportSnapshot().characters['suzette-as'], 'awakened');
assert.equal(getCharacterStatus(catalog.characters[2], olderTab.exportSnapshot()), 'owned');
assert.equal(olderTab.acceptExternal(newerRaw).ok, true);
assert.equal(awakeningStorage.writes, 1); // External records are also read-only.
assert.equal(olderTab.setStatus('aldo', 'owned').ok, true);
assert.equal(JSON.parse(awakeningStorage.raw).characters['suzette-as'], 'awakened');
assert.equal(newerTab.load().ok, true);
assert.equal(newerTab.getStatus('suzette-as'), 'awakened');
assert.equal(newerTab.getStatus('aldo'), 'owned');

// Explicit imports still preview and apply catalog corrections on confirmation.
const beforeCorrectionImport = awakeningStorage.raw;
const correctionPreview = olderTab.prepareImport(beforeCorrectionImport);
assert.equal(correctionPreview.corrections.length, 1);
assert.equal(awakeningStorage.raw, beforeCorrectionImport);
assert.equal(olderTab.commitImport(correctionPreview).ok, true);
assert.equal(JSON.parse(awakeningStorage.raw).characters['suzette-as'], 'owned');

// A newly corrupted or unreadable stored record cannot be overwritten by a stale tab.
const changedStorage = memoryStorage(backup({ aldo: 'owned' }));
const changedStore = createCollectionStore(catalog, changedStorage);
assert.equal(changedStore.load().ok, true);
const lastGoodSnapshot = changedStore.exportSnapshot();
changedStorage.raw = '{new corruption';
assert.equal(changedStore.setStatus('suzette', 'owned').error.code, 'INVALID_JSON');
assert.deepEqual(changedStore.exportSnapshot(), lastGoodSnapshot);
assert.equal(changedStore.getRecoverableRaw(), '{new corruption');
assert.equal(changedStorage.raw, '{new corruption');
assert.equal(changedStorage.writes, 0);
changedStorage.raw = backup({ aldo: 'owned' });
assert.equal(changedStore.setStatus('suzette', 'owned').error.code, 'PROTECTED_RECORD');
assert.equal(changedStore.load().ok, true);
changedStorage.failRead = true;
assert.equal(changedStore.setStatus('suzette', 'owned').error.code, 'READ_FAILED');
assert.deepEqual(changedStore.exportSnapshot(), lastGoodSnapshot);
assert.equal(changedStorage.writes, 0);
changedStorage.failRead = false;
assert.equal(changedStore.load().ok, true);

// A failed write after rebasing keeps the active snapshot and latest storage unchanged.
changedStorage.raw = backup({ suzette: 'awakened', 'future-form': 'owned' });
changedStorage.failWrite = true;
const beforeRebasedWrite = changedStorage.raw;
assert.equal(changedStore.setStatus('aldo', 'owned').error.code, 'SAVE_FAILED');
assert.deepEqual(changedStore.exportSnapshot(), lastGoodSnapshot);
assert.equal(changedStorage.raw, beforeRebasedWrite);
changedStorage.failWrite = false;
assert.equal(changedStore.setStatus('aldo', 'owned').ok, true);
assert.equal(changedStore.exportSnapshot().characters['future-form'], 'owned');
assert.equal(changedStore.getStatus('suzette'), 'awakened');

// A removed storage key is authoritative; do not resurrect a stale snapshot.
changedStorage.raw = null;
assert.equal(changedStore.setStatus('suzette-as', 'owned').ok, true);
assert.deepEqual(JSON.parse(changedStorage.raw).characters, {
  aldo: 'unowned', suzette: 'unowned', 'suzette-as': 'owned',
});

// Cross-tab snapshots replace state; invalid external data cannot overwrite it.
assert.equal(store.acceptExternal(backup({ suzette: 'awakened', 'older-form': 'owned' })).ok, true);
assert.equal(store.getStatus('aldo'), 'unowned');
assert.equal(store.getStatus('suzette'), 'awakened');
assert.equal(store.exportSnapshot().characters['older-form'], 'owned');
assert.equal(store.acceptExternal('{broken').ok, false);
assert.equal(store.getStatus('suzette'), 'awakened');
assert.equal(store.setStatus('aldo', 'owned').ok, false);
assert.equal(store.acceptExternal(null).ok, true);
assert.equal(store.getStats().owned, 0);

// Accessing the default storage getter is itself guarded (private mode / policies).
const oldDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
try {
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw Error('blocked getter'); } });
  const unavailable = createCollectionStore(catalog);
  assert.equal(unavailable.load().error.code, 'STORAGE_UNAVAILABLE');
  assert.equal(Object.keys(unavailable.exportSnapshot().characters).length, 3);
  assert.equal(unavailable.commitImport(unavailable.prepareImport(backup())).ok, false);
} finally {
  if (oldDescriptor) Object.defineProperty(globalThis, 'localStorage', oldDescriptor);
  else delete globalThis.localStorage;
}
console.log('Collection data checks passed: persistence, safe imports, migration, recovery, and storage synchronization.');
