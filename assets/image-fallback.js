// Start after hydration so an early CDN failure cannot change the server markup.
const cdn = "https://res.cloudinary.com/ryanditjia/image/upload/";

function useLocalImage(image) {
  if (!(image instanceof HTMLImageElement) || !image.src.startsWith(cdn)) return;
  const file = image.src.slice(cdn.length).replace(/[^a-zA-Z0-9/._-]/g, "_") + ".webp";
  image.src = new URL("../mirror-images/" + file, import.meta.url).href;
}

export function installImageFallback() {
  const onError = event => useLocalImage(event.target);
  document.addEventListener("error", onError, true);
  // Images can fail before React attaches the listener on the first visit.
  for (const image of document.images) {
    if (image.complete && image.naturalWidth === 0) useLocalImage(image);
  }
  return () => document.removeEventListener("error", onError, true);
}
