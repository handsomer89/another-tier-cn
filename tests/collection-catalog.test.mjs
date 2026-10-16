import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const moduleURL=new URL('../assets/collection-catalog.js',import.meta.url);
const moduleSource=await readFile(moduleURL,'utf8');
const {buildCollectionCatalog,validateCollectionCatalog,loadCollectionCatalog,parseCharacterList,rankCharacters,PUBLIC_CHARACTER_API}
  =await import('data:text/javascript;base64,'+Buffer.from(moduleSource.replaceAll('import.meta.url',JSON.stringify(moduleURL.href))).toString('base64'));
const [paid,free,staticCatalog,bundle]=await Promise.all([
  readFile(new URL('../data/characters/paid.json',import.meta.url),'utf8').then(JSON.parse),
  readFile(new URL('../data/characters/free.json',import.meta.url),'utf8').then(JSON.parse),
  readFile(new URL('../data/collection.json',import.meta.url),'utf8').then(JSON.parse),
  readFile(new URL('../assets/character-BWOG_BU2.js',import.meta.url),'utf8'),
]);
const copy=value => structuredClone(value);
const character=(slug,fields={}) => ({...copy(paid[0]),slug,name:slug,canSA:false,tierBase:'S',tierSA:'',...fields});
const lists=() => ({paid:[character('paid')],free:[character('free')]});
const snapshot=await buildCollectionCatalog(lists());
const failure=() => Promise.reject(new Error('offline'));

test('live catalog matches the Python-generated complete catalog and fingerprint',async () => {
  const input={paid:copy(paid),free:copy(free)}, before=copy(input);
  assert.deepEqual(await buildCollectionCatalog(input),staticCatalog);
  assert.deepEqual(input,before,'the original API lists remain unchanged');
  assert.deepEqual(await validateCollectionCatalog(staticCatalog),staticCatalog);
});

