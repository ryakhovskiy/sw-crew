import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Task } from '../api'

export default function History() {
  const [tasks, setTasks] = useState<Task[]>([]);

  useEffect(() => {
    api.listTasks().then(all => {
      setTasks(all.filter(t => t.status === 'done' || t.status === 'failed'));
    }).catch(console.error);
  }, []);

  return (
    <>
      <h1>History</h1>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Task ID</th>
              <th>Title</th>
              <th>Status</th>
              <th>Completed</th>
            </tr>
          </thead>
          <tbody>
            {tasks.length === 0 && (
              <tr><td colSpan={4} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>No completed tasks</td></tr>
            )}
            {tasks.map(t => (
              <tr key={t.id}>
                <td><Link to={`/tasks/${t.id}`}>{t.id}</Link></td>
                <td>{t.title.slice(0, 60)}</td>
                <td>
                  <span className={`badge ${t.status === 'done' ? 'badge-success' : 'badge-danger'}`}>
                    {t.status}
                  </span>
                </td>
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
