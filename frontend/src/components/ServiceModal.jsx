import { useState, useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'

const DEFAULT_FORM = {
  name: '',
  group_name: '',
  host: '',
  port: '',
  check_type: 'http',
  url: '',
}

function buildUrl(host, port, check_type) {
  if (check_type === 'tcp' || !host) return ''
  const portPart = port ? `:${port}` : ''
  return `${check_type}://${host}${portPart}`
}

export default function ServiceModal({ service, groups, onSaved, onClose }) {
  const isEdit = service != null
  const [form, setForm] = useState(DEFAULT_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  // Track if the user has manually edited the URL field
  const urlTouched = useRef(false)

  useEffect(() => {
    if (isEdit) {
      urlTouched.current = true  // Don't auto-fill when editing
      setForm({
        name: service.name || '',
        group_name: service.group_name || '',
        host: service.host || '',
        port: service.port != null ? String(service.port) : '',
        check_type: service.check_type || 'http',
        url: service.url || '',
      })
    } else {
      urlTouched.current = false
      setForm(DEFAULT_FORM)
    }
  }, [service, isEdit])

  function handleChange(e) {
    const { name, value } = e.target
    setForm(prev => {
      const next = { ...prev, [name]: value }

      // Auto-fill URL unless user has manually set it
      if (name === 'url') {
        urlTouched.current = value !== buildUrl(prev.host, prev.port, prev.check_type)
      } else if (!urlTouched.current) {
        const h = name === 'host' ? value : prev.host
        const p = name === 'port' ? value : prev.port
        const t = name === 'check_type' ? value : prev.check_type
        next.url = t === 'tcp' ? '' : buildUrl(h, p, t)
      }

      // Clear URL when switching to tcp
      if (name === 'check_type' && value === 'tcp') {
        next.url = ''
        urlTouched.current = false
      }

      return next
    })
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true)
    setError(null)

    const body = {
      name: form.name.trim(),
      group_name: form.group_name.trim() || 'General',
      host: form.host.trim(),
      port: form.port ? parseInt(form.port, 10) : null,
      check_type: form.check_type,
      url: form.check_type !== 'tcp' && form.url.trim() ? form.url.trim() : null,
    }

    try {
      const method = isEdit ? 'PUT' : 'POST'
      const url = isEdit ? `/api/services/${service.id}` : '/api/services'
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      onSaved()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return ReactDOM.createPortal(
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-card" role="dialog" aria-modal="true">
        <div className="modal-header">
          <span className="modal-title">{isEdit ? 'Edit Service' : 'Add Service'}</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && <div className="message-strip error">{error}</div>}

            <div className="form-row">
              <div className="form-field" style={{ flex: 2 }}>
                <label className="form-label">Name</label>
                <input
                  className="form-input"
                  name="name"
                  value={form.name}
                  onChange={handleChange}
                  required
                  placeholder="Plex Media Server"
                  autoFocus
                />
              </div>
              <div className="form-field" style={{ flex: 1 }}>
                <label className="form-label">Group</label>
                <input
                  className="form-input"
                  name="group_name"
                  value={form.group_name}
                  onChange={handleChange}
                  list="group-options"
                  placeholder="General"
                />
                <datalist id="group-options">
                  {groups.map(g => <option key={g} value={g} />)}
                </datalist>
              </div>
            </div>

            <div className="form-row">
              <div className="form-field" style={{ flex: 2 }}>
                <label className="form-label">Host / IP</label>
                <input
                  className="form-input"
                  name="host"
                  value={form.host}
                  onChange={handleChange}
                  required
                  placeholder="192.168.1.100"
                />
              </div>
              <div className="form-field" style={{ flex: 1 }}>
                <label className="form-label">Port</label>
                <input
                  className="form-input"
                  name="port"
                  type="number"
                  min="1"
                  max="65535"
                  value={form.port}
                  onChange={handleChange}
                  placeholder="8080"
                />
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Check Type</label>
              <select
                className="form-select"
                name="check_type"
                value={form.check_type}
                onChange={handleChange}
              >
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
                <option value="tcp">TCP</option>
              </select>
            </div>

            <div className="form-field">
              <label className="form-label">URL Override</label>
              <input
                className="form-input"
                name="url"
                value={form.url}
                onChange={handleChange}
                disabled={form.check_type === 'tcp'}
                placeholder={form.check_type === 'tcp' ? 'N/A for TCP checks' : 'Auto-filled from host + port'}
              />
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? 'Saving…' : isEdit ? 'Save Changes' : 'Add Service'}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  )
}
