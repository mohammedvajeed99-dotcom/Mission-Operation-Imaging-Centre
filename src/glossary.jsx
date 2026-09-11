/* Shared glossary context + info-tooltip, used by both main.jsx and
   analyticsViews.jsx's separate KpiCard implementations so a single
   /api/glossary fetch backs every ⓘ tooltip in the app. */

import React from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";

export const GlossaryContext = React.createContext({});

export function useGlossaryMap() {
  return React.useContext(GlossaryContext);
}

const POPOVER_WIDTH = 260;
const POPOVER_MARGIN = 12; // keep clear of the viewport edge, not flush against it

/* Was a plain absolutely-positioned child of the ⓘ icon (left: 0, fixed
   260px width) -- fine for an icon with open room to its right, but a KPI
   grid puts these icons everywhere including the last column, where the
   popover ran straight off the edge of its own card and (since KPI cards
   clip their content for the corner glow decoration) got silently cut off
   mid-sentence instead of overflowing visibly. Rendered into a portal at
   document.body with a position clamped to the viewport: it now always has
   somewhere valid to sit, regardless of which card or column it opens
   from, and is never clipped by an ancestor's overflow:hidden since it is
   no longer that ancestor's descendant in the DOM.

   Positioned below the whole KPI card, not just below the small ⓘ icon:
   the icon sits at the card's top-left next to its label, while a percent
   KPI's ring icon sits at the card's top-right (see KpiCard/RadialProgress
   in main.jsx) -- opening the popover directly under the icon put it
   right over that ring, the two glowing circles reading as one broken,
   overlapping mess rather than two separate pieces of UI. Anchoring on the
   card's own bottom edge instead means the popover always opens clear of
   everything else in the card, however that card happens to be laid out. */
// Only the horizontal axis was ever clamped to the viewport -- vertically it
// always anchored `top: cardRect.bottom + 8` with no floor check, so a card
// in the last row of a grid (bottom of the viewport, or just a short
// window) opened a popover whose lower half rendered off-screen with no way
// to scroll to it: not clipped invisibly, just placed somewhere the user
// could never reach.
//
// Fixed with a two-pass placement rather than a guessed height threshold,
// since different glossary terms have genuinely different content length
// (a bare definition vs. one with unit/source/calculation/significance all
// present) and a fixed cutoff would flip (or fail to flip) the wrong way
// for whichever terms don't match the guess:
//   Pass 1 (below `measure`): render the popover off-screen at its real
//   fixed width so its natural content height can be measured -- laid out
//   by the browser, never painted where the user could see it.
//   Pass 2 (below `place`): using that real height, pick whichever side of
//   the card (below or above) actually has enough room to show it in
//   full; if neither does, use the side with more room and cap the
//   popover's own max-height to fit, so the CSS overflow-y:auto safety net
//   (see .infoPopover in styles.css) scrolls the remainder internally
//   instead of it running off the viewport with no way to reach it.
function useClampedPosition(open, anchorRef, measureRef) {
  const [pos, setPos] = React.useState(null);

  const place = React.useCallback(() => {
    if (!anchorRef.current) return;
    // `th` matters as its own case, checked before the wider `.panel`
    // fallback: a table-header info icon (DataTable) sits inside a
    // `.panel` that can run to dozens of rows, and anchoring on the whole
    // panel's bottom edge would open the popover far below the header row
    // the icon is actually in, instead of right under it.
    const card = anchorRef.current.closest("th, .kpi, .panel, .icDetail, section") || anchorRef.current;
    const iconRect = anchorRef.current.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    const left = Math.min(
      Math.max(iconRect.left, POPOVER_MARGIN),
      window.innerWidth - POPOVER_WIDTH - POPOVER_MARGIN
    );
    const contentHeight = measureRef.current?.offsetHeight || 0;
    const spaceBelow = window.innerHeight - cardRect.bottom - 8 - POPOVER_MARGIN;
    const spaceAbove = cardRect.top - 8 - POPOVER_MARGIN;
    if (contentHeight <= spaceBelow || spaceBelow >= spaceAbove) {
      setPos({ top: cardRect.bottom + 8, left, maxHeight: Math.max(spaceBelow, 120) });
    } else {
      setPos({ bottom: window.innerHeight - cardRect.top + 8, left, maxHeight: Math.max(spaceAbove, 120) });
    }
  }, [anchorRef, measureRef]);

  React.useLayoutEffect(() => {
    if (!open || !anchorRef.current) {
      setPos(null);
      return;
    }
    // Pass 1: mount off-screen (fixed width, so its natural height doesn't
    // depend on where it ends up) purely so pass 2 can measure it. `place`
    // itself is stable (refs don't change identity) so this effect -- and
    // the resize/scroll listeners it owns -- isn't re-run by pass 2's own
    // setPos call below; only `open`/`anchorRef` changing tears it down.
    setPos({ top: -9999, left: -9999, measuring: true });
    // Reposition (not close) on scroll: the popover is `position: fixed`
    // so it doesn't move with the page on its own -- without this it would
    // drift away from the card it's anchored to as soon as the page
    // scrolled. An earlier version closed the popover outright on any
    // scroll instead, which was simpler but meant even an incidental
    // scroll -- one unrelated to the card, or just skimming further down
    // while still reading -- threw away what was open. Throttled with a
    // plain timer (not requestAnimationFrame, which browsers pause
    // entirely for a backgrounded/hidden tab -- a scroll that happens
    // while this tab isn't the visible one would otherwise never
    // reposition it) since scroll fires far more often than resize and
    // place() triggers a re-render each time it runs. `capture: true`
    // catches scrolling on any scrollable ancestor, not just window-level
    // scroll.
    let timer = null;
    const reflow = () => {
      if (timer != null) return;
      timer = setTimeout(() => {
        timer = null;
        place();
      }, 16); // ~60fps worth of coalescing, without depending on paint timing
    };
    window.addEventListener("resize", reflow);
    window.addEventListener("scroll", reflow, true);
    return () => {
      window.removeEventListener("resize", reflow);
      window.removeEventListener("scroll", reflow, true);
      if (timer != null) clearTimeout(timer);
    };
  }, [open, anchorRef, place]);

  React.useLayoutEffect(() => {
    // Pass 2: the off-screen copy from pass 1 is now laid out (this effect
    // runs after that render committed), so measureRef has a real height
    // to place from. Only fires once per open -- place()'s own setPos
    // clears `measuring`, so this is a no-op on the resulting re-render.
    if (pos?.measuring) place();
  }, [pos, place]);

  return pos;
}

