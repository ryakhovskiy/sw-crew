import { useEffect, useState, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api, TaskDetail as TaskDetailType } from '../api'

const PHASES = ['INTAKE', 'BUILD', 'TEST_LOOP', 'DEPLOY', 'DONE'];

function PhaseTimeline({ current }: { current: string }) {
  const idx = PHASES.indexOf(current);
  const failed = current === 'FAILED';

  return (
    <div className="timeline">
      {PHASES.map((p, i) => {
        let cls = 'timeline-step';
        if (failed && i === idx) cls += ' failed';
        else if (i < idx || current === 'DONE') cls += ' done';
        else if (i === idx) cls += ' active';
        return (
          <span key={p}>
            {i > 0 && <span className="timeline-arrow"> → </span>}
            <span className={cls}>{p}</span>
          </span>
        );
      })}
      {failed && <span className="timeline-step failed">FAILED</span>}
    </div>
  );
}

export default function TaskDetail() {
  const { taskId } = useParams<{ taskId: string }>();
  const [task, setTask] = useState<TaskDetailType | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!taskId) return;
    api.getTask(taskId).then(setTask).catch(console.error);
    const interval = setInterval(() => {
      api.getTask(taskId).then(setTask).catch(console.error);
    }, 3000);
    return () => clearInterval(interval);
  }, [taskId]);

  // SSE stream
  useEffect(() => {
    if (!taskId) return;
    const token = localStorage.getItem('crew_token') || 'change-me';
    const es = new EventSource(`/stream/${taskId}?token=${token}`);

    const handler = (e: MessageEvent) => {
      setLogs(prev => [...prev, `[${e.type}] ${e.data}`]);
      logRef.current?.scrollTo(0, logRef.current.scrollHeight);
    };

    // We can't set auth headers on EventSource, so we rely on query param fallback
    // or the token being in the URL. For proper auth, use fetch-based SSE.
    es.addEventListener('phase:change', handler);
    es.addEventListener('agent:log', handler);
    es.addEventListener('gate:pending', handler);
    es.addEventListener('task:done', handler);
    es.addEventListener('task:failed', handler);
    es.addEventListener('stream:end', () => es.close());
    es.onerror = () => es.close();

    return () => es.close();
  }, [taskId]);

  if (!task) return <p style={{ marginTop: 24 }}>Loading...</p>;

  return (
    <>
      <div className="flex justify-between items-center">
        <h1>{task.title}</h1>
        <span className={`badge ${task.status === 'done' ? 'badge-success' : task.status === 'failed' ? 'badge-danger' : 'badge-info'}`}>
          {task.status}
        </span>
      </div>

      <PhaseTimeline current={task.phase} />

      <div className="card">
        <h2>Details</h2>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
          Agent: {task.agent || 'none'} &middot; Debug attempts: {task.debug_attempts}
        </p>
        <pre style={{ whiteSpace: 'pre-wrap', marginTop: 8, fontSize: '0.9rem' }}>
          {task.body}
        </pre>
      </div>

      {task.artifacts.length > 0 && (
        <div className="card">
          <h2>Artifacts</h2>
          <ul style={{ listStyle: 'none' }}>
            {task.artifacts.map(a => (
              <li key={a.name} style={{ padding: '4px 0' }}>
                <a href={`/tasks/${task.id}/artifacts/${a.name}`} target="_blank" rel="noreferrer">
                  {a.name}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {task.gates.length > 0 && (
        <div className="card">
          <h2>Gates</h2>
          <table>
            <thead>
              <tr><th>Type</th><th>Status</th><th>Question</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {task.gates.map(g => (
                <tr key={g.id}>
                  <td>{g.type}</td>
                  <td>
                    <span className={`badge ${g.status === 'approved' ? 'badge-success' : g.status === 'rejected' ? 'badge-danger' : g.status === 'pending' ? 'badge-warning' : 'badge-info'}`}>
                      {g.status}
                    </span>
                  </td>
                  <td style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                    {g.question?.slice(0, 80) || '-'}
                  </td>
                  <td>
                    {g.status === 'pending' && (
                      <Link to="/approvals" className="btn" style={{ fontSize: '0.8rem' }}>
                        Review
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <h2>Live Log</h2>
        <div className="log-stream" ref={logRef}>
          {logs.length === 0 && (
            <div style={{ color: 'var(--text-muted)' }}>Waiting for events...</div>
          )}
          {logs.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      </div>
    </>
  );
}
