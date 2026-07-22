import { useMemo, useState } from 'react';
import Spinner from './Spinner';
import EmptyState from './EmptyState';

/**
 * Generic sortable table.
 * columns: [{ key, label, sortable=true, render?(row), width? }]
 */
export default function DataTable({
  columns,
  rows,
  keyField = 'id',
  loading = false,
  error = null,
  emptyTitle = 'No records',
  emptyMessage,
  onRowClick,
}) {
  const [sort, setSort] = useState(null); // { key, dir: 1 | -1 }

  const sorted = useMemo(() => {
    if (!sort || !rows) return rows || [];
    const { key, dir } = sort;
    return [...rows].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (av == null && bv == null) return 0;
      if (av == null) return dir;
      if (bv == null) return -dir;
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir;
    });
  }, [rows, sort]);

  const toggleSort = (col) => {
    if (col.sortable === false) return;
    setSort((s) =>
      s && s.key === col.key ? (s.dir === 1 ? { key: col.key, dir: -1 } : null) : { key: col.key, dir: 1 }
    );
  };

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                style={col.width ? { width: col.width } : undefined}
                className={col.sortable === false ? '' : 'sortable'}
                onClick={() => toggleSort(col)}
              >
                {col.label}
                {sort && sort.key === col.key && (
                  <span className="sort-arrow">{sort.dir === 1 ? ' ▲' : ' ▼'}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && (
            <tr>
              <td colSpan={columns.length} className="table-state">
                <Spinner />
              </td>
            </tr>
          )}
          {!loading && error && (
            <tr>
              <td colSpan={columns.length} className="table-state">
                <span className="error-text">{error}</span>
              </td>
            </tr>
          )}
          {!loading && !error && sorted.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="table-state">
                <EmptyState title={emptyTitle} message={emptyMessage} />
              </td>
            </tr>
          )}
          {!loading &&
            !error &&
            sorted.map((row) => (
              <tr
                key={row[keyField]}
                className={onRowClick ? 'clickable' : ''}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((col) => (
                  <td key={col.key}>{col.render ? col.render(row) : row[col.key] ?? '—'}</td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="pagination">
      <button className="btn btn-ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ← Prev
      </button>
      <span className="pagination-info">
        Page {page} of {pages} · {total} records
      </span>
      <button className="btn btn-ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next →
      </button>
    </div>
  );
}
