import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export default function Submit() {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!body.trim()) { setError('Requirement body is required.'); return; }
    setSubmitting(true);
    setError('');
    try {
      const result = await api.createTask(body.trim(), title.trim() || undefined);
      navigate(`/tasks/${result.task_id}`);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h1>Submit Requirement</h1>
      <form onSubmit={handleSubmit} className="card">
        <label style={{ display: 'block', marginBottom: 8, color: 'var(--text-muted)' }}>
          Title (optional)
        </label>
        <input
          type="text"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="Brief title..."
          style={{ marginBottom: 16 }}
        />

        <label style={{ display: 'block', marginBottom: 8, color: 'var(--text-muted)' }}>
          Requirement (Markdown)
        </label>
        <textarea
          rows={12}
          value={body}
          onChange={e => setBody(e.target.value)}
          placeholder="Describe what you want built..."
        />

        {error && <p style={{ color: 'var(--danger)', marginTop: 8 }}>{error}</p>}

        <div className="mt-2">
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? 'Submitting...' : 'Submit'}
          </button>
        </div>
      </form>
    </>
  );
}
