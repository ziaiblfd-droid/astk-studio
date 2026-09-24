# Access and upload checks (2026-09-24)

## Upload path

Browser -> Cloudflare Worker `/api/uploads` -> named tunnel -> Python backend.
The former uploader sent 1 MiB chunks sequentially. It now negotiates the
chunk size with the backend (default 4 MiB) and sends up to three chunks
concurrently. Per-chunk retries remain; the server checks exact chunk lengths
and refuses to assemble missing chunks. The UI shows completed bytes and an
observed-rate-based upload estimate separately from analysis progress.

The change reduces request overhead, but cannot increase the user's actual
uplink capacity or overcome packet loss. Do not infer a ten-minute public
upload time from a local-network benchmark. If public uploads are still slow,
record the ZIP size, network/ISP, whether VPN was enabled, a HAR capture
with credentials redacted, and upload session time (no patient/sample data).
Compare Worker `/api/health` and tunnel `/api/health` from the affected network.
Large repeated retries point to routing or transport problems, not scoring.

## Site availability

The frontend is served from Cloudflare Workers Assets; the API passes through
Worker and a Cloudflare named tunnel to a server bound to `127.0.0.1:4173`.
The frontend no longer depends at runtime on fonts.googleapis.com or
unpkg.com; icons are served from the same site, and system fonts are used.
This removes two unrelated external requests from the critical path.

An intermittent VPN-dependent failure can still occur before the frontend
loads or between a client and Cloudflare, or between Cloudflare and the
tunnel. A single successful health request does not establish availability
across mainland carriers. Diagnose separately:

1. On the affected network, record the exact URL, time, DNS answer, HTTP
   status and browser error for `/` and `/api/health`, with VPN on and off.
2. From the server, compare `curl http://127.0.0.1:4173/api/health` with
   `curl https://api.astkstudio.dpdns.org/api/health` and inspect the tunnel
   service status and logs. Do not share the tunnel token.
3. If the origin and tunnel are healthy but the site is unreachable only on
   some access networks, use a separately hosted, legally/operationally
   approved domestic HTTPS frontend and reverse proxy, or a provider with
   a route reachable from those networks. This requires a domain, hosting
   and network permissions; changing frontend code or users' DNS alone
   cannot guarantee a reliable China-wide route.

The UI estimate is based on one previous workload (~40 minutes with the old
unsharded sequence scoring) and an isolated AF/SE sharding comparison. It is
an interval, not a live deadline. Queueing and data size are additional.
