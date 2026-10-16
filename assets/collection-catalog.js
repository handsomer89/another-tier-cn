/** Live public character catalog, with an all-or-nothing static fallback. */
export const PUBLIC_CHARACTER_API = 'https://pb.anothertier.com/v1/characters';
const PAID_TIERS = ['New','Best','SSS','SS','S','A','B','C','D','E','F'];
const FREE_TIERS = ['New','SS','S','A','B','C','D','E','Niche','Slave'];
const TIERS = [...PAID_TIERS,'Niche','Slave'];
const ENUMS = {
  armor:['bangle','necklace','ring'],
  elements:['none','fire','earth','wind','water','thunder','shade','crystal'],
  lightShadow:['light','shadow'],
  style:['NS','AS','ES','AC','AC AS'],
  weapon:['staff','sword','katana','ax','lance','bow','fists','hammer'],
  tierBase:[...new Set([...PAID_TIERS,...FREE_TIERS,''])],
};
const STRING_FIELDS = ['alterName','name','slug','styleChangeTome'];
const LIST_FIELDS = ['classTomes','personalities'];
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const plainObject = value => value !== null && typeof value === 'object' && !Array.isArray(value)
  && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
const owns = (value,key) => Object.prototype.hasOwnProperty.call(value,key);
const invalid = message => new Error('角色目录格式不正确：'+message);

// Keep these fields/enums aligned with the original Wt/Gt list schema. A small
// standalone reader avoids loading the original React/PocketBase bundle here.
function parseCharacter(value) {
  if (!plainObject(value)) throw invalid('角色记录必须为对象。');
  for (const key of STRING_FIELDS) if (typeof value[key] !== 'string') throw invalid(key);
  if (!SLUG.test(value.slug) || value.slug.length > 200 || ['constructor','prototype','__proto__'].includes(value.slug)) throw invalid('角色标识。');
  for (const key of LIST_FIELDS) {
    if (!Array.isArray(value[key]) || !value[key].every(item => typeof item === 'string')) throw invalid(key);
  }
  for (const key of ['armor','lightShadow','style','weapon','tierBase']) {
    if (!ENUMS[key].includes(value[key])) throw invalid(key);
  }
  if (typeof value.canSA !== 'boolean') throw invalid('canSA');
  if (owns(value,'tierSA') && !ENUMS.tierBase.includes(value.tierSA)) throw invalid('tierSA');
  if (!Array.isArray(value.elements) || !value.elements.every(item => ENUMS.elements.includes(item))) throw invalid('elements');
  if (!Array.isArray(value.roles) || !value.roles.every(role => plainObject(role)
    && typeof role.name === 'string' && typeof role.slug === 'string')) throw invalid('roles');
  const character = {
    alterName:value.alterName,armor:value.armor,classTomes:[...value.classTomes],elements:[...value.elements],
    lightShadow:value.lightShadow,name:value.name,personalities:[...value.personalities],
    roles:value.roles.map(role => ({name:role.name,slug:role.slug})),slug:value.slug,style:value.style,
    styleChangeTome:value.styleChangeTome,tierBase:value.tierBase,canSA:value.canSA,
  };
  if (owns(value,'tierSA')) character.tierSA=value.tierSA;
  character.weapon=value.weapon;
  return character;
}

export function parseCharacterList(value) {
  if (!Array.isArray(value) || !value.length) throw invalid('角色列表为空。');
  const characters=value.map(parseCharacter), seen=new Map();
  for (const character of characters) {
    const record=canonical(character);
    if (seen.has(character.slug) && seen.get(character.slug) !== record) throw invalid('同一来源的角色记录冲突。');
    seen.set(character.slug,record);
  }
  return characters;
}

// This is the original qt tier placement: paid uses tierSA for canSA forms;
// free always uses tierBase. Sets retain the API's within-tier insertion order.
export function rankCharacters(characters, source) {
  const tierMap = new Map((source === 'free' ? FREE_TIERS : PAID_TIERS).map(tier => [tier,new Set()]));
  for (const character of characters) {
    const tier = source === 'paid' && character.canSA ? character.tierSA ?? '' : character.tierBase;
    tierMap.get(tier)?.add(character.slug);
  }
  return tierMap;
}

function canonical(value) {
  if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if (plainObject(value)) return '{'+Object.keys(value).sort().map(key => JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}';
  return JSON.stringify(value);
}

async function contentVersion(characters) {
  const bytes = new TextEncoder().encode(canonical(characters));
  const digest = await globalThis.crypto.subtle.digest('SHA-256',bytes);
  return 'sha256-'+[...new Uint8Array(digest)].slice(0,8).map(byte => byte.toString(16).padStart(2,'0')).join('');
}

