import { useEffect, useState } from 'react'
import { api, GateInfo } from '../api'

export default function Approvals() {
  const [gates, setGates] = useState<GateInfo[]>([]);
  const [comment, setComment] = useState('');
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState('');
  const [activeGate, setActiveGate] = useState<string | null>(null);

  const load = () => {
    api.listGates('pending').then(setGates).catch(console.error);
  };
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, []);

  const handleApprove = async (gateId: string) => {
    await api.approveGate(gateId, comment || undefined);
    setComment('');
    setActiveGate(null);
    load();
  };

  const handleReject = async (gateId: string) => {
    if (!reason.trim()) return;
    await api.rejectGate(gateId, reason.trim());
    setReason('');
    setActiveGate(null);
    load();
  };

  const handleAnswer = async (gateId: string) => {
    if (!message.trim()) return;
    await api.answerGate(gateId, message.trim());
    setMessage('');
    setActiveGate(null);
    load();
  };

  return (
    <>
      <h1>Approvals Inbox</h1>
      {gates.length === 0 && (
        <div className="card" style={{ color: 'var(--text-muted)', textAlign: 'center' }}>
          No pending gates
        </div>
      )}
      {gates.map(g => (
        <div key={g.id} className="card">
          <div className="flex justify-between items-center mb-2">
            <div>
              <span className="badge badge-warning">{g.type}</span>
              <span style={{ marginLeft: 12, color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Task: {g.task_id}
              </span>
            </div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
              {new Date(g.created_at * 1000).toLocaleString()}
            </span>
          </div>

          {g.question && (
            <p style={{ margin: '8px 0', fontSize: '0.95rem' }}>{g.question}</p>
          )}

          {g.artifact && (
            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
              Artifact: {g.artifact}
            </p>
          )}

          {activeGate === g.id ? (
            <div className="mt-2">
              {g.type === 'escalation' ? (
                <>
                  <textarea
                    rows={3}
                    value={message}
                    onChange={e => setMessage(e.target.value)}
                    placeholder="Your answer..."
                  />
                  <div className="flex gap-2 mt-1">
                    <button className="btn-primary" onClick={() => handleAnswer(g.id)}>Send Answer</button>
                    <button onClick={() => setActiveGate(null)}>Cancel</button>
                  </div>
                </>
              ) : (
                <>
                  <input
                    type="text"
                    value={comment}
                    onChange={e => setComment(e.target.value)}
                    placeholder="Comment (optional)..."
                    style={{ marginBottom: 8 }}
                  />
                  <input
                    type="text"
                    value={reason}
                    onChange={e => setReason(e.target.value)}
                    placeholder="Rejection reason..."
                    style={{ marginBottom: 8 }}
                  />
                  <div className="flex gap-2">
                    <button className="btn-success" onClick={() => handleApprove(g.id)}>Approve</button>
                    <button className="btn-danger" onClick={() => handleReject(g.id)} disabled={!reason.trim()}>Reject</button>
                    <button onClick={() => setActiveGate(null)}>Cancel</button>
                  </div>
                </>
              )}
            </div>
          ) : (
            <div className="mt-1">
              <button onClick={() => setActiveGate(g.id)}>Review</button>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
