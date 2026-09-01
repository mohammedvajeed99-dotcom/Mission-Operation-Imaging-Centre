# Deploying the Ansumi Orbital Hub (ASC_074)

Serving the dashboard to other people is different from running it for
yourself. This describes the network deployment.

---

## Quick start

```bash
python serve.py
```

Then share the LAN URL it prints, e.g. `http://192.168.0.104:5001`.

Anyone on the same network — office WiFi, home router — can open that in a
browser. They need no Python, no Node, and nothing installed.

---

## What `serve.py` does differently from `api.py`

`api.py` is the **development** server. Do not use it to serve other people.

| | `api.py` (dev) | `serve.py` (deployment) |
|---|---|---|
| Server | Flask/Werkzeug dev server | **Waitress**, a real WSGI server |
| Debug mode | **On** — the browser-facing debugger can execute arbitrary code | **Off** |
| Binds to | `127.0.0.1` — this machine only | `0.0.0.0` — reachable on the network |
| Frontend | Vite on a second port, cross-origin | Built UI served by the same process, **same origin** |
| Auto-reload | On (and it interrupts long image generations) | Off |

The debug-mode difference is the important one: Flask's debugger hands a
remote shell to anyone who can reach the port. It must never listen on a
network interface.

---

## Rebuilding the UI after code changes

The deployment serves the **built** frontend from `dist/`. Changes to
anything in `src/` do not appear until you rebuild:

```bash
npm run build
```

The build must leave the API base empty so the UI calls its own origin. On
Windows PowerShell:

```powershell
$env:VITE_API_BASE=""; npm run build
```

On Git Bash / macOS / Linux:

```bash
VITE_API_BASE= npm run build
```

If the API base is wrong, the app loads for you but shows **"Cannot reach the
mission API"** for everyone else — their browser would be trying to reach
`127.0.0.1` on *their own* machine.

---

## If other machines cannot connect

Almost always Windows Firewall blocking inbound TCP 5001. Run this **once**,
in an Administrator PowerShell:

```powershell
New-NetFirewallRule -DisplayName "ASC_074 Dashboard" -Direction Inbound -LocalPort 5001 -Protocol TCP -Action Allow -Profile Private
```

`-Profile Private` restricts the rule to networks you have marked private
(home/work). It deliberately does not open the port on public networks such
as cafe or airport WiFi.

To remove it later:

```powershell
Remove-NetFirewallRule -DisplayName "ASC_074 Dashboard"
```

Other things to check:
- Both machines are on the same network — phone hotspots and guest WiFi are
  usually isolated from each other.
- The IP can change when the router reassigns leases. Re-run `serve.py` to
  see the current one.

---

## Options

```bash
python serve.py --port 8080        # different port
python serve.py --host 127.0.0.1   # this machine only, no network exposure
python serve.py --threads 16       # more concurrent requests
```

---

## Access control

Every dashboard section stays gated by the codes in
`config/access_codes.json`. Someone who reaches the URL sees the shell, the
mission name, and the "How to Read This Dashboard" page. **They see no
mission data without a code**, because the server strips locked sections'
data from the response rather than merely hiding it in the UI.

Hand out only the codes for the sections a person should see. The open-lock
icon beside an unlocked section in the sidebar hands that access back.

### Full-access code

`access_codes.json` also has a `masterCode` -- one code that opens every
section at once, entered in the "Developer / reviewer access" box at the top
of the sidebar rather than one section at a time. It exists for someone who
needs the whole dashboard to do their job (a developer, the CEO, a technical
reviewer) rather than the routine case of a person who should see a few
specific sections. Print it the same way as the section codes:

```bash
python -c "import json; print(json.load(open('config/access_codes.json'))['masterCode'])"
```

Hand it out sparingly -- it bypasses the section-by-section restriction
entirely. "Lock all" in the sidebar surrenders full access the same way the
per-section lock icon surrenders one section.

`config/access_codes.json` and `config/.access_secret` are git-ignored and
must stay that way: the first opens every section, and the second allows
forging access tokens.

---

## Sharing with someone outside your network

The LAN URL only works for people on your own network. To reach someone in
another country, put a Cloudflare quick tunnel in front of the local server:

```bash
python serve.py
```

then, in a **second terminal**:

```bash
cloudflared tunnel --url http://localhost:5001
```

It prints a public URL like `https://random-words-here.trycloudflare.com`.
Send that to them. It works from anywhere, over HTTPS, with no account and
nothing uploaded — traffic is relayed to the server running on your machine.

Two consequences worth understanding:

- **Your machine is the host.** The link works only while both the server and
  the tunnel are running. Close either, or sleep the PC, and it stops.
- **The URL changes** every time you start a quick tunnel. Send the current
  one.

### Because this is now on the public internet

Two hardening changes were made before exposing it:

- **Access codes are much longer.** They were 4 hex characters (65,536
  combinations) — fine on a trusted LAN, enumerable in minutes from the
  internet. They are now 10 hex characters, about 1.1 x 10^12 combinations.
  **Codes were regenerated, so any you handed out previously no longer work.**
- **The unlock endpoint is throttled.** Eight wrong codes from one client
  triggers a five-minute lockout, during which even a correct code is
  refused — so guessing cannot be scripted, and a correct guess cannot be
  confirmed by timing.

Send your friend only the codes for the sections they should see. If you want
to revoke everything later, delete `config/.access_secret` and restart: every
issued token becomes invalid immediately.

