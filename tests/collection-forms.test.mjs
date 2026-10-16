import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../assets/collection-forms.js',import.meta.url),'utf8');
const {otherForms} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const {characters} = JSON.parse(await readFile(new URL('../data/collection.json',import.meta.url),'utf8'));
const slugs = forms => forms.map(form => form.slug);

test('all five styles are related, including the compound AC AS suffix, without mutating the catalog',() => {
  const before = JSON.stringify(characters);
  const expected = ['tsukiha','tsukiha-as','tsukiha-es','tsukiha-ac','tsukiha-ac-as'];
  for (const slug of expected) {
    const selected = characters.find(character => character.slug === slug);
    assert.deepEqual(slugs(otherForms(characters,selected)),expected.filter(value => value !== slug));
  }
  assert.equal(JSON.stringify(characters),before);
});

test('the complete catalog has symmetric families with no self links or duplicate forms',() => {
  for (const selected of characters) {
    const forms = otherForms(characters,selected);
    assert.equal(new Set(slugs(forms)).size,forms.length);
    assert.ok(!forms.includes(selected));
    for (const form of forms) assert.ok(otherForms(characters,form).includes(selected));
  }
});

test('single-form characters have no other forms',() => {
  const aisha = characters.find(character => character.slug === 'aisha');
  assert.deepEqual(otherForms(characters,aisha),[]);
});

test('new untranslated forms work without an NS record and preserve full hyphenated identities',() => {
  const forms = [
    {slug:'new-hero-ac-as',style:'AC AS',name:'Same translated name'},
    {slug:'new-hero-as',style:'AS',name:'Different name'},
    {slug:'new-hero-ac',style:'AC',name:'Alter identity'},
    {slug:'another-hero-as',style:'AS',name:'Same translated name'},
  ];
  assert.deepEqual(slugs(otherForms(forms,forms[0])),['new-hero-as','new-hero-ac']);
});

test('only a suffix matching the declared style is removed',() => {
  const forms = [
    {slug:'hero-as',style:'NS'},
    {slug:'hero-as-es',style:'ES'},
    {slug:'hero',style:'NS'},
    {slug:'hero-ac',style:'AS'},
  ];
  assert.deepEqual(slugs(otherForms(forms,forms[0])),['hero-as-es']);
  assert.deepEqual(otherForms(forms,forms[2]),[]);
});