test('tier placement matches the actual original qt implementation',() => {
  const match=bundle.match(/function qt\(e,t\)\{[\s\S]*?(?=var Jt=)/);
  assert.ok(match,'the original ranking helper must be available for comparison');
  const paidTiers=['New','Best','SSS','SS','S','A','B','C','D','E','F'];
  const freeTiers=['New','SS','S','A','B','C','D','E','Niche','Slave'];
  const original=Function('Pt','Ft','return ('+match[0]+')')(paidTiers,freeTiers);
  for (const [source,records] of Object.entries({paid,free})) {
    assert.deepEqual([...rankCharacters(records,source)],[...original(records,source).tierMap]);
  }
  const unusual=[character('has-no-sa-tier',{canSA:true}),character('paid-slave',{tierBase:'Slave'}),character('ordinary')];
  for (const source of ['paid','free']) assert.deepEqual([...rankCharacters(unusual,source)],[...original(unusual,source).tierMap]);
});

test('unified tiers take priority over source, and preserve original within-tier order',async () => {
  const catalog=await buildCollectionCatalog({
    paid:[character('paid-a',{tierBase:'A'}),character('paid-s-two'),character('paid-s-one')],
    free:[character('free-a',{tierBase:'A'}),character('free-s')],
  });
  assert.deepEqual(catalog.characters.map(item => item.slug),['paid-s-two','paid-s-one','free-s','paid-a','free-a']);
  assert.deepEqual(catalog.characters.map(item => item.order),[0,1,2,3,4]);
});

test('duplicates retain the earliest unified position and its source record',async () => {
  const catalog=await buildCollectionCatalog({
    paid:[character('shared',{tierBase:'A'}),character('paid')],
    free:[character('shared',{canSA:true,tierBase:'S',name:'Free fields'}),character('free')],
  });
  assert.deepEqual(catalog.characters.map(item => item.slug),['paid','shared','free']);
  assert.equal(catalog.characters[1].source,'free');
  assert.equal(catalog.characters[1].canSA,true);
  assert.equal(catalog.characters[1].name,'Free fields');
});

test('all forms survive missing applicable tiers; unranked forms sort last by slug',async () => {
  const catalog=await buildCollectionCatalog({
    paid:[character('z-no-tier',{canSA:true}),character('a-no-tier',{canSA:true}),character('ranked')],
    free:[character('free-slave',{tierBase:'Slave'})],
  });
  assert.deepEqual(catalog.characters.map(item => item.slug),['ranked','free-slave','a-no-tier','z-no-tier']);
});

test('conflicting duplicate records in one endpoint reject the entire live pair',async () => {
  const result=await loadCollectionCatalog({
    fetchRemote:async isPaid => isPaid ? [character('repeated'),character('repeated',{tierBase:'SS'})] : [character('free')],
    fetchStatic:async () => snapshot,
  });
  assert.equal(result.source,'static');
  assert.deepEqual(result.catalog,snapshot);
  assert.equal((await buildCollectionCatalog({paid:[character('repeated'),character('repeated')],free:[character('free')]})).characters.length,2);
});

test('strict API schema rejects invalid fields and normalizes harmless extra fields',() => {
  for (const change of [
    {slug:'../unsafe'}, {slug:'constructor'}, {slug:'prototype'}, {slug:'a'.repeat(201)},
    {canSA:'true'}, {name:null}, {armor:'future-armor'},
    {tierBase:'Future'}, {tierSA:undefined}, {elements:['unknown']}, {classTomes:[{}]},
    {roles:[{name:'DPS'}]}, {personalities:'Staff'}, {weapon:'other'},
  ]) assert.throws(() => parseCharacterList([character('one',change)]));
  for (const value of [[],{},null,[null]]) assert.throws(() => parseCharacterList(value));
  const parsed=parseCharacterList([character('one',{futureField:'ignored',roles:[{name:'DPS',slug:'dps',future:true}]})]);
  assert.equal(parsed[0].futureField,undefined);
  assert.deepEqual(parsed[0].roles,[{name:'DPS',slug:'dps'}]);
  const optional=character('two');delete optional.tierSA;
  assert.equal(Object.hasOwn(parseCharacterList([optional])[0],'tierSA'),false);
});

test('content changes produce stable new versions without editing source records',async () => {
  const input=lists(), original=await buildCollectionCatalog(input);
  const reorderedKeys={paid:input.paid.map(item => Object.fromEntries(Object.entries(item).reverse())),free:input.free};
  assert.deepEqual(await buildCollectionCatalog(reorderedKeys),original);
  input.paid[0].canSA=true;input.paid[0].tierSA='S';
  const enabled=await buildCollectionCatalog(input);
  assert.notEqual(enabled.catalogVersion,original.catalogVersion);
  input.free.push(character('new-form'));
  const added=await buildCollectionCatalog(input);
  assert.notEqual(added.catalogVersion,enabled.catalogVersion);
  assert.equal(added.characters.length,3);
});

test('both live endpoints succeed before the static catalog is used',async () => {
  const requested=[];
  const result=await loadCollectionCatalog({
    fetchRemote:async (isPaid,signal) => {requested.push(isPaid);assert.equal(signal.aborted,false);return isPaid ? paid : free;},
    fetchStatic:() => assert.fail('a valid live pair must not fetch the fallback'),
  });
  assert.deepEqual(requested,[true,false]);
  assert.equal(result.source,'remote');
  assert.deepEqual(result.catalog,staticCatalog);
});

test('one failed endpoint falls back as a complete batch and aborts remaining work',async () => {
  let pendingSignal;
  const result=await loadCollectionCatalog({
    fetchRemote:(isPaid,signal) => {
      if (isPaid) return failure();
      pendingSignal=signal;return new Promise(() => {});
    },
    fetchStatic:async () => snapshot,
  });
  assert.equal(result.source,'static');
  assert.deepEqual(result.catalog,snapshot);
  assert.equal(pendingSignal.aborted,true);
});

test('one invalid or empty endpoint cannot be mixed with a fresh valid endpoint',async () => {
  for (const invalid of [[],[{slug:'incomplete'}]]) {
    const result=await loadCollectionCatalog({
      fetchRemote:async isPaid => isPaid ? [character('live-only')] : invalid,
      fetchStatic:async () => snapshot,
    });
    assert.equal(result.source,'static');
    assert.deepEqual(result.catalog,snapshot);
    assert.equal(result.catalog.characters.some(item => item.slug==='live-only'),false);
  }
});

test('a live timeout falls back even when an injected request ignores abort',async () => {
  const signals=[];
  const result=await loadCollectionCatalog({
    fetchRemote:async (isPaid,signal) => {signals.push(signal);return new Promise(() => {});},
    fetchStatic:async () => snapshot,timeoutMs:15,
  });
  assert.equal(result.source,'static');
  assert.ok(signals.every(signal => signal.aborted));
});

test('static fallback rejects tampering, duplicate slugs, invalid fields and wrong metadata',async () => {
  for (const mutate of [
    value => {value.catalogVersion='sha256-0000000000000000';},
    value => {value.characters[0].canSA='yes';},
    value => {value.characters[1].slug=value.characters[0].slug;},
    value => {value.characters[0].order=5;},
    value => {value.characters[0].source='other';},
    value => {value.characters[0].extra='unexpected';},
    value => {value.extra=true;},
  ]) {
    const broken=copy(snapshot);mutate(broken);
    await assert.rejects(validateCollectionCatalog(broken));
    await assert.rejects(loadCollectionCatalog({fetchRemote:failure,fetchStatic:async () => broken}),AggregateError);
  }
});

test('failure of both sources reports a recoverable load failure',async () => {
  await assert.rejects(loadCollectionCatalog({fetchRemote:failure,fetchStatic:failure}),error => {
    assert.ok(error instanceof AggregateError);
    assert.equal(error.errors.length,2);
    return true;
  });
});

test('explicit cancellation aborts live work without starting a fallback',async () => {
  const controller=new AbortController();let requestSignal;
  const loading=loadCollectionCatalog({
    signal:controller.signal,
    fetchRemote:async (isPaid,signal) => {requestSignal=signal;return new Promise(() => {});},
    fetchStatic:() => assert.fail('a cancelled load must stay cancelled'),
  });
  await Promise.resolve();controller.abort();
  await assert.rejects(loading,error => error.name==='AbortError');
  assert.equal(requestSignal.aborted,true);
});

test('default public API requests use the original endpoint, paid flags and cache revalidation',async () => {
  const originalFetch=globalThis.fetch, requested=[];
  globalThis.fetch=async (url,options) => {
    requested.push({url:new URL(url),options});
    return {ok:true,json:async () => new URL(url).searchParams.get('paid')==='true' ? paid : free};
  };
  try {
    assert.equal((await loadCollectionCatalog()).source,'remote');
  } finally {globalThis.fetch=originalFetch;}
  assert.equal(requested.length,2);
  assert.deepEqual(requested.map(({url}) => url.searchParams.get('paid')),['true','false']);
  for (const {url,options} of requested) {
    assert.equal(url.origin+url.pathname,PUBLIC_CHARACTER_API);
    assert.equal(options.cache,'no-cache');
    assert.ok(options.signal instanceof AbortSignal);
  }
});
