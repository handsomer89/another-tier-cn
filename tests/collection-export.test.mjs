import test from "node:test";
import assert from "node:assert/strict";

// The site is plain ES modules without a package.json or build step.
const { calculateLayout, getCellPosition, imageFilename, exportCollectionImage, clearExportImageCache } = await import(
  new URL("../assets/collection-export.js", import.meta.url)
);

test("current catalog uses the preferred 9:16 canvas and the largest possible portraits", () => {
  const layout = calculateLayout(322);
  assert.equal(layout.width, 1800);
  assert.equal(layout.height, 3200);
  assert.ok(layout.avatarSize >= 96);
  for (let columns = 1; columns <= 322; columns += 1) {
    const rows = Math.ceil(322 / columns);
    const width = columns * (layout.avatarSize + 1) + (columns - 1) * layout.gap;
    const height = rows * (layout.avatarSize + 1) + (rows - 1) * layout.gap;
    assert.ok(width > layout.width - 2 * layout.padding ||
      height > layout.height - 2 * layout.padding - layout.headerHeight - layout.footerHeight,
    `a larger portrait would fit in ${columns} columns`);
  }
});

for (const count of [1, 14, 321, 322, 323, 500, 1000]) {
  test(`all ${count} portraits fit once, and the final row is centered`, () => {
    const layout = calculateLayout(count);
    const occupied = new Set();
    for (let index = 0; index < count; index += 1) {
      const { x, y } = getCellPosition(index, count, layout);
      assert.ok(x >= layout.padding);
      assert.ok(x + layout.avatarSize <= layout.width - layout.padding);
      assert.ok(y >= layout.padding + layout.headerHeight);
      assert.ok(y + layout.avatarSize <= layout.footerTop);
      assert.ok(!occupied.has(`${x},${y}`));
      occupied.add(`${x},${y}`);
    }
    const lastRowStart = (layout.rows - 1) * layout.columns;
    const left = getCellPosition(lastRowStart, count, layout).x;
    const right = getCellPosition(count - 1, count, layout).x + layout.avatarSize;
    assert.ok(Math.abs(left - (layout.width - right)) <= 1);
    assert.ok(layout.avatarSize >= 96);
    assert.ok(Math.abs(layout.width / layout.height - 9 / 16) < 0.001);
  });
}

test("growing catalogs raise resolution rather than shrinking portraits", () => {
  const layout = calculateLayout(1000);
  assert.ok(layout.width > 1800);
  assert.ok(layout.height > 3200);
  assert.ok(layout.avatarSize >= 96);
});

test("invalid counts and cell positions fail explicitly", () => {
  for (const count of [0, -1, 1.5, NaN, Infinity]) assert.throws(() => calculateLayout(count), RangeError);
  const layout = calculateLayout(322);
  for (const index of [-1, 322, 0.5]) assert.throws(() => getCellPosition(index, 322, layout), RangeError);
});

test("the PNG filename uses the local generation timestamp", () => {
  assert.equal(imageFilename(new Date(2026, 9, 16, 9, 5, 3)), "another-tier-个人图鉴-20261016-090503.png");
});

test("canceling a stalled image export rejects promptly without canceling shared image loading", async t => {
  const realSetTimeout = globalThis.setTimeout;
  const realClearTimeout = globalThis.clearTimeout;
  const OriginalImage = globalThis.Image;
  const pendingImages = [];
  let deadline;
  // Leave image loading stalled forever unless this test explicitly reports failure.
  globalThis.Image = class {
    constructor() { this.sources = []; pendingImages.push(this); }
    set src(value) { this.sources.push(value); }
  };
  t.mock.timers.enable({ apis: ["setTimeout"] });
  clearExportImageCache();
  try {
    const controller = new AbortController();
    const exportTask = exportCollectionImage({
      characters: [{ slug: "aldo", name: "Aldo", canSA: false }],
      signal: controller.signal,
    });
    assert.equal(pendingImages.length, 1);
    controller.abort();
    await Promise.race([
      assert.rejects(exportTask, error => error.name === "AbortError"),
      new Promise((resolve, reject) => {
        deadline = realSetTimeout(() => reject(new Error("Cancellation waited for the image timeout")), 500);
      }),
    ]);
    // The canceled consumer must leave the cached source intact for other consumers.
    assert.equal(pendingImages[0].sources.length, 1);
    assert.equal(typeof pendingImages[0].onerror, "function");
    // Fail the background local source and its CDN fallback after export has canceled.
    // An unhandled rejection here causes node:test to fail.
    pendingImages[0].onerror();
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
    assert.equal(pendingImages.length, 2);
    pendingImages[1].onerror();
    await new Promise(resolve => realSetTimeout(resolve, 0));
  } finally {
    realClearTimeout(deadline);
    clearExportImageCache();
    t.mock.timers.reset();
    if (OriginalImage === undefined) delete globalThis.Image;
    else globalThis.Image = OriginalImage;
  }
});
