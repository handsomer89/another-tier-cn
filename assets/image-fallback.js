import { imageVersions } from './image-manifest.js?v=36ed4f782854';

const CDN = 'https://res.cloudinary.com/ryanditjia/image/upload/';
const mirror = new URL('../mirror-images/', import.meta.url);

// New API characters can use the CDN before the next static snapshot refresh.
export function imageSourcesForURL(source) {
  if (typeof source !== 'string' || !source.startsWith(CDN)) return [source];
  const file = source.slice(CDN.length).replace(/[^a-zA-Z0-9/._-]/g, '_') + '.webp';
  const version = imageVersions[file];
  return version ? [new URL(file + '?v=' + version, mirror).href, source] : [source];
}

export function setImageSource(image, source) {
  const sources = imageSourcesForURL(source);
  if (sources.length > 1) image.setAttribute('data-original-src', source);
  else image.removeAttribute('data-original-src');
  image.src = sources[0];
}

function useOriginalImage(image) {
  if (!(image instanceof HTMLImageElement)) return;
  const original = image.getAttribute('data-original-src');
  if (!original?.startsWith(CDN)) return;
  const [local] = imageSourcesForURL(original);
  // The original is the final attempt, including when its own request fails.
  if (image.src === local && local !== original) image.src = original;
}

// Apply before React creates images, including lazy images and route changes.
// This keeps hydration consistent with the generated snapshot-first HTML.
export function mirrorImageRuntime(runtime) {
  const wrap = render => (type, props, ...rest) => {
    if (type === 'img') {
      const [source, original] = imageSourcesForURL(props.src);
      const onError = props.onError;
      if (original) props = { ...props, src: source, 'data-original-src': original,
        onError: event => { useOriginalImage(event.currentTarget); onError?.(event); } };
    }
    return render(type, props, ...rest);
  };
  return { ...runtime, jsx: wrap(runtime.jsx), jsxs: wrap(runtime.jsxs) };
}

export function installImageFallback() {
  const onError = event => useOriginalImage(event.target);
  document.addEventListener('error', onError, true);
  for (const image of document.images) {
    if (image.complete && image.naturalWidth === 0) useOriginalImage(image);
  }
  if (globalThis.isSecureContext && 'serviceWorker' in navigator) {
    // On-demand image cache. HTML, APIs and personal records are never stored.
    navigator.serviceWorker.register(new URL('../image-cache-sw.js', import.meta.url),
      { scope: new URL('../', import.meta.url).pathname, updateViaCache: 'none' }).catch(() => {});
  }
  return () => document.removeEventListener('error', onError, true);
}
