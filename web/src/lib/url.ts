// Tiny helper to prepend Astro's base path to internal URLs.
// import.meta.env.BASE_URL is '/' or '/happycake-us/' depending on deploy.
export function withBase(path: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  if (path.startsWith('http')) return path;
  if (!path.startsWith('/')) path = '/' + path;
  return base + path;
}
