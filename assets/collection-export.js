import { getCharacterStatus } from "./collection-data.js";

// Standalone image export: never read the filtered DOM or mutable personal records.
const CDN = "https://res.cloudinary.com/ryanditjia/image/upload/";
const PORTRAIT_PATH = "dpr_2.0/c_lfill,h_80,w_80/q_auto:low/f_auto/v1/another-eden/characters/";
const STAR_PATH = "dpr_2.0/c_limit,h_24,w_24/q_auto:low/f_auto/v1/another-eden/sa";
const imageCache = new Map();
const MAX_CACHED_IMAGES = 512;
const IMAGE_TIMEOUT = 20000;
const FONT = '"Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';

export class ExportImageError extends Error {
  constructor(missing) {
    const names = missing.map(item => `${item.name}（${item.slug}）`).join("、");
    super(`图片加载失败，尚未生成图鉴。请检查网络后重试。缺失图片：${names}`);
    this.name = "ExportImageError";
    this.missing = missing;
  }
}

function measureLayout(count, width, height, scale) {
  const padding = Math.round(72 * scale);
  const headerHeight = Math.round(200 * scale);
  const footerHeight = Math.round(180 * scale);
  const gap = Math.max(1, Math.round(14 * scale));
  const availableWidth = width - padding * 2;
  const availableHeight = height - padding * 2 - headerHeight - footerHeight;
  let best = { columns: 1, rows: count, avatarSize: 0 };
  const columnLimit = Math.min(count, Math.ceil(availableWidth / gap));
  for (let columns = 1; columns <= columnLimit; columns += 1) {
    const rows = Math.ceil(count / columns);
    const avatarSize = Math.floor(Math.min(
      (availableWidth - gap * (columns - 1)) / columns,
      (availableHeight - gap * (rows - 1)) / rows,
    ));
    if (avatarSize > best.avatarSize) best = { columns, rows, avatarSize };
  }
  const gridWidth = best.columns * best.avatarSize + (best.columns - 1) * gap;
  const gridHeight = best.rows * best.avatarSize + (best.rows - 1) * gap;
  return {
    ...best, width, height, scale, padding, gap, headerHeight, footerHeight,
    gridWidth, gridHeight,
    gridTop: padding + headerHeight + Math.floor((availableHeight - gridHeight) / 2),
    footerTop: height - padding - footerHeight,
  };
}

/** Maximize square portraits on a portrait canvas, growing resolution when needed. */
export function calculateLayout(count, { width = 1800, height = 4200, minAvatarSize = 96 } = {}) {
  if (!Number.isSafeInteger(count) || count < 1) throw new RangeError("角色数量必须为正整数");
  if (![width, height, minAvatarSize].every(value => Number.isFinite(value) && value > 0)) {
    throw new RangeError("画布尺寸必须为正数");
  }
  const base = measureLayout(count, Math.round(width), Math.round(height), 1);
  if (base.avatarSize <= 0) throw new RangeError("角色数量超出图片排版容量");
  if (base.avatarSize >= minAvatarSize) return Object.freeze(base);
  let scale = minAvatarSize / base.avatarSize;
  let result;
  // Rounding padding and gaps can cost a pixel; recalculate rather than clipping.
  do {
    result = measureLayout(count, Math.ceil(width * scale), Math.ceil(height * scale), scale);
    if (result.avatarSize < minAvatarSize) scale += 0.01;
  } while (result.avatarSize < minAvatarSize);
  return Object.freeze(result);
}

/** Center every row, including the incomplete final row. */
export function getCellPosition(index, count, layout) {
  if (!Number.isInteger(index) || index < 0 || index >= count) throw new RangeError("角色位置无效");
  const row = Math.floor(index / layout.columns);
  const column = index % layout.columns;
  const rowCount = Math.min(layout.columns, count - row * layout.columns);
  const rowWidth = rowCount * layout.avatarSize + (rowCount - 1) * layout.gap;
  return {
    x: Math.floor((layout.width - rowWidth) / 2) + column * (layout.avatarSize + layout.gap),
    y: layout.gridTop + row * (layout.avatarSize + layout.gap),
  };
}

