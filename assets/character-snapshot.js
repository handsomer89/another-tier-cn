// Keep the original API authoritative; static snapshots support outages.
export async function readCharacterSnapshot(file, loadRemote, parse) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(loadRemote).then(parse),
      new Promise((_, reject) => {timer = setTimeout(() => reject(new Error('原站数据请求超时')), 10000);}),
    ]);
  } catch (remoteError) {
    clearTimeout(timer);
    try {
      const response = await fetch(new URL(`../data/characters/${encodeURIComponent(file)}.json`, import.meta.url), {cache: 'no-cache'});
      if (response.ok) return parse(await response.json());
    } catch { /* Preserve the original API error when both sources fail. */ }
    throw remoteError;
  } finally {
    clearTimeout(timer);
  }
}
