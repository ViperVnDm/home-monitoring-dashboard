import { useState, useEffect } from 'react'
import ReactDOM from 'react-dom'

export default function SettingsModal({ onClose }) {
  const [form, setForm] = useState({ webhook_url: '', webhook_type: 'discord' })
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [message, setMessage] = useState(null)  // { text, ok }

  useEffect(() => {
    fetch('/api/settings')
      .then(r => r.json())
      .then(data => setForm({ webhook_url: data.webhook_url || '', webhook_type: data.webhook_type || 'discord' }))
      .catch(() => {})
  }, [])

  function handleChange(e) {
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))
    setMessage(null)
  }

  async function handleSave(e) {
    e.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setMessage({ text: 'Settings saved.', ok: true })
    } catch (err) {
      setMessage({ text: err.message, ok: false })
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    if (!form.webhook_url) {
      setMessage({ text: 'Enter a webhook URL first.', ok: false })
      return
    }
    setTesting(true)
    setMessage(null)
    try {
      const res = await fetch('/api/settings/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ webhook_url: form.webhook_url, webhook_type: form.webhook_type }),
      })
      const data = await res.json()
      setMessage({ text: data.message, ok: data.ok })
    } catch (err) {
      setMessage({ text: err.message, ok: false })
    } finally {
      setTesting(false)
    }
  }

  return ReactDOM.createPortal(
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-card" role="dialog" aria-modal="true">
        <div className="modal-header">
          <span className="modal-title">Alert Settings</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form onSubmit={handleSave}>
          <div className="modal-body">
            {message && (
              <div className={`message-strip ${message.ok ? 'success' : 'error'}`}>
                {message.text}
              </div>
            )}

            <div className="form-field">
              <label className="form-label">Webhook Type</label>
              <select
                className="form-select"
                name="webhook_type"
                value={form.webhook_type}
                onChange={handleChange}
              >
                <option value="discord">Discord</option>
                <option value="slack">Slack</option>
                <option value="generic">Generic (JSON POST)</option>
              </select>
            </div>

            <div className="form-field">
              <label className="form-label">Webhook URL</label>
              <input
                className="form-input"
                name="webhook_url"
                type="url"
                value={form.webhook_url}
                onChange={handleChange}
                placeholder="https://discord.com/api/webhooks/…"
              />
            </div>

            <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Alerts are sent when a service transitions between UP and DOWN states.
              Leave the URL blank to disable alerts.
            </p>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn-secondary"
              onClick={handleTest}
              disabled={testing || saving}
            >
              {testing ? 'Sending…' : 'Test'}
            </button>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={saving || testing}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  )
}