## Always-on hosting (survives your PC being off)

The tunnel above relays to *your machine*, so it dies when your machine does.
For a URL that works regardless, the application has to run on a host.

`Dockerfile` builds the whole thing — frontend and API — into one container.
It is standard Docker, so Render, Fly.io, Railway and any VPS all work;
`render.yaml` is included because Render has the least friction.

### The one thing you must not skip

A hosted filesystem is **ephemeral**: every restart and redeploy wipes it. If
the access codes and signing secret are generated inside the container, they
are regenerated on every restart — **silently changing every code you have
handed out** and logging everyone out.

So both are supplied as environment variables instead:

| Variable | What to set it to |
|---|---|
| `ASC074_ACCESS_CODES` | The entire contents of `config/access_codes.json` |
| `ASC074_ACCESS_SECRET` | Any long random string, kept private |
| `ASC074_WARM_CACHES` | `0` on a small/free plan (see memory note below) |

Print the codes to paste in:

```bash
python -c "print(open('config/access_codes.json').read())"
```

Generate a signing secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Deploying on Render

1. Push this repository to GitHub. `.gitignore` already excludes
   `config/access_codes.json` and `config/.access_secret` — keep it that way.
2. On [render.com](https://render.com), create a free account and choose
   **New → Blueprint**, pointing it at the repository. It reads `render.yaml`.
3. When prompted, set `ASC074_ACCESS_SECRET` and `ASC074_ACCESS_CODES` to the
   values printed above.
4. Deploy. The first build takes several minutes (GDAL and rasterio are
   large). You get a permanent `https://<name>.onrender.com` URL.

Any other Docker host works the same way: build the image, set the three
environment variables, expose the port the platform assigns via `$PORT`.

### What ships, so that every section works

All 31 sections work on the deployment. Twenty-nine of them read the small
processed data files (~8 MB), which are always included. The two Image Center
sections need product files, so those are shipped selectively:

| File | Purpose | Size | Shipped |
|---|---|---|---|
| `.json` | Product metadata — drives the whole detail panel | 0.1 MB | yes |
| `.thumb.jpg` | Gallery tiles | 0.7 MB | yes |
| `.png` | Full-resolution preview and zoom | 80 MB | yes |
| `.tif` | Full-resolution GeoTIFF | 230 MB | **no** |

The GeoTIFFs are the single exclusion: 16 MB each, not needed to view or
analyse anything in the UI, and rebuildable on demand. Where one is absent the
download menu shows **GeoTIFF — unavailable** with the reason, instead of
offering it and failing on click; every other format still works, and the ZIP
bundle contains whatever is present. Regenerating an observation rebuilds its
GeoTIFF and the entry becomes downloadable again.

Gallery tiles come from a separate thumbnail tier (`/preview?size=thumb`,
~50 KB each) rather than the 6 MB PNG. That is what makes the gallery usable
remotely at all: one gallery view transfers **380 KB instead of ~73 MB**. The
detail view still loads the full-resolution PNG.

### What to expect on a free plan

Be aware of these before promising anyone a demo:

- **Cold starts.** Render's free tier sleeps a service after ~15 minutes of
  inactivity; the next visit waits ~1 minute while it wakes, then a further
  ~10 s to build the first mission payload.
- **Memory.** The 48-satellite payload densifies to ~840k track points, which
  is the peak-memory moment. `ASC074_WARM_CACHES=0` avoids doing that for
  both missions at startup. If the service restarts under load, a paid plan
  with more RAM is the fix.
- **Generating a *new* image will be slow, and may not work at all.** It
  downloads tens of megabytes from the Sentinel-2 archive and holds large
  rasters in memory. Use the 512 px setting, and expect the free tier's memory
  limit to be the binding constraint. The products that ship with the image
  are unaffected — they are already generated.
- **Newly generated products do not survive a restart.** The hosted filesystem
  is ephemeral, so anything generated on the host is lost when the service
  restarts; the shipped products always come back, because they are part of
  the image. A persistent disk would keep new products, but note that a disk
  mounted over `data/image_center` hides the shipped ones until they are
  copied onto it.

## Scope of this deployment

Three ways of serving it are described above, in increasing reach:

| | Reach | Runs on | Survives your PC being off |
|---|---|---|---|
| `serve.py` | Same network | your machine | no |
| Cloudflare quick tunnel | Anywhere | your machine | no |
| Docker host (Render etc.) | Anywhere | the host | **yes** |

What has been hardened for exposure beyond a trusted network:

- **HTTPS termination** — provided by the tunnel and by any hosting platform.
- **Access codes at 10 hex characters** (~1.1 x 10^12 combinations), up from
  the 4 characters that were enumerable in minutes.
- **Throttling on `/api/access/unlock`** — eight wrong codes from one client
  triggers a five-minute lockout, so guessing cannot be scripted.
- **Server-side data filtering** — locked sections are stripped from the API
  response, not merely hidden in the UI.
- **Same-origin serving** — the built UI and the API share one origin, so the
  permissive CORS setting in `api.py` is not reachable cross-origin in a
  deployment.

What is still worth doing before treating this as a public service rather than
a demonstration you hand a link to: tighten the `CORS` allowlist in `api.py`
rather than relying on same-origin serving, and put the access codes behind a
per-person identity rather than a shared secret, so a leaked code can be
revoked without rotating everyone's.
