import test from 'node:test';
import assert from 'node:assert/strict';
import {imageSourcesForURL, setImageSource, mirrorImageRuntime, installImageFallback} from '../assets/image-fallback.js';

const CDN = 'https://res.cloudinary.com/ryanditjia/image/upload/';
const original = CDN + 'dpr_2.0/c_lfill,h_80,w_80/q_auto:low/f_auto/v1/another-eden/characters/aldo/portrait';

test('saved snapshots take priority; new API characters and unrelated images still load', () => {
  const [local, remote] = imageSourcesForURL(original);
  assert.match(local, /mirror-images\/dpr_2.0\/c_lfill_h_80_w_80\/q_auto_low\/.*\.webp\?v=[0-9a-f]{12}$/);
  assert.equal(remote, original);
  const added = original.replace('/aldo/', '/new-unmirrored-character/');
  assert.deepEqual(imageSourcesForURL(added), [added]);
  assert.deepEqual(imageSourcesForURL('https://other.example/photo.jpg'), ['https://other.example/photo.jpg']);
});

class FakeImage {
  attributes = new Map();
  complete = true;
  naturalWidth = 0;
  setAttribute(key, value) {this.attributes.set(key, value);}
  getAttribute(key) {return this.attributes.get(key);}
  removeAttribute(key) {this.attributes.delete(key);}
}

test('static and dynamic image failures fall back once, then stop', () => {
  const oldImage=globalThis.HTMLImageElement, oldDocument=globalThis.document;
  globalThis.HTMLImageElement=FakeImage;
  const early=new FakeImage();setImageSource(early,original);
  let handler, removed;
  globalThis.document={images:[early], addEventListener:(name,fn)=>{handler=fn;}, removeEventListener:(name,fn)=>{removed=fn;}};
  try {
    const cleanup=installImageFallback();
    assert.equal(early.src,original,'failure before hydration also falls back');
    const late=new FakeImage();setImageSource(late,original);
    handler({target:late});assert.equal(late.src,original);
    handler({target:late});assert.equal(late.src,original,'no reverse fallback loop');
    handler({target:{}});
    cleanup();assert.equal(handler,removed);
  } finally {
    if(oldImage===undefined)delete globalThis.HTMLImageElement;else globalThis.HTMLImageElement=oldImage;
    if(oldDocument===undefined)delete globalThis.document;else globalThis.document=oldDocument;
  }
});

test('React props are converted before creation and preserve existing error handlers and keys', () => {
  const raw=(...args)=>args;
  const runtime=mirrorImageRuntime({jsx:raw,jsxs:raw});
  const input={src:original,alt:'Aldo',onError:()=>{}};
  const [type,props,key]=runtime.jsx('img',input,'aldo');
  assert.equal(type,'img');assert.equal(key,'aldo');
  assert.equal(props.src,imageSourcesForURL(original)[0]);
  assert.equal(props['data-original-src'],original);
  assert.equal(props.alt,'Aldo');assert.notEqual(props.onError,input.onError);
  assert.equal(input.src,original,'caller props remain unchanged');
  assert.equal(runtime.jsxs('div',input)[1],input,'other elements remain unchanged');
});
