const API_PREFIX = "/api/";
function corsHeaders(origin) {
  const headers = new Headers({
    "access-control-allow-credentials": "true",
    "access-control-allow-headers": "content-type, authorization, x-requested-with",
    "access-control-allow-methods": "GET,HEAD,POST,OPTIONS",
    "access-control-max-age": "86400",
  });
  if (origin) headers.set("access-control-allow-origin", origin);
  return headers;
}
function jsonResponse(payload, status, request) {
  const headers = corsHeaders(request.headers.get("Origin"));
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  return new Response(JSON.stringify(payload), { status, headers });
}
function backendUrl(env) {
  const value = String(env.ASTK_BACKEND_URL || "").trim().replace(/\/$/, "");
  return value && /^https?:\/\//i.test(value) ? value : "";
}
async function proxyApi(request, env) {
  const upstream = backendUrl(env);
  if (!upstream) {
    return jsonResponse({ status: "unavailable", error: "ASTK_BACKEND_URL is not configured on the Cloudflare Worker." }, 503, request);
  }
  const incoming = new URL(request.url);
  const target = new URL(`${upstream}${incoming.pathname}${incoming.search}`);
  const headers = new Headers(request.headers);
  headers.delete("host"); headers.delete("cookie");
  headers.set("x-forwarded-host", incoming.host);
  headers.set("x-forwarded-proto", incoming.protocol.replace(":", ""));
  let body;
  if (request.method !== "GET" && request.method !== "HEAD") body = request.body;
  const response = await fetch(target, { method: request.method, headers, body, redirect: "manual" });
  const outputHeaders = new Headers(response.headers);
  outputHeaders.set("cache-control", "no-store");
  const origin = request.headers.get("Origin");
  for (const [name, value] of corsHeaders(origin)) outputHeaders.set(name, value);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers: outputHeaders });
}
const ASSET_CONTENT_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".csv": "text/csv; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".pdf": "application/pdf",
  ".zip": "application/zip",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
};
function fixAssetContentType(response, pathname) {
  const current = response.headers.get("content-type") || "";
  if (current && !current.startsWith("application/octet-stream")) return response;
  let path = pathname;
  if (path.endsWith("/")) path += "index.html";
  const dot = path.lastIndexOf(".");
  const ext = dot === -1 ? ".html" : path.slice(dot).toLowerCase();
  const wanted = ASSET_CONTENT_TYPES[ext];
  if (!wanted) return response;
  const headers = new Headers(response.headers);
  headers.set("content-type", wanted);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith(API_PREFIX)) return fixAssetContentType(await env.ASSETS.fetch(request), url.pathname);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders(request.headers.get("Origin")) });
    try { return await proxyApi(request, env); }
    catch (error) { return jsonResponse({ status: "error", error: `ASTK backend proxy failed: ${error instanceof Error ? error.message : String(error)}` }, 502, request); }
  },
};
