import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import ServiceModal from './components/ServiceModal'
import SettingsModal from './components/SettingsModal'

// ── Utilities ──────────────────────────────────────────────────────────────

function groupBy(arr, key) {
  return arr.reduce((acc, item) => {
    const g = item[key] || 'General'
    if (!acc[g]) acc[g] = []
    acc[g].push(item)
    return acc
  }, {})
}

function fmtMs(ms) {
  if (ms == null) return '—'
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

function fmtPct(pct) {
  if (pct == null) return '—'
  return `${pct.toFixed(pct === 100 ? 0 : 1)}%`
}

function uptimeClass(pct) {
  if (pct == null) return 'neutral'
  if (pct >= 99)   return 'up'
  if (pct >= 95)   return 'partial'
  return 'down'
}

function fmtHour(hourStr) {
  const d = new Date(hourStr + 'Z')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' '
    + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

function fmtDuration(startIso, endIso) {
  const start = new Date(startIso + 'Z')
  const end = endIso ? new Date(endIso + 'Z') : new Date()
  const secs = Math.floor((end - start) / 1000)
  if (secs < 60) return `${secs}s`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  const remMins = mins % 60
  return remMins > 0 ? `${hrs}h ${remMins}m` : `${hrs}h`
}

function fmtRemaining(secs) {
  if (!secs || secs <= 0) return ''
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m`
  return `${Math.floor(secs / 3600)}h`
}

// ── Per-service pause button ────────────────────────────────────────────────

const PAUSE_DURATIONS = [
  { label: '5 minutes', seconds: 5 * 60 },
  { label: '1 hour',    seconds: 60 * 60 },
  { label: '1 day',     seconds: 24 * 60 * 60 },
]

function ServicePauseButton({ service, onPause, onResume }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const btnRef = useRef(null)
  const dropRef = useRef(null)

  function handleToggle() {
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      // Align dropdown right-edge to button right-edge; clamp so it never exits viewport
      const DROPDOWN_W = 160
      setPos({
        top: rect.bottom + 4,
        left: Math.max(8, rect.right - DROPDOWN_W),
      })
    }
    setOpen(o => !o)
  }

  useEffect(() => {
    if (!open) return
    function handle(e) {
      if (btnRef.current?.contains(e.target) || dropRef.current?.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [open])

  const isPaused = service.paused === true
  const remaining = service.paused_remaining_seconds || 0

  const dropdown = open ? createPortal(
    <div
      ref={dropRef}
      className="svc-pause-dropdown"
      style={{ position: 'fixed', top: pos.top, left: pos.left }}
    >
      {isPaused && (
        <>
          <button
            className="pause-dropdown-item resume"
            onClick={() => { onResume(service.id); setOpen(false) }}
          >
            Resume now
          </button>
          <div className="pause-dropdown-sep" />
        </>
      )}
      <div className="pause-dropdown-label">{isPaused ? 'Extend pause:' : 'Pause for:'}</div>
      {PAUSE_DURATIONS.map(d => (
        <button
          key={d.seconds}
          className="pause-dropdown-item"
          onClick={() => { onPause(service.id, d.seconds); setOpen(false) }}
        >
          {d.label}
        </button>
      ))}
    </div>,
    document.body
  ) : null

  return (
    <div className="svc-pause-wrap">
      <button
        ref={btnRef}
        className={`icon-btn${isPaused ? ' svc-paused' : ''}`}
        onClick={handleToggle}
        title={isPaused ? `Paused \u2014 ${fmtRemaining(remaining)} remaining` : 'Pause checks for this service'}
      >
        {isPaused ? '\u25B6' : '\u23F8'}
      </button>
      {dropdown}
    </div>
  )
}

// ── Sparkline ───────────────────────────────────────────────────────────────

function Sparkline({ data }) {
  if (!data || data.length === 0) {
    return <div className="sparkline-cell" />
  }

  const W = 120, H = 28
  const maxMs = Math.max(...data.map(d => d.avg_ms || 0), 1)
  const pts = data.map((d, i) => {
    const x = (i / Math.max(data.length - 1, 1)) * W
    const y = d.avg_ms != null ? H - (d.avg_ms / maxMs) * (H - 4) : H
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')

  return (
    <div className="sparkline-cell">
      <svg className="sparkline" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {data.map((d, i) => {
          const x = (i / Math.max(data.length - 1, 1)) * W
          return (
            <circle
              key={i}
              cx={x}
              cy={d.avg_ms != null ? H - (d.avg_ms / maxMs) * (H - 4) : H}
              r="1.5"
              fill={d.up === false ? 'var(--red)' : 'var(--green)'}
              opacity="0.7"
            />
          )
        })}
        {pts.includes(' ') && (
          <polyline
            points={pts}
            fill="none"
            stroke="var(--blue)"
            strokeWidth="1.2"
            opacity="0.6"
          />
        )}
      </svg>
    </div>
  )
}

// ── Incident panel ──────────────────────────────────────────────────────────

function IncidentPanel({ incidents }) {
  if (incidents == null) {
    return (
      <div className="incident-panel">
        <div className="incident-panel-title">Incident History</div>
        <div className="incident-panel-empty">Loading…</div>
      </div>
    )
  }
  if (incidents.length === 0) {
    return (
      <div className="incident-panel">
        <div className="incident-panel-title">Incident History</div>
        <div className="incident-panel-empty">No incidents recorded.</div>
      </div>
    )
  }
  return (
    <div className="incident-panel">
      <div className="incident-panel-title">Incident History</div>
      {incidents.map(inc => {
        const ongoing = inc.recovered_at == null
        const isManual = inc.note != null
        const badgeClass = isManual ? 'disabled' : (ongoing ? 'ongoing' : 'resolved')
        const badgeLabel = isManual
          ? inc.note
          : (ongoing ? 'Ongoing' : 'Resolved')
        return (
          <div key={inc.id} className="incident-row">
            <span className={`incident-badge ${badgeClass}`}>{badgeLabel}</span>
            <span className="incident-time">{fmtHour(inc.started_at)}</span>
            {!ongoing && (
              <span className="incident-time">→ {fmtHour(inc.recovered_at)}</span>
            )}
            <span className="incident-duration">
              {fmtDuration(inc.started_at, inc.recovered_at)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── Service row ────────────────────────────────────────────────────────────

function serviceLink(svc) {
  if (svc.check_type === 'tcp') return null
  return svc.url || `${svc.check_type}://${svc.host}${svc.port ? ':' + svc.port : ''}`
}

function ServiceRow({ service, sparklineData, onEdit, onDelete, incidents, incidentExpanded, onToggleIncident, onToggleEnabled, onPauseService, onResumeService }) {
  const raw = service.current_status
  const status = raw === 1 ? 'up' : raw === 0 ? 'down' : 'unknown'
  const link = serviceLink(service)
  const hostText = `${service.host}${service.port ? ':' + service.port : ''}`
  const isEnabled = service.enabled !== 0
  const isPaused = service.paused === true

  return (
    <div className={`service-row-wrapper${isEnabled ? '' : ' service-disabled'}`}>
      <div className="service-row">
        <div className="service-info">
          <div className="service-name">
            <span className={`status-dot ${status}`} />
            {service.name}
          </div>
          {link
            ? <a className="service-host service-host-link" href={link} target="_blank" rel="noopener noreferrer">{hostText}</a>
            : <div className="service-host">{hostText}</div>
          }
        </div>

        <div className="service-enabled-wrap">
          <input
            type="checkbox"
            className="service-toggle"
            checked={isEnabled}
            onChange={() => onToggleEnabled(service)}
            title={isEnabled ? 'Disable monitoring' : 'Enable monitoring'}
          />
        </div>

        <div className="service-metrics">
          <div className="metric">
            <div className="metric-label">Status</div>
            {isPaused ? (
              <div className="metric-value svc-paused-label">
                &#x23F8; {fmtRemaining(service.paused_remaining_seconds)}
              </div>
            ) : (
              <div className={`metric-value ${status}`}>
                {status === 'up' ? 'UP' : status === 'down' ? 'DOWN' : '—'}
              </div>
            )}
          </div>
          <div className="metric">
            <div className="metric-label">Response</div>
            <div className="metric-value neutral">{fmtMs(service.current_response_ms)}</div>
          </div>
          <div className="metric">
            <div className="metric-label">7d Uptime</div>
            <div className={`metric-value ${uptimeClass(service.uptime_7d)}`}>
              {fmtPct(service.uptime_7d)}
            </div>
          </div>
        </div>

        <Sparkline data={sparklineData} />

        <div className="service-actions">
          <ServicePauseButton
            service={service}
            onPause={onPauseService}
            onResume={onResumeService}
          />
          <button
            className={`icon-btn ${incidentExpanded ? 'active' : ''}`}
            onClick={onToggleIncident}
            title="Incident history"
          >
            &#x23F1;
          </button>
          <button className="icon-btn" onClick={onEdit} title="Edit service">
            &#x270E;
          </button>
          <button className="icon-btn danger" onClick={onDelete} title="Delete service">
            &#x2715;
          </button>
        </div>
      </div>

      {incidentExpanded && <IncidentPanel incidents={incidents} />}
    </div>
  )
}

// ── Service group ──────────────────────────────────────────────────────────

function ServiceGroup({ name, services, sparklines, onEdit, onDelete, incidentCache, expandedIncidents, onToggleIncident, onToggleEnabled, onPauseService, onResumeService }) {
  return (
    <div className="group">
      <div className="group-header">
        <span className="group-title">{name}</span>
        <div className="group-line" />
      </div>
      <div className="group-card">
        {services.map(svc => (
          <ServiceRow
            key={svc.id}
            service={svc}
            sparklineData={sparklines[svc.id]}
            onEdit={() => onEdit(svc)}
            onDelete={() => onDelete(svc)}
            incidents={incidentCache[svc.id]}
            incidentExpanded={expandedIncidents.has(svc.id)}
            onToggleIncident={() => onToggleIncident(svc.id)}
            onToggleEnabled={() => onToggleEnabled(svc)}
            onPauseService={onPauseService}
            onResumeService={onResumeService}
          />
        ))}
      </div>
    </div>
  )
}

// ── Header ─────────────────────────────────────────────────────────────────

function Header({ lastUpdated, onRefresh, refreshing, onAddService, onSettings, sseConnected, statusSummary, onImport, importMsg }) {
  const [clock, setClock] = useState(new Date())

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const allUp = statusSummary.total > 0 && statusSummary.up === statusSummary.total

  return (
    <header className="header">
      <div className="header-left">
        <span className="header-icon">&#x1F3E0;</span>
        <span className="header-title">Home Monitor</span>
        {statusSummary.total > 0 && (
          <span className={`status-summary ${allUp ? 'all-up' : 'some-down'}`}>
            {statusSummary.up}/{statusSummary.total} up
          </span>
        )}
      </div>
      <div className="header-right">
        <div className="sse-indicator">
          <span className={`sse-dot ${sseConnected ? 'connected' : ''}`} />
          <span className="sse-label">{sseConnected ? 'Live' : 'Polling'}</span>
        </div>
        {lastUpdated && (
          <span className="header-clock">
            Updated {lastUpdated.toLocaleTimeString()}
          </span>
        )}
        <span className="header-clock">
          {clock.toLocaleTimeString()}
        </span>
        <button className="refresh-btn" disabled={refreshing} onClick={onRefresh}>
          {refreshing ? 'Refreshing…' : '\u21BB Refresh'}
        </button>
        <a className="export-btn" href="/api/export" download="services.csv" title="Export as CSV">
          &#x2193; CSV
        </a>
        <a className="export-btn" href="/api/export/config" download="home-monitor-config.json" title="Export config for migration">
          &#x2193; JSON
        </a>
        <button className="export-btn" onClick={onImport} title="Import config from JSON file">
          &#x2191; Import
        </button>
        {importMsg && (
          <span className={`import-msg ${importMsg.ok ? 'success' : 'error'}`}>
            {importMsg.text}
          </span>
        )}
        <button className="add-service-btn" onClick={onAddService}>
          + Add Service
        </button>
        <button className="settings-btn" onClick={onSettings} title="Alert settings">
          &#x2699;
        </button>
      </div>
    </header>
  )
}

// ── App ────────────────────────────────────────────────────────────────────

const GROUP_ORDER = ['Plex NR Server', 'Network', 'NickPi5A', 'NICKPI5A', 'NickPi5B', 'NICKPI5B']

export default function App() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [importMsg, setImportMsg] = useState(null)
  const importRef = useRef(null)

  const [modalService, setModalService] = useState(undefined)  // undefined=closed, null=add, obj=edit
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [sparklines, setSparklines] = useState({})
  const [expandedIncidents, setExpandedIncidents] = useState(new Set())
  const [incidentCache, setIncidentCache] = useState({})
  const [sseConnected, setSseConnected] = useState(false)
  const eventSourceRef = useRef(null)

  // Countdown ticker — runs only when at least one service is paused
  const anyPaused = data.some(s => s.paused)
  useEffect(() => {
    if (!anyPaused) return
    const t = setInterval(() => {
      setData(prev => prev.map(s => {
        if (!s.paused) return s
        const rem = Math.max(0, (s.paused_remaining_seconds || 0) - 1)
        return rem === 0
          ? { ...s, paused: false, paused_remaining_seconds: 0 }
          : { ...s, paused_remaining_seconds: rem }
      }))
    }, 1000)
    return () => clearInterval(t)
  }, [anyPaused])

  const fetchData = useCallback(async (isManual = false) => {
    if (isManual) setRefreshing(true)
    try {
      const res = await fetch('/api/uptime')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setLastUpdated(new Date())
      setError(null)
      return json
    } catch (e) {
      setError(e.message)
      return null
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  async function loadSparklines(services) {
    const results = await Promise.allSettled(
      services.map(s =>
        fetch(`/api/services/${s.id}/sparkline`)
          .then(r => r.json())
          .then(d => ({ id: s.id, data: d }))
      )
    )
    setSparklines(
      Object.fromEntries(
        results
          .filter(r => r.status === 'fulfilled')
          .map(r => [r.value.id, r.value.data])
      )
    )
  }

  function connectSSE() {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }
    const es = new EventSource('/api/events')
    es.onopen = () => setSseConnected(true)
    es.onmessage = (e) => {
      try {
        const { type, data: payload } = JSON.parse(e.data)
        if (type === 'check_result' || type === 'service_updated') {
          setData(prev => prev.map(s =>
            s.id === payload.id ? { ...s, ...payload } : s
          ))
        }
      } catch {}
    }
    es.onerror = () => {
      es.close()
      setSseConnected(false)
      setTimeout(() => {
        fetchData()
        connectSSE()
      }, 5000)
    }
    eventSourceRef.current = es
  }

  useEffect(() => {
    fetchData().then(services => {
      if (services) loadSparklines(services)
    })

    connectSSE()

    // Refresh uptime buckets every minute (SSE handles live status patches)
    const uptimeInterval = setInterval(() => fetchData(), 60_000)
    // Refresh sparklines every 5 minutes
    const sparklineInterval = setInterval(() => {
      setData(curr => {
        if (curr.length) loadSparklines(curr)
        return curr
      })
    }, 5 * 60_000)

    return () => {
      clearInterval(uptimeInterval)
      clearInterval(sparklineInterval)
      if (eventSourceRef.current) eventSourceRef.current.close()
    }
  }, [fetchData])  // eslint-disable-line react-hooks/exhaustive-deps

  function handleImportClick() {
    importRef.current.value = ''
    importRef.current.click()
  }

  async function handleImportFile(e) {
    const file = e.target.files[0]
    if (!file) return
    try {
      const text = await file.text()
      const body = JSON.parse(text)
      const res = await fetch('/api/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const { imported, skipped } = await res.json()
      setImportMsg({ ok: true, text: `Imported ${imported} service${imported !== 1 ? 's' : ''}${skipped ? `, ${skipped} skipped (already exist)` : ''}` })
      await fetchData()
    } catch (err) {
      setImportMsg({ ok: false, text: `Import failed: ${err.message}` })
    }
    setTimeout(() => setImportMsg(null), 6000)
  }

  async function handleDeleteService(svc) {
    if (!confirm(`Delete "${svc.name}"? This cannot be undone.`)) return
    try {
      await fetch(`/api/services/${svc.id}`, { method: 'DELETE' })
      await fetchData()
    } catch (err) {
      alert(`Failed to delete: ${err.message}`)
    }
  }

  async function handleToggleIncident(serviceId) {
    setExpandedIncidents(prev => {
      const next = new Set(prev)
      if (next.has(serviceId)) {
        next.delete(serviceId)
      } else {
        next.add(serviceId)
        // Fetch incidents if not cached
        if (!(serviceId in incidentCache)) {
          fetch(`/api/services/${serviceId}/incidents`)
            .then(r => r.json())
            .then(d => setIncidentCache(c => ({ ...c, [serviceId]: d })))
            .catch(() => setIncidentCache(c => ({ ...c, [serviceId]: [] })))
        }
      }
      return next
    })
  }

  async function handleToggleEnabled(svc) {
    const newEnabled = svc.enabled === 0 ? 1 : 0
    setData(prev => prev.map(s => s.id === svc.id ? { ...s, enabled: newEnabled } : s))
    setIncidentCache(c => { const n = { ...c }; delete n[svc.id]; return n })
    try {
      const res = await fetch(`/api/services/${svc.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: newEnabled === 1 }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    } catch {
      setData(prev => prev.map(s => s.id === svc.id ? { ...s, enabled: svc.enabled } : s))
    }
  }

  async function handlePauseService(serviceId, seconds) {
    try {
      const r = await fetch(`/api/services/${serviceId}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration_seconds: seconds }),
      })
      if (r.ok) {
        const state = await r.json()
        setData(prev => prev.map(s =>
          s.id === serviceId
            ? { ...s, paused: state.paused, paused_remaining_seconds: state.remaining_seconds }
            : s
        ))
      }
    } catch {}
  }

  async function handleResumeService(serviceId) {
    try {
      const r = await fetch(`/api/services/${serviceId}/pause`, { method: 'DELETE' })
      if (r.ok) {
        const state = await r.json()
        setData(prev => prev.map(s =>
          s.id === serviceId
            ? { ...s, paused: state.paused, paused_remaining_seconds: state.remaining_seconds }
            : s
        ))
      }
    } catch {}
  }

  function handleSaved() {
    setModalService(undefined)
    fetchData().then(services => {
      if (services) loadSparklines(services)
    })
    setIncidentCache({})
  }

  // Group and sort services
  const groups = groupBy(data, 'group_name')
  const sortedGroupNames = Object.keys(groups).sort((a, b) => {
    const ia = GROUP_ORDER.findIndex(g => g.toLowerCase() === a.toLowerCase())
    const ib = GROUP_ORDER.findIndex(g => g.toLowerCase() === b.toLowerCase())
    if (ia === -1 && ib === -1) return a.localeCompare(b)
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })

  const existingGroups = [...new Set(data.map(s => s.group_name).filter(Boolean))]

  const enabledData = data.filter(s => s.enabled !== 0)
  const statusSummary = {
    up: enabledData.filter(s => s.current_status === 1).length,
    total: enabledData.filter(s => s.current_status != null).length,
  }

  return (
    <>
      <input
        ref={importRef}
        type="file"
        accept=".json"
        style={{ display: 'none' }}
        onChange={handleImportFile}
      />
      <Header
        lastUpdated={lastUpdated}
        onRefresh={() => fetchData(true)}
        refreshing={refreshing}
        onAddService={() => setModalService(null)}
        onSettings={() => setSettingsOpen(true)}
        sseConnected={sseConnected}
        statusSummary={statusSummary}
        onImport={handleImportClick}
        importMsg={importMsg}
      />
      <main className="main">
        {loading && <div className="loading">Loading services…</div>}
        {error && <div className="error-banner">Error: {error}</div>}
        {sortedGroupNames.map(group => (
          <ServiceGroup
            key={group}
            name={group}
            services={groups[group]}
            sparklines={sparklines}
            onEdit={svc => setModalService(svc)}
            onDelete={handleDeleteService}
            incidentCache={incidentCache}
            expandedIncidents={expandedIncidents}
            onToggleIncident={handleToggleIncident}
            onToggleEnabled={handleToggleEnabled}
            onPauseService={handlePauseService}
            onResumeService={handleResumeService}
          />
        ))}
      </main>

      {modalService !== undefined && (
        <ServiceModal
          service={modalService}
          groups={existingGroups}
          onSaved={handleSaved}
          onClose={() => setModalService(undefined)}
        />
      )}

      {settingsOpen && (
        <SettingsModal onClose={() => setSettingsOpen(false)} />
      )}
    </>
  )
}
