import Icon from './Icons';

export default function EmptyState({ icon = 'logs', title = 'Nothing here', message }) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">
        <Icon name={icon} size={28} />
      </div>
      <div className="empty-state-title">{title}</div>
      {message && <div className="empty-state-message">{message}</div>}
    </div>
  );
}
