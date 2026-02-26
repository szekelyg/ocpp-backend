// frontend/src/components/ui/PayModal.jsx
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export default function PayModal({ open, onClose, busy, children }) {
  const panelRef = useRef(null);

  useEffect(() => {
    if (!open) return;

    // body scroll lock
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // ESC close
    const onKeyDown = (e) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);

    // fókusz a panelre
    setTimeout(() => panelRef.current?.focus(), 0);

    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose, busy]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[10000]"
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => {
        // backdrop click close (csak ha nem busy)
        if (!busy && e.target === e.currentTarget) onClose();
      }}
    >
      <div className="absolute inset-0 bg-black/60" />
      <div className="relative h-full w-full flex items-center justify-center p-4">
        <div
          ref={panelRef}
          tabIndex={-1}
          className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-950 p-5 shadow-xl outline-none"
        >
          {children}
        </div>
      </div>
    </div>,
    document.body
  );
}