/** Match scripts/generate-collection.py without mutating either public list. */
export async function buildCollectionCatalog(lists) {
  const candidates = [], records = {};
  for (const [sourceIndex,source] of ['paid','free'].entries()) {
    const characters = parseCharacterList(lists?.[source]);
    const bySlug = new Map();
    for (const character of characters) if (!bySlug.has(character.slug)) bySlug.set(character.slug,character);
    records[source]=bySlug;
    const ranked = new Set();
    for (const [tier,slugs] of rankCharacters(characters,source)) {
      let position=0;
      for (const slug of slugs) {
        ranked.add(slug);
        candidates.push({priority:TIERS.indexOf(tier),sourceIndex,position:position++,slug,source});
      }
    }
    for (const slug of [...bySlug.keys()].filter(slug => !ranked.has(slug)).sort()) {
      candidates.push({priority:TIERS.length+1,sourceIndex,position:0,slug,source});
    }
  }
  candidates.sort((a,b) => a.priority-b.priority || a.sourceIndex-b.sourceIndex || a.position-b.position
    || (a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0));
  const seen = new Set(), characters=[];
  for (const {slug,source} of candidates) {
    if (seen.has(slug)) continue;
    seen.add(slug);
    characters.push({...records[source].get(slug),order:characters.length,source});
  }
  return {catalogVersion:await contentVersion(characters),characters};
}

/** Validate the fallback's content as well as its stored fingerprint. */
export async function validateCollectionCatalog(value) {
  if (!plainObject(value) || Object.keys(value).sort().join(',') !== 'catalogVersion,characters'
      || !/^sha256-[0-9a-f]{16}$/.test(value.catalogVersion)) throw invalid('目录版本。');
  const characters = parseCharacterList(value.characters), seen = new Set();
  for (const [index,character] of characters.entries()) {
    const original=value.characters[index];
    if (seen.has(character.slug) || original.order !== index || !['paid','free'].includes(original.source)) throw invalid('角色排序或来源。');
    seen.add(character.slug);
    character.order=index;character.source=original.source;
    if (canonical(character) !== canonical(original)) throw invalid('未识别的角色字段。');
  }
  if (await contentVersion(characters) !== value.catalogVersion) throw invalid('目录内容与版本不一致。');
  return {catalogVersion:value.catalogVersion,characters};
}

async function fetchJSON(url,signal) {
  const response=await fetch(url,{cache:'no-cache',signal});
  if (!response.ok) throw new Error('角色目录请求失败（'+response.status+'）。');
  return response.json();
}
function fetchRemote(paid,signal) {
  const url=new URL(PUBLIC_CHARACTER_API);
  url.searchParams.set('paid',String(paid));
  return fetchJSON(url,signal);
}
function fetchStatic(signal) {
  return fetchJSON(new URL('../data/collection.json',import.meta.url),signal);
}

async function bounded(task,timeoutMs,signal) {
  if (signal?.aborted) throw signal.reason ?? new DOMException('Aborted','AbortError');
  const controller=new AbortController();
  let timer, onAbort;
  const stopped=new Promise((resolve,reject) => {
    const stop=error => {controller.abort(error);reject(error);};
    onAbort=() => stop(signal.reason ?? new DOMException('Aborted','AbortError'));
    signal?.addEventListener('abort',onAbort,{once:true});
    timer=setTimeout(() => stop(new Error('角色目录请求超时。')),timeoutMs);
  });
  try {
    return await Promise.race([Promise.resolve().then(() => task(controller.signal)),stopped]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort',onAbort);
    controller.abort();
  }
}

/** Both endpoints must succeed; never combine one live list with one old list. */
export async function loadCollectionCatalog(options={}) {
  const remote=options.fetchRemote ?? fetchRemote, local=options.fetchStatic ?? fetchStatic;
  const timeoutMs=options.timeoutMs ?? 10000, signal=options.signal;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new TypeError('timeoutMs must be positive');
  let remoteError;
  try {
    const catalog=await bounded(async requestSignal => {
      const [paid,free]=await Promise.all([remote(true,requestSignal),remote(false,requestSignal)]);
      return buildCollectionCatalog({paid,free});
    },timeoutMs,signal);
    return {catalog,source:'remote'};
  } catch (error) {
    if (signal?.aborted) throw signal.reason ?? error;
    remoteError=error;
  }
  try {
    const catalog=await bounded(async requestSignal => validateCollectionCatalog(await local(requestSignal)),timeoutMs,signal);
    return {catalog,source:'static'};
  } catch (error) {
    if (signal?.aborted) throw signal.reason ?? error;
    throw new AggregateError([remoteError,error],'原站及本地角色目录均无法加载。');
  }
}
