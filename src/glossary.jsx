/* Shared glossary context + info-tooltip, used by both main.jsx and
   analyticsViews.jsx's separate KpiCard implementations so a single
   /api/glossary fetch backs every ⓘ tooltip in the app. */

import React from "react";
import { Info } from "lucide-react";

export const GlossaryContext = React.createContext({});

export function useGlossaryMap() {
  return React.useContext(GlossaryContext);
}

export function InfoPopover({ infoKey }) {
  const map = React.useContext(GlossaryContext);
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  const term = infoKey ? map[infoKey] : null;

  React.useEffect(() => {
    if (!open) return;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  if (!term) return null;

  return (
    <span className="infoPopoverWrap" ref={ref}>
      <button
        type="button"
        className="infoIconBtn"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        title={term.name}
        aria-label={`About ${term.name}`}
      >
        <Info size={12} />
      </button>
      {open ? (
        <div className="infoPopover" onClick={(e) => e.stopPropagation()}>
          <strong>{term.name}</strong>
          <p>{term.definition}</p>
          {term.unit ? <div className="infoPopoverRow"><span>Unit</span><span>{term.unit}</span></div> : null}
          {term.source ? <div className="infoPopoverRow"><span>Source</span><span>{term.source}</span></div> : null}
          {term.calculation ? <div className="infoPopoverRow"><span>Calculation</span><span>{term.calculation}</span></div> : null}
          {term.significance ? <p className="infoPopoverSig">{term.significance}</p> : null}
        </div>
      ) : null}
    </span>
  );
}