export function InfoPopover({ infoKey, triggerRef, containerRef }) {
  const map = React.useContext(GlossaryContext);
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  const popoverRef = React.useRef(null);
  const term = infoKey ? map[infoKey] : null;
  const pos = useClampedPosition(open, ref, popoverRef);

  React.useEffect(() => {
    if (!open) return;
    const away = (e) => {
      // `containerRef`, when given, is the whole clickable card this icon
      // lives in (see KpiCard) -- a click anywhere else on that same card
      // is the card's own toggle, not a click "away" from the popover, so
      // it must not race this handler into closing what the card's own
      // click is about to re-open (that race made the card-body click
      // that should CLOSE an open popover instead flicker it straight back
      // open: this handler closed it on mousedown, then the click that
      // followed reopened it).
      if (containerRef?.current && containerRef.current.contains(e.target)) return;
      if (ref.current && !ref.current.contains(e.target) && !e.target.closest(".infoPopover")) setOpen(false);
    };
    // Scrolling used to close the popover outright (see useClampedPosition's
    // own scroll listener, which now repositions it instead) -- only a
    // real click away from the card, or the toggle button itself, closes it.
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  if (!term) return null;

  return (
    <span className="infoPopoverWrap" ref={ref}>
      <button
        ref={triggerRef}
        type="button"
        className="infoIconBtn"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        title={term.name}
        aria-label={`About ${term.name}`}
      >
        <Info size={12} />
      </button>
      {open && pos
        ? createPortal(
            <div
              ref={popoverRef}
              className="infoPopover infoPopoverPortal"
              style={{
                top: pos.top,
                bottom: pos.bottom,
                left: pos.left,
                width: POPOVER_WIDTH,
                maxHeight: pos.maxHeight,
                // Pass 1 (see useClampedPosition) needs this laid out to
                // measure its real height, but never actually visible --
                // it sits off-screen at (-9999,-9999) already, this just
                // belt-and-suspenders against any layout that would
                // otherwise make it visible mid-measurement.
                visibility: pos.measuring ? "hidden" : "visible",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <strong>{term.name}</strong>
              <p>{term.definition}</p>
              {term.unit ? <div className="infoPopoverRow"><span>Unit</span><span>{term.unit}</span></div> : null}
              {term.source ? <div className="infoPopoverRow"><span>Source</span><span>{term.source}</span></div> : null}
              {term.calculation ? <div className="infoPopoverRow"><span>Calculation</span><span>{term.calculation}</span></div> : null}
              {term.significance ? <p className="infoPopoverSig">{term.significance}</p> : null}
            </div>,
            document.body
          )
        : null}
    </span>
  );
}