export function imageFilename(date = new Date()) {
  const pad = value => String(value).padStart(2, "0");
  return `another-tier-个人图鉴-${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}.png`;
}

export function imageSources(slug) {
  const path = slug === "__stellar__" ? STAR_PATH : `${PORTRAIT_PATH}${encodeURIComponent(slug)}/portrait`;
  const localPath = path.replace(/[^a-zA-Z0-9/._-]/g, "_") + ".webp";
  return [new URL(`../mirror-images/${localPath}`, import.meta.url).href, CDN + path];
}

function makeCanvas(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("此浏览器无法创建图片画布，请换用其他浏览器重试。");
  return { canvas, context };
}

function loadSource(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    // CORS must be configured before src, including CDN fallback.
    image.crossOrigin = "anonymous";
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      image.onload = null;
      image.onerror = null;
      if (error) {
        image.src = "";
        reject(error);
      } else resolve(image);
    };
    const timer = setTimeout(() => finish(new Error("图片加载超时")), IMAGE_TIMEOUT);
    image.onerror = () => finish(new Error("图片加载失败"));
    image.onload = async () => {
      let probe;
      try {
        if (typeof image.decode === "function") await image.decode();
        if (!image.naturalWidth || !image.naturalHeight) throw new Error("图片解码失败");
        // Detect a tainted source now so it can use the next source before export.
        probe = makeCanvas(1, 1);
        probe.context.drawImage(image, 0, 0, 1, 1);
        probe.context.getImageData(0, 0, 1, 1);
        finish();
      } catch (error) {
        finish(error);
      } finally {
        if (probe) probe.canvas.width = probe.canvas.height = 0;
      }
    };
    image.src = src;
  });
}

async function loadImage(slug) {
  const cached = imageCache.get(slug);
  if (cached) return cached;
  const loading = (async () => {
    for (const src of imageSources(slug)) {
      try { return await loadSource(src); } catch { /* Try the CORS CDN fallback. */ }
    }
    throw new Error(`无法加载 ${slug}`);
  })();
  imageCache.set(slug, loading);
  try {
    const image = await loading;
    if (imageCache.size > MAX_CACHED_IMAGES) {
      imageCache.delete(imageCache.keys().next().value);
    }
    return image;
  } catch (error) {
    // Failed resources must be attempted again when the user chooses retry.
    imageCache.delete(slug);
    throw error;
  }
}

export function clearExportImageCache() {
  imageCache.clear();
}

function checkCancelled(signal) {
  if (signal?.aborted) throw new DOMException("已取消图片生成", "AbortError");
}

