// frontend/src/components/ui/PayModal.jsx
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export default function PayModal({ open, onClose, busy, children }) {
  const panelRef = useRef(null);

  // Scroll lock + fókusz: CSAK akkor fut, ha open változik (nem onClose/busy)
  // Ha ezt nem választjuk szét, akkor minden 5s-es parent re-render (ami új onClose
  // referenciát hoz létre) újrafuttatná az effectet és panelRef.focus() ellopná
  // a fókuszt az inputról.
  useEffect(() => {
    if (!open) return;

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const id = setTimeout(() => panelRef.current?.focus(), 0);

    return () => {
      clearTimeout(id);
      document.body.style.overflow = prevOverflow;
    };
  }, [open]);

  // ESC billentyű: külön effect, hogy onClose/busy változásra frissüljön
  // de NE indítsa újra a fókusz-logikát
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose, busy]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[10000]"
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => {
        if (!busy && e.target === e.currentTarget) onClose();
      }}
    >
      <div className="absolute inset-0 bg-black/60" />
      <div className="relative h-full w-full flex items-start justify-center p-4 overflow-y-auto">
        <div
          ref={panelRef}
          tabIndex={-1}
          className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-950 p-5 shadow-xl outline-none my-auto"
        >
          {children}
        </div>
      </div>
    </div>,
    document.body
  );
}
