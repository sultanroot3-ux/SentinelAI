import { titleCase } from '../utils/format';

const VARIANT = {
  // case status
  open: 'warn',
  investigating: 'info',
  closed: 'ok',
  // priority
  low: 'muted',
  medium: 'info',
  high: 'warn',
  critical: 'danger',
  // unknown-face status
  new: 'info',
  reviewed: 'ok',
  case_opened: 'warn',
  // roles
  admin: 'accent',
  security_officer: 'info',
  receptionist: 'muted',
  it: 'ok',
  // notification levels
  info: 'info',
  warning: 'warn',
  alert: 'danger',
  // generic
  online: 'ok',
  offline: 'danger',
  yes: 'ok',
  no: 'muted',
};

export default function Badge({ value, variant, children }) {
  const v = variant || VARIANT[String(value).toLowerCase()] || 'muted';
  return <span className={`badge badge-${v}`}>{children ?? titleCase(value)}</span>;
}