// Cancel only this wait. A cached image may still be needed by another export.
function waitForImage(promise, signal) {
  if (!signal) return promise;
  return new Promise((resolve, reject) => {
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    const onAbort = () => {
      cleanup();
      reject(new DOMException("已取消图片生成", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    // Keep both handlers attached after abort so a later background failure is handled.
    promise.then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
    if (signal.aborted) onAbort();
  });
}

function freezeSnapshot(characters, statuses) {
  if (!Array.isArray(characters) || !characters.length) throw new Error("角色目录为空，无法生成图片。");
  const seen = new Set();
  return Object.freeze(characters.map(character => {
    if (!character || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(character.slug)) {
      throw new Error("角色目录包含无效标识，无法生成完整图片。");
    }
    if (seen.has(character.slug)) throw new Error(`角色目录包含重复项：${character.slug}`);
    seen.add(character.slug);
    const canSA = character.canSA === true;
    const status = getCharacterStatus(character, statuses);
    return Object.freeze({ slug: character.slug, name: character.name || character.slug, canSA, status });
  }));
}

function drawCover(context, image, x, y, size) {
  const side = Math.min(image.naturalWidth, image.naturalHeight);
  context.drawImage(image, (image.naturalWidth - side) / 2, (image.naturalHeight - side) / 2,
    side, side, x, y, size, size);
}

/** Convert pixels explicitly; Canvas filter support varies between browsers. */
function grayscale(context, width, height) {
  const pixels = context.getImageData(0, 0, width, height);
  for (let i = 0; i < pixels.data.length; i += 4) {
    const luminance = Math.round(pixels.data[i] * 0.2126 + pixels.data[i + 1] * 0.7152 + pixels.data[i + 2] * 0.0722);
    pixels.data[i] = pixels.data[i + 1] = pixels.data[i + 2] = luminance;
  }
  context.putImageData(pixels, 0, 0);
}

function drawHeader(context, snapshot, layout, generatedAt, statusFilter) {
  const { scale, padding, width, footerTop } = layout;
  const owned = snapshot.filter(character => character.status !== "unowned").length;
  const awakened = snapshot.filter(character => character.status === "awakened").length;
  const available = snapshot.filter(character => character.canSA).length;
  context.fillStyle = "#111827";
  context.fillRect(0, 0, width, layout.height);
  context.textAlign = "center";
  context.textBaseline = "top";
  context.fillStyle = "#f9fafb";
  context.font = `600 ${Math.round(57 * scale)}px ${FONT}`;
  const title = { all: "个人角色图鉴", owned: "已拥有角色图鉴", unowned: "未拥有角色图鉴" }[statusFilter];
  context.fillText(title, width / 2, padding + 12 * scale);
  context.fillStyle = "#d1d5db";
  context.font = `${Math.round(29 * scale)}px ${FONT}`;
  context.fillText(`已拥有 ${owned} / ${snapshot.length}    ·    已星导 ${awakened} / ${available}`, width / 2, padding + 99 * scale);
  context.strokeStyle = "#374151";
  context.lineWidth = Math.max(1, scale);
  context.beginPath();
  context.moveTo(padding, footerTop + 19 * scale);
  context.lineTo(width - padding, footerTop + 19 * scale);
  context.stroke();
  context.fillStyle = "#d1d5db";
  context.font = `${Math.round(24 * scale)}px ${FONT}`;
  context.fillText("灰色头像：未拥有  ·  彩色头像：已拥有", width / 2, footerTop + 48 * scale);
  context.fillText("灰色星导标志：未星导  ·  彩色星导标志：已星导", width / 2, footerTop + 88 * scale);
  context.fillStyle = "#9ca3af";
  context.font = `${Math.round(20 * scale)}px ${FONT}`;
  const date = `${generatedAt.getFullYear()}-${String(generatedAt.getMonth() + 1).padStart(2, "0")}-${String(generatedAt.getDate()).padStart(2, "0")}`;
  context.fillText(`生成于 ${date}  ·  原榜单 Natural_Pleasant  ·  原站 Ryandi Tjia / Another Tier`, width / 2, footerTop + 133 * scale);
}

function toPng(canvas) {
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error("PNG 编码失败，请稍后重试。")), "image/png");
    } catch {
      reject(new Error("PNG 导出失败，图片可能未完整加载或画布尺寸超出此浏览器限制。请重试或换用其他浏览器。"));
    }
  });
}

/**
 * Call with the full sorted catalog and effective slug -> state dictionary.
 * Only the ownership tab limits the export; search and attribute filters do not.
 * The caller owns download/preview object URLs and must revoke them on close.
 * Loading failures include every missing resource in error.missing; retry by calling again.
 */
