import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Task, HealthStatus } from '../api'

function statusBadge(status: string) {
  const cls = status === 'done' ? 'badge-success'
    : status === 'failed' ? 'badge-danger'
    : status === 'running' ? 'badge-info'
    : 'badge-warning';
  return <span className={`badge ${cls}`}>{status}</span>;
}

export default function Dashboard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [pendingGates, setPendingGates] = useState(0);

  useEffect(() => {
    const load = () => {
      api.listTasks().then(setTasks).catch(console.error);
      api.health().then(setHealth).catch(console.error);
      api.listGates('pending').then(g => setPendingGates(g.length)).catch(console.error);
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const healthColor = health?.status === 'ok' ? 'var(--success)' : 'var(--warning)';

  return (
    <>
      <div className="flex justify-between items-center">
        <h1>Dashboard</h1>
        <div className="flex gap-2 items-center">
          {pendingGates > 0 && (
            <Link to="/approvals">
              <span className="badge badge-warning">{pendingGates} pending gate{pendingGates > 1 ? 's' : ''}</span>
            </Link>
          )}
          <span className="badge" style={{ background: healthColor + '22', color: healthColor }}>
            {health?.status || '...'}
          </span>
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Task ID</th>
              <th>Title</th>
              <th>Phase</th>
              <th>Status</th>
              <th>Agent</th>
            </tr>
          </thead>
          <tbody>
            {tasks.length === 0 && (
              <tr><td colSpan={5} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>No tasks yet</td></tr>
            )}
            {tasks.map(t => (
              <tr key={t.id}>
                <td><Link to={`/tasks/${t.id}`}>{t.id}</Link></td>
                <td>{t.title.slice(0, 60)}</td>
                <td><span className="badge badge-info">{t.phase}</span></td>
                <td>{statusBadge(t.status)}</td>
                <td style={{ color: 'var(--text-muted)' }}>{t.agent || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
