import { useEffect, useState } from 'react'
import { api, HealthStatus } from '../api'

function StatusCard({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="card" style={{ display: 'inline-block', minWidth: 140, margin: 8, textAlign: 'center' }}>
      <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: 4 }}>{label}</div>
      <span className={`badge ${ok ? 'badge-success' : 'badge-danger'}`}>
        {ok ? 'OK' : 'DOWN'}
      </span>
    </div>
  )
}

function CbBadge({ state }: { state: string }) {
  const cls = state === 'closed' ? 'badge-success' : state === 'open' ? 'badge-danger' : 'badge-warning';
  return <span className={`badge ${cls}`}>{state}</span>;
}

function formatUptime(seconds: number) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}h ${m}m ${s}s`;
}

export default function Health() {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    const load = () => api.health().then(setHealth).catch(console.error);
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  if (!health) return <p style={{ marginTop: 24 }}>Loading...</p>;

  const cbEntries = Object.entries(health.circuit_breakers || {});

  return (
    <>
      <h1>System Health</h1>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        <StatusCard label="Gateway" ok={health.gateway} />
        <StatusCard label="Orchestrator" ok={health.orchestrator} />
        <StatusCard label="Database" ok={health.database} />
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2>Metrics</h2>
        <table>
          <tbody>
            <tr><td style={{ color: 'var(--text-muted)' }}>Uptime</td><td>{formatUptime(health.uptime_seconds)}</td></tr>
            <tr><td style={{ color: 'var(--text-muted)' }}>Queue Depth</td><td>{health.queue_depth}</td></tr>
            <tr><td style={{ color: 'var(--text-muted)' }}>Active Agents</td><td>{health.active_agents?.length ? health.active_agents.join(', ') : 'none'}</td></tr>
            <tr><td style={{ color: 'var(--text-muted)' }}>Tasks Completed</td><td>{health.tasks_completed}</td></tr>
            <tr><td style={{ color: 'var(--text-muted)' }}>Tasks Failed</td><td>{health.tasks_failed}</td></tr>
            <tr><td style={{ color: 'var(--text-muted)' }}>Total Cost</td><td style={{ fontFamily: 'monospace' }}>${health.total_cost_usd?.toFixed(4) ?? '0.0000'}</td></tr>
          </tbody>
        </table>
      </div>

      {cbEntries.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Circuit Breakers</h2>
          <table>
            <thead>
              <tr><th>Agent</th><th>State</th></tr>
            </thead>
            <tbody>
              {cbEntries.map(([name, state]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td><CbBadge state={state} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
