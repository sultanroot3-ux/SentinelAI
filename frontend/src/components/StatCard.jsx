import Icon from './Icons';

export default function StatCard({ label, value, sub, icon, tone = 'accent' }) {
  return (
    <div className="stat-card card">
      <div className={`stat-card-icon tone-${tone}`}>
        <Icon name={icon} size={20} />
      </div>
      <div className="stat-card-body">
        <div className="stat-card-value">{value}</div>
        <div className="stat-card-label">{label}</div>
        {sub && <div className="stat-card-sub">{sub}</div>}
      </div>
    </div>
  );
}
