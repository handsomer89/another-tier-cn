import test from "node:test";
import assert from "node:assert/strict";

// The site is plain ES modules without a package.json or build step.
const { calculateLayout, getCellPosition, imageFilename, imageSources, rememberCollectionImage, exportCollectionImage, clearExportImageCache } = await import(
  new URL("../assets/collection-export.js", import.meta.url)
);

const characters = Object.freeze([
  Object.freeze({ slug: "aldo", name: "Aldo", canSA: false }),
  Object.freeze({ slug: "alma-as", name: "Alma AS", canSA: true }),
  Object.freeze({ slug: "ewan", name: "Ewan", canSA: true }),
  Object.freeze({ slug: "amy", name: "Amy", canSA: false }),
]);
const statuses = Object.freeze({ aldo: "owned", "alma-as": "awakened", ewan: "unowned" });

for (const [statusFilter, expected] of [
  [undefined, ["aldo", "alma-as", "ewan", "amy", "__stellar__"]],
  ["all", ["aldo", "alma-as", "ewan", "amy", "__stellar__"]],
  ["owned", ["aldo", "alma-as", "__stellar__"]],
  ["unowned", ["ewan", "amy", "__stellar__"]],
]) {
  test(`${statusFilter ?? "default"} export loads only that tab's portraits in catalog order`, async () => {
    const OriginalImage = globalThis.Image;
    // Fail every source so error.missing exposes the actual resources requested,
    // without a browser canvas or depending on network access.
    globalThis.Image = class {
      set src(value) { if (value) queueMicrotask(() => this.onerror?.()); }
    };
    clearExportImageCache();
    const before = JSON.stringify({ characters, statuses });
    try {
      await assert.rejects(exportCollectionImage({ characters, statuses, statusFilter }), error => {
        assert.equal(error.name, "ExportImageError");
        assert.deepEqual(error.missing.map(item => item.slug), expected);
        return true;
      });
      assert.equal(JSON.stringify({ characters, statuses }), before);
    } finally {
      clearExportImageCache();
      if (OriginalImage === undefined) delete globalThis.Image;
      else globalThis.Image = OriginalImage;
    }
  });
}

test("empty ownership ranges fail before requesting images", async () => {
  await assert.rejects(exportCollectionImage({ characters, statusFilter: "owned" }), /没有已拥有的角色/);
  await assert.rejects(exportCollectionImage({
    characters, statuses: Object.fromEntries(characters.map(character => [character.slug, "owned"])), statusFilter: "unowned",
  }), /没有未拥有的角色/);
});

test("invalid export scopes fail explicitly", async () => {
  await assert.rejects(exportCollectionImage({ characters, statusFilter: "awakened" }), RangeError);
});

for (const scenario of ["loaded page image", "CDN failure", "unsafe page image", "unloaded page image"]) {
  test(`export resource reuse and CDN priority: ${scenario}`, async () => {
    const originalImage = globalThis.Image, originalDocument = globalThis.document;
    const requests = [], probed = [];
    const [cdn, mirror] = imageSources("aldo");
    const displayed = {src: cdn, complete: scenario !== "unloaded page image", naturalWidth: 80, naturalHeight: 80};
    const stop = new Error("resources ready; do not render in this unit test");
    globalThis.document = {createElement: () => ({getContext: () => {
      let current;
      return {
        drawImage(image) {current = image;probed.push(image);},
        getImageData() {
          if (scenario === "unsafe page image" && current === displayed) throw new Error("Canvas is tainted");
          return {data: new Uint8ClampedArray(4)};
        },
      };
    }})};
    globalThis.Image = class {
      naturalWidth = 80;
      naturalHeight = 80;
      set src(value) {
        if (!value) return;
        assert.equal(this.crossOrigin, "anonymous");
        requests.push(value);
        queueMicrotask(() => {
          if (scenario === "CDN failure" && value === cdn) this.onerror?.();
          else this.onload?.();
        });
      }
    };
    clearExportImageCache();
    try {
      if (scenario !== "CDN failure") rememberCollectionImage("aldo", displayed);
      const prepare = () => exportCollectionImage({
        characters: [characters[0]],
        onProgress(progress) {if (progress.phase === "loading" && progress.completed === progress.total) throw stop;},
      });
      await assert.rejects(prepare(), error => error === stop);
      if (scenario === "loaded page image") {
        assert.deepEqual(requests, []);
        assert.deepEqual(probed, [displayed]);
      } else {
        assert.deepEqual(requests, scenario === "CDN failure" ? [cdn, mirror] : [cdn]);
      }
      const previousRequests = [...requests];
      await assert.rejects(prepare(), error => error === stop);
      assert.deepEqual(requests, previousRequests, "a second export must reuse the resolved resource");
      assert.equal(displayed.src, cdn, "export must not change a page image's source");
    } finally {
      clearExportImageCache();
      if (originalImage === undefined) delete globalThis.Image;else globalThis.Image = originalImage;
      if (originalDocument === undefined) delete globalThis.document;else globalThis.document = originalDocument;
    }
  });
}

test("current catalog uses the preferred 9:21 canvas and the largest possible portraits", () => {
  const layout = calculateLayout(322);
  assert.equal(layout.width, 1800);
  assert.equal(layout.height, 4200);
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
    assert.ok(Math.abs(layout.width / layout.height - 9 / 21) < 0.001);
  });
}

test("growing catalogs raise resolution rather than shrinking portraits", () => {
  const layout = calculateLayout(1000);
  assert.ok(layout.width > 1800);
  assert.ok(layout.height > 4200);
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
    // Fail the background CDN source and its mirror fallback after export has canceled.
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
