"""Production entrypoint for the Ansumi Orbital Hub (ASC_074).

Run this instead of `api.py` when serving the dashboard to anyone other than
yourself. It differs from the development server in three ways that matter:

  * **Waitress, not the Flask dev server.** Werkzeug's server is explicitly
    not for production, and its auto-reloader was interrupting long image
    generations mid-request.
  * **Debug mode off.** Flask's debugger executes arbitrary code from the
    browser. Leaving it on while listening on a network interface would hand
    a shell to anyone who can reach the port.
  * **Binds to every interface**, so other machines on the network can reach
    it -- which is the whole point of serving it.

The built UI (dist/) is served by the same process on the same port, so the
application is one origin: no CORS exposure, one URL to hand out.

    python serve.py                 # port 5001, all interfaces
    python serve.py --port 8080
    python serve.py --host 127.0.0.1  # this machine only

Access to every dashboard section is still gated by the per-section codes in
config/access_codes.json. Anyone who can reach the port sees the shell and
the mission name; they see no mission data without a code.
"""

import argparse
import os
import socket
from pathlib import Path

BASE = Path(__file__).resolve().parent


def local_addresses(port):
    """Best-effort list of URLs this server will answer on."""
    urls = [f"http://127.0.0.1:{port}"]
    try:
        # Opening a UDP socket to a public address reveals which local
        # interface the OS would route through, without sending anything.
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.2)
        probe.connect(("8.8.8.8", 80))
        lan_ip = probe.getsockname()[0]
        probe.close()
        if lan_ip and not lan_ip.startswith("127."):
            urls.append(f"http://{lan_ip}:{port}")
    except Exception:
        pass
    return urls


def main():
    parser = argparse.ArgumentParser(description="Serve the ASC_074 dashboard.")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Interface to bind (default: all, so the network can reach it)")
    # Hosting platforms assign the port at runtime and expect the app to obey
    # $PORT; the flag stays available for local use.
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5001)))
    parser.add_argument("--threads", type=int, default=8,
                        help="Worker threads. Image generation is slow and I/O bound, "
                             "so a few threads keep the UI responsive during a batch.")
    args = parser.parse_args()

    if not (BASE / "dist" / "index.html").exists():
        raise SystemExit(
            "dist/ is missing or empty -- the UI has not been built.\n"
            "Build it first, with the API base left empty so requests stay same-origin:\n"
            '    npm run build        (see DEPLOY.md for the exact command)\n'
        )

    from waitress import serve

    import api  # imports the Flask app and its routes

    # Warming computes every mission's payload up front (default mission
    # first, see core.missions.MISSIONS) so the first visitor does not wait
    # ~10 s. It is also the peak-memory moment, so a small hosted instance
    # can turn it off and pay the cost on first request.
    if os.environ.get("ASC074_WARM_CACHES", "1") not in ("0", "false", "False"):
        api._warm_caches()

    urls = local_addresses(args.port)
    print("Ansumi Orbital Hub (ASC_074) — serving")
    print(f"  server   : waitress ({args.threads} threads), debug OFF")
    for u in urls:
        print(f"  reachable: {u}")
    if args.host == "0.0.0.0" and len(urls) > 1:
        print(f"\n  Share the second URL with people on your network.")
        print("  If they cannot connect, Windows Firewall is very likely blocking")
        print(f"  inbound TCP {args.port} -- see DEPLOY.md for the one-line fix.")
    print("\n  Every section still requires its access code from config/access_codes.json.")
    print("  Ctrl+C to stop.\n")

    serve(api.app, host=args.host, port=args.port, threads=args.threads)


if __name__ == "__main__":
    main()
