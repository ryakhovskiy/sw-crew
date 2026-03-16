import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Task } from '../api'

export default function History() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    api.listTasks().then(all => {
      setTasks(all.filter(t => t.status === 'done' || t.status === 'failed'));
    }).catch(console.error);
  }, []);

  const filtered = search
    ? tasks.filter(t => t.title.toLowerCase().includes(search.toLowerCase()))
    : tasks;

  return (
    <>
      <h1>History</h1>
      <div style={{ marginBottom: 16 }}>
        <input
          type="text"
          placeholder="Search tasks..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ padding: '8px 12px', width: '100%', maxWidth: 400, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg)', color: 'var(--text)' }}
        />
      </div>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Task ID</th>
              <th>Title</th>
              <th>Status</th>
              <th>Cost</th>
              <th>Completed</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={5} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>No completed tasks</td></tr>
            )}
            {filtered.map(t => (
              <tr key={t.id}>
                <td><Link to={`/tasks/${t.id}`}>{t.id}</Link></td>
                <td>{t.title.slice(0, 60)}</td>
                <td>
                  <span className={`badge ${t.status === 'done' ? 'badge-success' : 'badge-danger'}`}>
                    {t.status}
                  </span>
                </td>
                <td style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>${t.total_cost_usd?.toFixed(4) ?? '0.0000'}</td>
                <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                  {new Date(t.updated_at * 1000).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
