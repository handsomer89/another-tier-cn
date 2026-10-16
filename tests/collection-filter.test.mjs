import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

// Load the actual browser modules, including their translation dependencies,
// without adding a package.json or changing the static site's module setup.
const moduleURLs = new Map();
async function browserModuleURL(url) {
  const key = url.href;
  if (moduleURLs.has(key)) return moduleURLs.get(key);
  const result = (async () => {
    let source = await readFile(url, 'utf8');
    const imports = [...source.matchAll(/\bfrom\s*(['"])(\.[^'"]+)\1/g)];
    for (const match of imports) {
      const dependency = await browserModuleURL(new URL(match[2], url));
      source = source.replace(match[0], `from ${JSON.stringify(dependency)}`);
    }
    return `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
  })();
  moduleURLs.set(key, result);
  return result;
}
async function browserModule(path) {
  return import(await browserModuleURL(new URL(path, import.meta.url)));
}

const [filtersModule, aliasesModule, verifiedModule, catalog] = await Promise.all([
  browserModule('../assets/collection-filter.js'),
  browserModule('../assets/cn-aliases.js'),
  browserModule('../assets/cn-verified.js'),
  readFile(new URL('../data/collection.json', import.meta.url), 'utf8').then(JSON.parse),
]);
const {
  normalize, displayName, emptyFilters, matchesCharacter,
  filterOptions, readPublicFilters, publicFilterSearch,
} = filtersModule;
const { translateAlias } = aliasesModule;
const { translateVerified } = verifiedModule;
const characters = catalog.characters;
assert.ok(characters.length > 0, 'the generated catalog must contain actual characters');
const query = (character, keyword) => matchesCharacter(character, { ...emptyFilters(), keyword }, 'unowned');
const books = character => [character.styleChangeTome, ...(character.classTomes ?? [])].filter(Boolean);
const valuesOf = (list, dimension) => {
  if (dimension === 'roles') return list.flatMap(character => character.roles.map(role => role.slug));
  if (dimension === 'weapons') return list.map(character => character.weapon);
  return list.flatMap(character => character[dimension]);
};
const dimensions = ['elements', 'weapons', 'roles', 'personalities'];

test('search accepts current Chinese and English names, including case-insensitive substrings', () => {
  const translated = characters.find(character => displayName(character) !== character.name && /[\u3400-\u9fff]/u.test(displayName(character)));
  assert.ok(translated, 'select a character with an existing Chinese translation');
  assert.ok(query(translated, displayName(translated)));
  assert.ok(query(translated, translated.name.toUpperCase()));
  assert.ok(query(translated, translated.name.slice(1, -1).toLowerCase()));
  assert.equal(query(translated, '__no_character_has_this_search_text__'), false);
});

test('search includes verified AC aliases in Chinese and English', () => {
  const character = characters.find(character => character.alterName
    && translateAlias(character.alterName) !== character.alterName);
  assert.ok(character, 'select a real AC form with a verified alias');
  assert.ok(query(character, character.alterName.toUpperCase()));
  assert.ok(query(character, translateAlias(character.alterName)));
});

test('search includes class and style-change books with verified Chinese translations', () => {
  for (const field of ['classTomes', 'styleChangeTome']) {
    const character = characters.find(character => {
      const candidates = field === 'classTomes' ? character.classTomes : [character.styleChangeTome];
      return candidates.some(book => book && translateVerified('materials', book, character.name) !== book);
    });
    assert.ok(character, `select an existing translated ${field} book`);
    const candidates = field === 'classTomes' ? character.classTomes : [character.styleChangeTome];
    const book = candidates.find(book => book && translateVerified('materials', book, character.name) !== book);
    assert.ok(query(character, book.toUpperCase()), `${field}: English book`);
    assert.ok(query(character, translateVerified('materials', book, character.name)), `${field}: Chinese book`);
  }
});

test('search preserves the original NFD and accent-removal behavior on actual books', () => {
  const character = characters.find(character => books(character).some(book => book.normalize('NFD') !== book));
  assert.ok(character, 'select a real book containing a decomposable accent');
  const book = books(character).find(book => book.normalize('NFD') !== book);
  const unaccented = book.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();
  assert.ok(query(character, book.normalize('NFD')));
  assert.ok(query(character, unaccented));
  assert.equal(normalize(book), normalize(unaccented));
  // The old list normalizes accents and case; it does not trim or tokenize.
  assert.equal(normalize(` ${book} `), ` ${normalize(book)} `);
});

test('different dimensions are ANDed while elements and weapons are ORed within a dimension', () => {
  const character = characters.find(character => character.elements.length && character.weapon
    && character.roles.length && character.personalities.length);
  assert.ok(character);
  const otherElement = valuesOf(characters, 'elements').find(value => !character.elements.includes(value));
  const otherWeapon = valuesOf(characters, 'weapons').find(value => value !== character.weapon);
  assert.ok(otherElement && otherWeapon, 'select real alternative attribute values');
  const selected = { ...emptyFilters(), elements: [otherElement, character.elements[0]],
    weapons: [otherWeapon, character.weapon], roles: [character.roles[0].slug],
    personalities: [character.personalities[0]], keyword: character.name.toUpperCase() };
  assert.ok(matchesCharacter(character, selected, 'unowned'));
  assert.equal(matchesCharacter(character, { ...selected, elements: [otherElement] }, 'unowned'), false);
  assert.equal(matchesCharacter(character, { ...selected, weapons: [otherWeapon] }, 'unowned'), false);
  assert.equal(matchesCharacter(character, { ...selected, keyword: '__unmatched_name__' }, 'unowned'), false);
});

for (const dimension of ['roles', 'personalities']) {
  test(`${dimension} supports both all and any, including nonmatching selections`, () => {
    const character = characters.find(character => new Set(valuesOf([character], dimension)).size >= 2);
    assert.ok(character, `select a real character with at least two ${dimension}`);
    const present = [...new Set(valuesOf([character], dimension))];
    const missing = valuesOf(characters, dimension).find(value => !present.includes(value));
    assert.ok(missing, `select an existing ${dimension} value absent from the character`);
    const mode = `${dimension}Match`;
    const bothPresent = { ...emptyFilters(), [dimension]: present.slice(0, 2), [mode]: 'all' };
    assert.ok(matchesCharacter(character, bothPresent, 'unowned'));
    const mixed = { ...bothPresent, [dimension]: [present[0], missing] };
    assert.equal(matchesCharacter(character, mixed, 'unowned'), false);
    assert.ok(matchesCharacter(character, { ...mixed, [mode]: 'any' }, 'unowned'));
    assert.equal(matchesCharacter(character, { ...mixed, [dimension]: [missing], [mode]: 'any' }, 'unowned'), false);
    assert.ok(matchesCharacter(character, { ...mixed, [dimension]: [], [mode]: 'any' }, 'unowned'));
  });
}

test('ownership filters offer all, owned including awakened, and unowned', () => {
  const available = characters.find(character => character.canSA === true);
  const unavailable = characters.find(character => character.canSA === false);
  assert.ok(available && unavailable, 'select current eligible and ineligible forms');
  const owned = { ...emptyFilters(), status: 'owned' };
  assert.ok(matchesCharacter(available, owned, 'owned'));
  assert.ok(matchesCharacter(available, owned, 'awakened'));
  assert.ok(matchesCharacter(unavailable, owned, 'owned'));
  assert.equal(matchesCharacter(available, owned, 'unowned'), false);
  const unowned = { ...emptyFilters(), status: 'unowned' };
  assert.ok(matchesCharacter(available, unowned, 'unowned'));
  assert.equal(matchesCharacter(available, unowned, 'owned'), false);
  assert.equal(matchesCharacter(available, unowned, 'awakened'), false);
  for (const status of ['unowned', 'owned', 'awakened']) {
    assert.ok(matchesCharacter(available, emptyFilters(), status));
  }
});

test('filtering retains the generated cross-list order and does not mutate catalog data', () => {
  const before = JSON.stringify(characters);
  const first = characters.find(character => character.elements.length);
  const filtered = characters.filter(character => matchesCharacter(character,
    { ...emptyFilters(), elements: [first.elements[0]] }, 'owned'));
  assert.ok(filtered.length > 1 && filtered.length < characters.length);
  const positions = new Map(characters.map((character, index) => [character.slug, index]));
  for (let i = 1; i < filtered.length; i += 1) {
    assert.ok(positions.get(filtered[i - 1].slug) < positions.get(filtered[i].slug));
  }
  filterOptions(characters);
  assert.equal(JSON.stringify(characters), before);
});

test('filter options equal the full paid/free union and contain free-only values', () => {
  const paid = characters.filter(character => character.source === 'paid');
  const free = characters.filter(character => character.source === 'free');
  assert.ok(paid.length && free.length, 'the generated catalog includes both original lists');
  const options = filterOptions(characters);
  let freeOnlyCount = 0;
  for (const dimension of dimensions) {
    const expected = [...new Set(valuesOf(characters, dimension).filter(Boolean))].sort();
    assert.deepEqual(options[dimension].map(option => option.value).sort(), expected, dimension);
    const paidValues = new Set(valuesOf(paid, dimension));
    const freeOnly = [...new Set(valuesOf(free, dimension))].filter(value => !paidValues.has(value));
    for (const value of freeOnly) {
      freeOnlyCount += 1;
      assert.ok(options[dimension].some(option => option.value === value), `${dimension}: ${value}`);
      const matches = characters.filter(character => matchesCharacter(character,
        { ...emptyFilters(), [dimension]: [value] }, 'unowned'));
      assert.ok(matches.length > 0);
      assert.ok(matches.every(character => character.source === 'free'));
    }
  }
  assert.ok(freeOnlyCount > 0, 'the fixture must exercise actual free-only options');
});

test('URL serialization roundtrips public filters and excludes personal ownership data', () => {
  const sample = characters.find(character => character.roles.length && character.personalities.length);
  const selected = { ...emptyFilters(), keyword: displayName(sample), elements: sample.elements,
    weapons: [sample.weapon], roles: [sample.roles[0].slug], personalities: [sample.personalities[0]],
    rolesMatch: 'any', personalitiesMatch: 'any', status: 'owned',
    characters: { [sample.slug]: 'owned' }, personalRecords: { [sample.slug]: 'awakened' } };
  const encoded = publicFilterSearch(selected);
  const params = new URLSearchParams(encoded);
  const publicKeys = ['keyword', ...dimensions, 'rolesMatch', 'personalitiesMatch'];
  assert.ok([...params.keys()].every(key => publicKeys.includes(key)));
  for (const key of ['status', 'characters', 'personalRecords']) assert.equal(params.has(key), false);
  const decoded = readPublicFilters(encoded);
  for (const key of publicKeys) assert.deepEqual(decoded[key], selected[key], key);
  assert.equal(decoded.status, 'all');
  const injected = readPublicFilters(`${encoded}&status=awakened&characters=%7B%7D`);
  assert.deepEqual(injected, decoded);
  assert.equal(publicFilterSearch(emptyFilters()), '');
});

test('malformed public URL arrays cannot inject non-string filter values', () => {
  const parsed = readPublicFilters('?elements=%7B%22fire%22%3Atrue%7D&roles=%5B1%5D&personalitiesMatch=invalid');
  assert.deepEqual(parsed.elements, []);
  assert.deepEqual(parsed.roles, []);
  assert.equal(parsed.personalitiesMatch, 'all');
});