export async function exportCollectionImage({ characters, statuses = {}, statusFilter = "all", onProgress = () => {}, signal } = {}) {
  if (!["all", "owned", "unowned"].includes(statusFilter)) throw new RangeError("无效的图鉴导出范围");
  const snapshot = freezeSnapshot(characters, statuses).filter(character => statusFilter === "all"
    || (statusFilter === "owned" ? character.status !== "unowned" : character.status === "unowned"));
  if (!snapshot.length) throw new Error(`没有${statusFilter === "owned" ? "已拥有" : "未拥有"}的角色，无法生成图片。`);
  const generatedAt = new Date();
  const layout = calculateLayout(snapshot.length);
  const progress = (phase, completed, total, percent, message) => onProgress({ phase, completed, total, percent, message });
  checkCancelled(signal);
  const resources = snapshot.map(character => ({ slug: character.slug, name: character.name }));
  if (snapshot.some(character => character.canSA)) resources.push({ slug: "__stellar__", name: "星导标志" });
  const images = new Map();
  const missing = [];
  let next = 0;
  let loaded = 0;
  progress("loading", 0, resources.length, 0, `加载图鉴素材：0 / ${resources.length}`);
  await Promise.all(Array.from({ length: Math.min(6, resources.length) }, async () => {
    while (next < resources.length) {
      checkCancelled(signal);
      const resource = resources[next++];
      try { images.set(resource.slug, await waitForImage(loadImage(resource.slug), signal)); }
      catch {
        checkCancelled(signal);
        missing.push(resource);
      }
      loaded += 1;
      progress("loading", loaded, resources.length, Math.round(loaded / resources.length * 75), `加载图鉴素材：${loaded} / ${resources.length}`);
    }
  }));
  checkCancelled(signal);
  if (missing.length) {
    const order = new Map(resources.map((resource, index) => [resource.slug, index]));
    missing.sort((a, b) => order.get(a.slug) - order.get(b.slug));
    throw new ExportImageError(missing);
  }
  let output;
  let portrait;
  let star;
  let grayStar;
  try {
    output = makeCanvas(layout.width, layout.height);
    portrait = makeCanvas(layout.avatarSize, layout.avatarSize);
    const context = output.context;
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    drawHeader(context, snapshot, layout, generatedAt, statusFilter);
    const starHeight = Math.round(layout.avatarSize * 0.36);
    const starWidth = Math.round(starHeight * 21 / 24);
    if (images.has("__stellar__")) {
      star = makeCanvas(starWidth, starHeight);
      grayStar = makeCanvas(starWidth, starHeight);
      star.context.drawImage(images.get("__stellar__"), 0, 0, starWidth, starHeight);
      grayStar.context.drawImage(star.canvas, 0, 0);
      grayscale(grayStar.context, starWidth, starHeight);
    }
    for (let index = 0; index < snapshot.length; index += 1) {
      checkCancelled(signal);
      const character = snapshot[index];
      const { x, y } = getCellPosition(index, snapshot.length, layout);
      context.fillStyle = "#374151";
      context.fillRect(x - 1, y - 1, layout.avatarSize + 2, layout.avatarSize + 2);
      if (character.status === "unowned") {
        portrait.context.clearRect(0, 0, layout.avatarSize, layout.avatarSize);
        drawCover(portrait.context, images.get(character.slug), 0, 0, layout.avatarSize);
        grayscale(portrait.context, layout.avatarSize, layout.avatarSize);
        context.drawImage(portrait.canvas, x, y);
      } else drawCover(context, images.get(character.slug), x, y, layout.avatarSize);
      // Stars are independent layers. Never render one on a non-SA character.
      if (character.canSA) {
        context.drawImage(character.status === "awakened" ? star.canvas : grayStar.canvas,
          x + Math.round(layout.avatarSize * 0.025), y + Math.round(layout.avatarSize * 0.025));
      }
      if ((index + 1) % 20 === 0 || index === snapshot.length - 1) {
        progress("drawing", index + 1, snapshot.length, 75 + Math.round((index + 1) / snapshot.length * 22), `绘制角色：${index + 1} / ${snapshot.length}`);
        await new Promise(resolve => setTimeout(resolve, 0));
      }
    }
    checkCancelled(signal);
    progress("encoding", 0, 1, 98, "正在生成 PNG 图片…");
    const blob = await toPng(output.canvas);
    checkCancelled(signal);
    progress("encoding", 1, 1, 100, "图片生成完成");
    return { blob, filename: imageFilename(generatedAt), width: layout.width, height: layout.height, count: snapshot.length };
  } finally {
    // Reset backing stores even when decoding, drawing or PNG encoding fails.
    for (const layer of [output, portrait, star, grayStar]) {
      if (layer) layer.canvas.width = layer.canvas.height = 0;
    }
    images.clear();
  }
}
