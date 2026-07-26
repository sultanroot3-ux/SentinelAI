import { useEffect, useId, useRef } from 'react';
import Icon from './Icons';

/* Elements that can receive keyboard focus inside the dialog. */
const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export default function Modal({ open, title, onClose, children, footer, wide = false }) {
  const dialogRef = useRef(null);
  const titleId = useId();
  /* The element focused before opening, so focus can be restored on close. */
  const restoreFocusRef = useRef(null);

  useEffect(() => {
    if (!open) return;

    restoreFocusRef.current = document.activeElement;

    /* Move focus into the dialog. Without this, focus stays on the page behind
       and a screen-reader user is never told a dialog opened. */
    const node = dialogRef.current;
    const first = node?.querySelector(FOCUSABLE);
    (first ?? node)?.focus();

    const onKey = (e) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;

      /* Focus trap: aria-modal alone does not stop Tab from walking into the
         page behind the overlay, which leaves keyboard users stranded. */
      const items = Array.from(node?.querySelectorAll(FOCUSABLE) ?? []).filter(
        (el) => el.offsetParent !== null || el === document.activeElement
      );
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      if (e.shiftKey && document.activeElement === firstItem) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && document.activeElement === lastItem) {
        e.preventDefault();
        firstItem.focus();
      }
    };

    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      /* Return focus to whatever opened the dialog. */
      const target = restoreFocusRef.current;
      if (target && typeof target.focus === 'function' && document.contains(target)) {
        target.focus();
      }
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={dialogRef}
        className={`modal ${wide ? 'modal-wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className="modal-header">
          <h3 id={titleId}>{title}</h3>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close dialog">
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}
