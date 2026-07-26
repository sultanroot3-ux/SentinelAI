import Icon from './Icons';

export default function StatCard({ label, value, sub, icon, tone = 'accent', title }) {
  return (
    <div className="stat-card card" title={title}>
      {/* Decorative: the adjacent label already names the statistic. */}
      <div className={`stat-card-icon tone-${tone}`} aria-hidden="true">
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
