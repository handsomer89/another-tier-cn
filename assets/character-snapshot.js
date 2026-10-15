// Match the mirrored pages even when the original public API is unavailable.
// If a snapshot is missing, retain access to characters added upstream later.
export async function readCharacterSnapshot(file, loadRemote, parse) {
  try {
    const response = await fetch(new URL(`../data/characters/${encodeURIComponent(file)}.json`, import.meta.url));
    if (response.ok) return parse(await response.json());
  } catch {}
  return parse(await loadRemote());
}
