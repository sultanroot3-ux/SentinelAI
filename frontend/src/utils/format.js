export function fmtDateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (isNaN(d.getTime())) return String(value);
  return d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

export function fmtDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString([], { dateStyle: 'medium' });
}

export function fmtScore(value) {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  return isNaN(n) ? String(value) : n.toFixed(2);
}

export function fmtPercent(value) {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  if (isNaN(n)) return String(value);
  return `${(n <= 1 ? n * 100 : n).toFixed(1)}%`;
}

export function titleCase(value) {
  if (!value) return '';
  return String(value)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
