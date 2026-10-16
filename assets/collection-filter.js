import {cnNames} from './cn-names.js?v=aadc6b4789a0';
import {translateAlias} from './cn-aliases.js?v=419f47e10abd';
import {translateVerified} from './cn-verified.js?v=1da74c9ef4dd';
import {cnTerms} from './cn-terms.js?v=5c106893cf4a';

export const normalize = value => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
export const displayName = character => cnNames[character.name] ?? character.name;
export function term(group, value) {
  const key = Object.keys(cnTerms[group] ?? {}).find(key => normalize(key) === normalize(value));
  return cnTerms[group]?.[key] ?? (group === 'personalities' ? translateVerified(group, value) : value);
}
export function searchText(character) {
  const books = [character.styleChangeTome, ...(character.classTomes ?? [])].filter(Boolean);
  return [character.name, displayName(character), character.alterName, translateAlias(character.alterName),
    ...books, ...books.map(book => translateVerified('materials', book, character.name))].map(normalize);
}
export function emptyFilters() {
  return {keyword:'',elements:[],weapons:[],roles:[],personalities:[],rolesMatch:'all',personalitiesMatch:'all',status:'all'};
}
export function matchesCharacter(character, filters, status) {
  const keyword = normalize(filters.keyword);
  const match = (selected, values, mode = 'any') => !selected.length || selected[mode === 'all' ? 'every' : 'some'](value => values.includes(value));
  return (!keyword || searchText(character).some(value => value.includes(keyword)))
    && match(filters.elements, character.elements ?? [])
    && match(filters.weapons, [character.weapon])
    && match(filters.roles, (character.roles ?? []).map(role => role.slug), filters.rolesMatch)
    && match(filters.personalities, character.personalities ?? [], filters.personalitiesMatch)
    && (filters.status === 'all'
      || (filters.status === 'owned' && (status === 'owned' || status === 'awakened'))
      || (filters.status === 'unowned' && status === 'unowned'));
}
export function filterOptions(characters) {
  const roles = new Map();
  for (const character of characters) for (const role of character.roles ?? []) roles.set(role.slug, role.name);
  const options = (key, values) => [...new Set(values)].filter(Boolean).map(value => ({value,label:term(key,value)})).sort((a,b) => a.label.localeCompare(b.label,'zh-CN'));
  return {
    elements:options('elements',characters.flatMap(c => c.elements ?? [])),
    weapons:options('weapons',characters.map(c => c.weapon)),
    roles:[...roles].map(([value,name]) => ({value,label:term('roles',name)})).sort((a,b) => a.label.localeCompare(b.label,'zh-CN')),
    personalities:options('personalities',characters.flatMap(c => c.personalities ?? []))
  };
}
export function readPublicFilters(search) {
  const params = new URLSearchParams(search), result = emptyFilters();
  result.keyword = params.get('keyword') ?? '';
  for (const key of ['elements','weapons','roles','personalities']) {
    const raw = params.get(key);
    if (!raw) continue;
    try { const parsed = JSON.parse(raw); if (Array.isArray(parsed) && parsed.every(x => typeof x === 'string')) result[key] = parsed; }
    catch { result[key] = raw.split(',').filter(Boolean); }
  }
  for (const key of ['rolesMatch','personalitiesMatch']) if (params.get(key) === 'any') result[key] = 'any';
  return result;
}
export function publicFilterSearch(filters) {
  const params = new URLSearchParams();
  if (filters.keyword) params.set('keyword',filters.keyword);
  for (const key of ['elements','weapons','roles','personalities']) if (filters[key].length) params.set(key,JSON.stringify(filters[key]));
  for (const key of ['rolesMatch','personalitiesMatch']) if (filters[key] === 'any') params.set(key,'any');
  return params.toString();
}
