/* ------------------------------------------------------------------
   Per-section access control (client side)

   This is the visible front end of a gate that is actually enforced on
   the server: the API strips locked sections' data before responding, so
   the lock panel below is not what protects the data -- it is what tells
   the operator which code to enter.
   ------------------------------------------------------------------ */

import React from "react";
import { KeyRound, Lock, ShieldCheck } from "lucide-react";

const TOKEN_KEY = "asc074AccessToken";

/* Pure token-to-URL builder, independent of React state. withAccess (below)
   is this closed over the current token for normal use; requestDownload
   callers that open a URL right after a fresh unlock pass the just-granted
   token here directly, since React state has not re-rendered yet at that
   point and the reactive withAccess would still carry the old one. */
export function buildAccessUrl(url, token) {
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}access=${encodeURIComponent(token)}`;
}

export const AccessContext = React.createContext({
  token: "",
  sections: [],
  missions: [],
  downloads: [],
  isUnlocked: () => false,
  isMissionUnlocked: () => true,
  isDownloadUnlocked: () => false,
  unlock: async () => ({ ok: false }),
  unlockMission: async () => ({ ok: false }),
  unlockDownload: async () => ({ ok: false }),
  requestDownload: () => {},
  authFetch: (url, opts) => fetch(url, opts),
  withAccess: (url) => url,
});

export function useAccess() {
  return React.useContext(AccessContext);
}

export function AccessProvider({ apiBase, children }) {
  const [token, setToken] = React.useState(
    () => (typeof window !== "undefined" && window.localStorage.getItem(TOKEN_KEY)) || ""
  );
  const [sections, setSections] = React.useState([]);
  const [missions, setMissions] = React.useState([]);
  const [downloads, setDownloads] = React.useState([]);

  React.useEffect(() => {
    if (typeof window === "undefined") return;
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  }, [token]);

  /* Ask the server which sections and missions this token opens. The server
     is the authority -- an expired or forged token simply comes back with
     everything locked (except the default mission, which needs no code). */
  const loadSections = React.useCallback(
    (activeToken) => {
      const headers = {};
      const t = activeToken !== undefined ? activeToken : token;
      if (t) headers["X-Access-Token"] = t;
      return fetch(`${apiBase}/api/access/sections`, { headers })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d) {
            setSections(d.sections || []);
            setMissions(d.missions || []);
            setDownloads(d.downloads || []);
          }
        })
        .catch(() => {});
    },
    [apiBase, token]
  );

  React.useEffect(() => {
    loadSections();
  }, [loadSections]);

  const unlockedSet = React.useMemo(
    () => new Set(sections.filter((s) => s.unlocked).map((s) => s.id)),
    [sections]
  );

  const isUnlocked = React.useCallback((id) => unlockedSet.has(id), [unlockedSet]);

  const sectionLabel = React.useCallback(
    (id) => sections.find((s) => s.id === id)?.label || id,
    [sections]
  );

  const unlockedMissionSet = React.useMemo(
    () => new Set(missions.filter((m) => m.unlocked).map((m) => m.id)),
    [missions]
  );

  /* Same fail-closed convention as isUnlocked: before the first
     /api/access/sections response lands, every mission reads as locked --
     the server always marks the default mission unlocked in that response,
     so it corrects itself within one render pass rather than needing a
     special case here. */
  const isMissionUnlocked = React.useCallback((id) => unlockedMissionSet.has(id), [unlockedMissionSet]);

  const missionLabel = React.useCallback(
    (id) => missions.find((m) => m.id === id)?.label || id,
    [missions]
  );

  const unlock = React.useCallback(
    async (section, code) => {
      try {
        const r = await fetch(`${apiBase}/api/access/unlock`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ section, code, token }),
        });
        const j = await r.json();
        if (!r.ok || !j.ok) return { ok: false, error: j.error || `Request failed (${r.status})` };
        setToken(j.token);
        await loadSections(j.token);
        return { ok: true };
      } catch (err) {
        return { ok: false, error: String(err.message || err) };
      }
    },
    [apiBase, token, loadSections]
  );

  /* Hand back access to a section. Needs no code -- surrendering access you
     already hold is always allowed. Pass "*" to lock everything. */
  const relock = React.useCallback(
    async (section) => {
      try {
        const r = await fetch(`${apiBase}/api/access/lock`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ section, token }),
        });
        const j = await r.json();
        if (!r.ok || !j.ok) return { ok: false, error: j.error || `Request failed (${r.status})` };
        setToken(j.token);
        await loadSections(j.token);
        return { ok: true };
      } catch (err) {
        return { ok: false, error: String(err.message || err) };
      }
    },
    [apiBase, token, loadSections]
  );

  /* Switching to a non-default mission is gated the same way opening a
     section is: its own code, exchanged for a wider token. */
  const unlockMission = React.useCallback(
    async (missionId, code) => {
      try {
        const r = await fetch(`${apiBase}/api/access/unlock`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mission: missionId, code, token }),
        });
        const j = await r.json();
        if (!r.ok || !j.ok) return { ok: false, error: j.error || `Request failed (${r.status})` };
        setToken(j.token);
        await loadSections(j.token);
        return { ok: true };
      } catch (err) {
        return { ok: false, error: String(err.message || err) };
      }
    },
    [apiBase, token, loadSections]
  );

  /* Surrender access to a mission -- needs no code, same as relock. */
  const relockMission = React.useCallback(
    async (missionId) => {
      try {
        const r = await fetch(`${apiBase}/api/access/lock`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mission: missionId, token }),
        });
        const j = await r.json();
        if (!r.ok || !j.ok) return { ok: false, error: j.error || `Request failed (${r.status})` };
        setToken(j.token);
        await loadSections(j.token);
        return { ok: true };
      } catch (err) {
        return { ok: false, error: String(err.message || err) };
      }
    },
    [apiBase, token, loadSections]
  );

  const unlockedDownloadSet = React.useMemo(
    () => new Set(downloads.filter((d) => d.unlocked).map((d) => d.id)),
    [downloads]
  );

  /* Fail-closed like isUnlocked: a section being unlocked for viewing says
     nothing about whether it is unlocked for downloading -- that is a
     second, independent grant. */
  const isDownloadUnlocked = React.useCallback((id) => unlockedDownloadSet.has(id), [unlockedDownloadSet]);

  const downloadLabel = React.useCallback(
    (id) => downloads.find((d) => d.id === id)?.label || sections.find((s) => s.id === id)?.label || id,
    [downloads, sections]
  );

  /* Downloading from a section is gated by a second code, separate from the
     code that unlocked it for viewing -- exchanged the same way a section
     or mission code is. */
  const unlockOneDownload = React.useCallback(
    async (section, code) => {
      try {
        const r = await fetch(`${apiBase}/api/access/unlock`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ downloadSection: section, code, token }),
        });
        const j = await r.json();
        if (!r.ok || !j.ok) return { ok: false, error: j.error || `Request failed (${r.status})` };
        setToken(j.token);
        await loadSections(j.token);
        // The freshly widened token is returned directly (not just set into
        // state) because a caller that opens a URL right after unlocking
        // cannot wait for the next render -- React state updates are not
        // synchronous, so `token` in this closure is still the pre-unlock
        // value the instant this resolves.
        return { ok: true, token: j.token };
      } catch (err) {
        return { ok: false, error: String(err.message || err) };
      }
    },
    [apiBase, token, loadSections]
  );

  /* A feature area can be gated by more than one section (Image Center's
     catalog and gallery share one download prompt), and the code the person
     was given may belong to either -- tried in order, stopping at the first
     match, so a single correct code unlocks whichever section it belongs
     to without the caller needing to know which one that is. */
  const unlockDownload = React.useCallback(
    async (sections, code) => {
      const candidates = Array.isArray(sections) ? sections : [sections];
      let lastError = "Incorrect access code";
      for (const section of candidates) {
        const res = await unlockOneDownload(section, code);
        if (res.ok) return res;
        lastError = res.error || lastError;
      }
      return { ok: false, error: lastError };
    },
    [unlockOneDownload]
  );

  /* Surrender download access to a section -- needs no code, same as relock. */
  const relockDownload = React.useCallback(
    async (section) => {
      try {
        const r = await fetch(`${apiBase}/api/access/lock`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ downloadSection: section, token }),
        });
        const j = await r.json();
        if (!r.ok || !j.ok) return { ok: false, error: j.error || `Request failed (${r.status})` };
        setToken(j.token);
        await loadSections(j.token);
        return { ok: true };
      } catch (err) {
        return { ok: false, error: String(err.message || err) };
      }
    },
    [apiBase, token, loadSections]
  );

  /* One shared prompt for every Download button in the app: if the section
     (or, for a feature area gated by more than one section, any one of
     them -- see Image Center's ic-catalog/ic-gallery) is already download-
     unlocked, or the caller holds full/master access which grants every
     download at once, `action` runs immediately with no interruption.
     Otherwise the actual download is held until a matching download code is
     entered, then `action` runs. This is the single place that decision is
     made, so every download control in the UI behaves identically without
     each one re-implementing the prompt. */
  const [pendingDownload, setPendingDownload] = React.useState(null);

  const requestDownload = React.useCallback(
    (section, action) => {
      const candidates = Array.isArray(section) ? section : [section];
      if (candidates.some((s) => isDownloadUnlocked(s))) {
        // Already unlocked, so the current token already carries this
        // grant -- no unlock just happened, so (unlike the gated path
        // below) this token is not stale.
        action(token);
        return;
      }
      setPendingDownload({ sections: candidates, action });
    },
    [isDownloadUnlocked, token]
  );

  /* Attaches the token to a normal fetch. Identity changes when the token
     changes, so callers that list it as a dependency re-fetch on unlock. */
  const authFetch = React.useCallback(
    (url, opts = {}) => {
      const headers = { ...(opts.headers || {}) };
      if (token) headers["X-Access-Token"] = token;
      return fetch(url, { ...opts, headers });
    },
    [token]
  );

  /* For browser-native GETs that cannot carry a header: <img src>,
     <a href> downloads and window.open. */
  const withAccess = React.useCallback((url) => buildAccessUrl(url, token), [token]);

  /* Public sections carry no code and can never be locked. */
  const isPublic = React.useCallback(
    (id) => sections.find((s) => s.id === id)?.public === true,
    [sections]
  );

  const value = React.useMemo(
    () => ({
      token, sections, missions, downloads, isUnlocked, isPublic, sectionLabel, unlock, relock,
      isMissionUnlocked, missionLabel, unlockMission, relockMission,
      isDownloadUnlocked, downloadLabel, unlockDownload, relockDownload, requestDownload,
      authFetch, withAccess, loadSections,
    }),
    [
      token, sections, missions, downloads, isUnlocked, isPublic, sectionLabel, unlock, relock,
      isMissionUnlocked, missionLabel, unlockMission, relockMission,
      isDownloadUnlocked, downloadLabel, unlockDownload, relockDownload, requestDownload,
      authFetch, withAccess, loadSections,
    ]
  );

  return (
    <AccessContext.Provider value={value}>
      {children}
      {pendingDownload ? (
        <DownloadGate
          label={pendingDownload.sections.map((s) => downloadLabel(s)).join(" / ")}
          onCancel={() => setPendingDownload(null)}
          onUnlock={async (code) => {
            const res = await unlockDownload(pendingDownload.sections, code);
            if (res.ok) {
              const action = pendingDownload.action;
              setPendingDownload(null);
              // Pass the just-granted token through directly -- see the
              // comment on unlockOneDownload for why the React state value
              // cannot be trusted yet at this exact point.
              action(res.token);
            }
            return res;
          }}
        />
      ) : null}
    </AccessContext.Provider>
  );
}

/* ------------------------- the download gate ------------------------- */

/* A compact modal, not a full contentGrid panel: downloading is a header-
   level action taken from wherever the person already is, and that view
   stays exactly as it was if they cancel. Visually mirrors the mission
   switch gate in Header (main.jsx) -- both interrupt an in-place action
   rather than replacing the whole page the way AccessGate does. */
function DownloadGate({ label, onCancel, onUnlock }) {
  const [code, setCode] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError("");
    const res = await onUnlock(code.trim());
    setBusy(false);
    if (!res.ok) setError(res.error || "Incorrect access code");
  };

  return (
    <div className="missionGateOverlay" onClick={onCancel}>
      <form className="missionGatePanel" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <div className="gateIcon">
          <Lock size={22} />
        </div>
        <p className="gateEyebrow">Download requires a second code</p>
        <h3>{label}</h3>
        <p className="gateSub">
          Viewing this section does not by itself allow downloading from it. Enter this section&apos;s
          download code to continue — nothing has been downloaded yet.
        </p>
        <label className="gateField">
          <KeyRound size={15} />
          <input
            type="text"
            value={code}
            autoComplete="off"
            spellCheck="false"
            placeholder="Enter download access code"
            onChange={(e) => setCode(e.target.value)}
            autoFocus
          />
        </label>
        <div className="missionGateActions">
          <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>
          <button className="btn primary" type="submit" disabled={busy || !code.trim()}>
            <ShieldCheck size={15} /> {busy ? "Checking…" : "Download"}
          </button>
        </div>
        {error ? <p className="gateError">{error}</p> : null}
      </form>
    </div>
  );
}

/* ---------------------------- the gate ---------------------------- */

export function AccessGate({ section, children }) {
  const { isUnlocked, sectionLabel, unlock, sections } = useAccess();
  const [code, setCode] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    setCode("");
    setError("");
  }, [section]);

  if (isUnlocked(section)) return children;

  const known = sections.some((s) => s.id === section);
  if (sections.length && !known) {
    return (
      <div className="contentGrid">
        <section className="panel reveal wide">
          <div className="panelHead">
            <div>
              <h2>Unknown section</h2>
              <p>No section is registered under “{section}”.</p>
            </div>
          </div>
        </section>
      </div>
    );
  }

  const submit = async (e) => {
    e.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    setError("");
    const res = await unlock(section, code.trim());
    setBusy(false);
    if (!res.ok) {
      setError(res.error || "Incorrect access code");
      setCode("");
    }
  };

  return (
    <div className="contentGrid">
      <section className="panel reveal wide gatePanel">
        <div className="gateInner">
          <div className="gateIcon">
            <Lock size={26} />
          </div>
          <p className="gateEyebrow">Restricted section</p>
          <h2>{sectionLabel(section)}</h2>
          <p className="gateSub">
            This section requires an access code issued by the project owner. Its data is
            withheld by the server until a valid code is entered — nothing for this section
            has been sent to your browser.
          </p>

          <form className="gateForm" onSubmit={submit}>
            <label className="gateField">
              <KeyRound size={15} />
              <input
                type="text"
                value={code}
                autoComplete="off"
                spellCheck="false"
                placeholder="Enter access code"
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
            <button className="btn primary" type="submit" disabled={busy || !code.trim()}>
              <ShieldCheck size={15} /> {busy ? "Checking…" : "Unlock section"}
            </button>
          </form>

          {error ? <p className="gateError">{error}</p> : null}
        </div>
      </section>
    </div>
  );
}

export default { AccessProvider, AccessGate, useAccess };
