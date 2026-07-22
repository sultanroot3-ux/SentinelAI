import { useCallback, useEffect, useState } from 'react';
import { api, asPage } from '../api/client';
import Badge from '../components/Badge';
import Spinner from '../components/Spinner';
import EmptyState from '../components/EmptyState';
import Icon from '../components/Icons';
import { useToast } from '../components/Toast';
import { fmtDateTime } from '../utils/format';

export default function Notifications() {
  const toast = useToast();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [items, setItems] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get('/api/notifications', { unread_only: unreadOnly ? true : undefined })
      .then((d) => setItems(asPage(d).items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [unreadOnly]);

  useEffect(load, [load]);

  const markRead = async (n) => {
    try {
      await api.put(`/api/notifications/${n.id}/read`);
      setItems((list) => list.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
    } catch (e) {
      toast(e.message, 'error');
    }
  };

  const markAllRead = async () => {
    try {
      await api.put('/api/notifications/read-all');
      toast('All notifications marked as read', 'success');
      load();
    } catch (e) {
      toast(e.message, 'error');
    }
  };

  const unreadCount = (items || []).filter((n) => !n.read).length;

  return (
    <div className="page">
      <div className="card pad">
        <div className="filter-row space-between">
          <div className="tab-row inline-tabs">
            <button className={`tab ${!unreadOnly ? 'active' : ''}`} onClick={() => setUnreadOnly(false)}>
              All
            </button>
            <button className={`tab ${unreadOnly ? 'active' : ''}`} onClick={() => setUnreadOnly(true)}>
              Unread
            </button>
          </div>
          <button className="btn btn-secondary" onClick={markAllRead} disabled={unreadCount === 0}>
            <Icon name="check" size={15} /> Mark all read
          </button>
        </div>

        {loading ? (
          <div className="fullpage-loading">
            <Spinner />
          </div>
        ) : error ? (
          <div className="error-text">{error}</div>
        ) : !items || items.length === 0 ? (
          <EmptyState
            icon="bell"
            title="No notifications"
            message={unreadOnly ? 'You are all caught up.' : 'System alerts will appear here.'}
          />
        ) : (
          <ul className="notif-list">
            {items.map((n) => (
              <li key={n.id} className={`notif-item ${n.read ? '' : 'unread'}`}>
                <div className="notif-main">
                  <div className="notif-head">
                    <Badge value={n.level} />
                    <strong>{n.title}</strong>
                    {!n.read && <span className="unread-dot" title="Unread" />}
                  </div>
                  <p className="notif-message">{n.message}</p>
                  <span className="muted-text">{fmtDateTime(n.created_at)}</span>
                </div>
                {!n.read && (
                  <button className="btn btn-ghost btn-sm" onClick={() => markRead(n)}>
                    Mark read
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
