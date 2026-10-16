/** Form families use the public slug/style pair, never translated names. */
const suffixes = {AS:'-as',ES:'-es',AC:'-ac','AC AS':'-ac-as'};
const styles = ['NS','AS','ES','AC','AC AS'];

function familySlug(character) {
  const suffix = suffixes[character.style];
  return suffix && character.slug.endsWith(suffix)
    ? character.slug.slice(0,-suffix.length) : character.slug;
}

export function otherForms(characters, selected) {
  const family = familySlug(selected);
  return characters.filter(character => character.slug !== selected.slug && familySlug(character) === family)
    .sort((a,b) => styles.indexOf(a.style) - styles.indexOf(b.style));
}
