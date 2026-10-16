import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../image-cache-sw.js', import.meta.url), 'utf8');
const root = 'https://mirror.example/another-tier-cn/';
const image = version => root + 'mirror-images/portrait.webp?v=' + version;

function worker({failStorage = false, failPut = false, status = 200, type = 'image/webp'} = {}) {
  const handlers = {}, stored = new Map(), requests = [];
  const cache = {
    async match(request) { return stored.get(request.url)?.clone(); },
    async put(request, response) { if (failPut) throw new Error('quota'); stored.set(request.url, response); },
    async keys() { return [...stored.keys()].map(url => new Request(url)); },
    async delete(request) { return stored.delete(request.url); },
  };
  vm.runInNewContext(source, {
    URL, Map,
    self: {registration: {scope: root}, addEventListener: (name, handler) => {handlers[name] = handler;}},
    caches: {async open() { if (failStorage) throw new Error('storage disabled'); return cache; }},
    fetch: async request => {requests.push(request.url); return new Response('pixels', {status, headers: {'Content-Type': type}});},
  });
  return {stored, requests, read(url, method = 'GET') {
    let response;
    handlers.fetch({request: new Request(url, {method}), respondWith: value => {response = value;}});
    return response;
  }};
}

test('repeat and concurrent page/export requests share a persistent snapshot', async () => {
  const w = worker(), url = image('111111111111');
  const [first, second] = await Promise.all([w.read(url), w.read(url)]);
  assert.equal(await first.text(), 'pixels');
  assert.equal(await second.text(), 'pixels');
  assert.equal(await (await w.read(url)).text(), 'pixels');
  assert.deepEqual(w.requests, [url]);
});

test('a new content version fetches fresh pixels and removes the older version', async () => {
  const w = worker(), first = image('111111111111'), second = image('222222222222');
  await w.read(first); await w.read(second);
  assert.deepEqual(w.requests, [first, second]);
  assert.deepEqual([...w.stored.keys()], [second]);
});

for (const options of [{status:404}, {type:'text/html'}, {failStorage:true}, {failPut:true}]) {
  test(`unsuccessful responses or unavailable storage never poison the cache: ${JSON.stringify(options)}`, async () => {
    const w = worker(options), url = image('111111111111');
    assert.equal((await w.read(url)).status, options.status || 200);
    await w.read(url);
    assert.equal(w.requests.length, 2);
    assert.equal(w.stored.size, 0);
  });
}

test('API data, pages, scripts, other sites and unversioned images remain outside the image cache', () => {
  const w = worker();
  for (const url of [root, root+'data/collection.json', root+'assets/collection.js',
    root+'mirror-images/portrait.webp', root+'mirror-images/portrait.webp?v=bad',
    'https://pb.anothertier.com/v1/characters?paid=true',
    'https://other.example/another-tier-cn/mirror-images/portrait.webp?v=111111111111']) {
    assert.equal(w.read(url), undefined, url);
  }
  assert.equal(w.read(image('111111111111'), 'POST'), undefined);
  assert.deepEqual(w.requests, []);
});

test('image cache stays bounded as the catalog grows', async () => {
  const w = worker();
  for (let index=0; index<1202; index++) {
    await w.read(root+`mirror-images/${index}.webp?v=111111111111`);
  }
  assert.equal(w.stored.size, 1200);
  assert.ok(!w.stored.has(root+'mirror-images/0.webp?v=111111111111'));
});
