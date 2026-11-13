import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

let rawApi = (import.meta.env.VITE_API_BASE || '').trim().replace(/\/+$/, '')
const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:'
if (isHttps && rawApi.startsWith('http://')) {
  rawApi = rawApi.replace(/^http:\/\//, 'https://')
}
const API_BASE = rawApi || (isHttps ? '' : 'http://127.0.0.1:8000')
const WS_BASE = API_BASE
  ? API_BASE.replace(/^http(s?):/, 'ws$1:')
  : (isHttps ? 'wss://' + (typeof window !== 'undefined' ? window.location.host : '') : 'ws://127.0.0.1:8000')

function Icon({ name, size = 20 }) {
  const props = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }
  const shapes = {
    mic: <><rect x="8" y="3" width="8" height="12" rx="4" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3m-4 0h8" /></>,
    stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
    book: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 1 4 17.5z" /><path d="M4 6h13M8 10h8m-8 4h8" /></>,
    arrow: <><path d="M5 12h14m-6-6 6 6-6 6" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M5.5 9a7 7 0 0 1 11.6-2L20 12M4 12l2.9 5a7 7 0 0 0 11.6-2" /></>,
    wave: <path d="M3 10v4m4-8v12m4-15v18m4-14v10m4-13v16m3-11v6" />,
    check: <path d="m5 12 4 4L19 6" />,
    alert: <><path d="M12 9v4m0 4h.01" /><path d="M10.3 3.9 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></>,
    back: <path d="m15 18-6-6 6-6" />,
    user: <><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></>,
    search: <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></>,
    close: <path d="M18 6 6 18M6 6l12 12" />,
  }
  return <svg {...props}>{shapes[name] || null}</svg>
}

const money = (value) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value || 0)
const shortDate = (value) => value ? new Date(value + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : ''

function speakAnswer(text) {
  if (!('speechSynthesis' in window) || !text) return false
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'hi-IN'
  utterance.rate = 1.02
  window.speechSynthesis.speak(utterance)
  return true
}

function downsample(input, inputRate, outputRate = 16000) {
  const ratio = inputRate / outputRate
  if (ratio === 1) return input
  const output = new Float32Array(Math.floor(input.length / ratio))
  for (let i = 0; i < output.length; i += 1) {
    const start = Math.floor(i * ratio)
    const end = Math.min(Math.floor((i + 1) * ratio), input.length)
    let sum = 0
    for (let j = start; j < end; j += 1) sum += input[j]
    output[i] = sum / Math.max(1, end - start)
  }
  return output
}

function pcmFrame(samples) {
  const buffer = new ArrayBuffer(1024)
  const view = new DataView(buffer)
  for (let i = 0; i < 512; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i] || 0))
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
  }
  return buffer
}

function App() {
  const [balances, setBalances] = useState([])
  const [events, setEvents] = useState([])
  const [selectedCustomer, setSelectedCustomer] = useState(null)
  const [customerHistoryData, setCustomerHistoryData] = useState(null)
  const [customerSearch, setCustomerSearch] = useState('')
  const [reminderConsents, setReminderConsents] = useState({})
  const [reminderPreview, setReminderPreview] = useState(null)
  const [backendOnline, setBackendOnline] = useState(false)
  const [socketStatus, setSocketStatus] = useState('disconnected')
  const [recording, setRecording] = useState(false)
  const [handsFree, setHandsFree] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [reply, setReply] = useState('')
  const [pendingEvent, setPendingEvent] = useState(null)
  const [typedText, setTypedText] = useState('')
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const socketRef = useRef(null)
  const captureRef = useRef(null)
  const bufferRef = useRef([])

  const refreshLedger = useCallback(async () => {
    if (!API_BASE) {
      setBackendOnline(false)
      setError('VITE_API_BASE is not configured. In Vercel Project Settings > Environment Variables, add VITE_API_BASE=<your-render-url> and redeploy.')
      return
    }
    setRefreshing(true)
    try {
      const results = await Promise.all([
        fetch(API_BASE + '/ledger/summary'),
        fetch(API_BASE + '/ledger/events?limit=100'),
      ])
      if (!results[0].ok || !results[1].ok) throw new Error('Ledger could not be loaded from backend (' + API_BASE + ')')
      const currentBalances = await results[0].json()
      const currentEvents = await results[1].json()
      setBalances(currentBalances)
      setEvents(currentEvents)
      const consentEntries = await Promise.all(currentBalances.map(async (customer) => {
        try {
          const response = await fetch(API_BASE + '/customers/' + encodeURIComponent(customer.customer) + '/reminder-consent')
          const consent = await response.json()
          return [customer.customer, consent.opted_in]
        } catch { return [customer.customer, false] }
      }))
      setReminderConsents(Object.fromEntries(consentEntries))
      setBackendOnline(true)
      setError('')
    } catch {
      setBackendOnline(false)
      if (isHttps && API_BASE.startsWith('http:')) {
        setError('Mixed Content: Vercel runs on HTTPS but VITE_API_BASE is using HTTP. Please set VITE_API_BASE to your HTTPS backend URL (e.g. https://your-backend.onrender.com).')
      } else if (API_BASE.includes('render.com')) {
        setError('Connecting to backend on Render... Free tier service may take ~45s to wake up.')
      } else {
        setError('Can’t reach backend at ' + API_BASE + '. Make sure the backend server is running.')
      }
    } finally {
      setRefreshing(false)
    }
  }, [])

  const selectCustomer = useCallback(async (name) => {
    setSelectedCustomer(name)
    try {
      const response = await fetch(API_BASE + '/customers/' + encodeURIComponent(name) + '/history')
      if (response.ok) {
        const data = await response.json()
        setCustomerHistoryData(data)
      }
    } catch {
      // Local fallback calculation in activeCustomerHistory handles this seamlessly
    }
  }, [])

  const activeCustomerHistory = useMemo(() => {
    if (!selectedCustomer) return null
    if (customerHistoryData && customerHistoryData.customer && customerHistoryData.customer.toLowerCase() === selectedCustomer.toLowerCase()) {
      return customerHistoryData
    }
    const custRow = balances.find((b) => b.customer.toLowerCase() === selectedCustomer.toLowerCase())
    const netDue = custRow ? custRow.net_due : 0
    const custEvents = events.filter((e) => (e.customer_name || '').toLowerCase() === selectedCustomer.toLowerCase())
    const totalCredit = custEvents.reduce((sum, e) => {
      const type = e.type === 'correction' ? (e.meta?.replacement_type || 'credit') : e.type
      return type === 'credit' ? sum + (Number(e.amount) || 0) : sum
    }, 0)
    const totalPayment = custEvents.reduce((sum, e) => {
      const type = e.type === 'correction' ? (e.meta?.replacement_type || 'credit') : e.type
      return type === 'payment' ? sum + (Number(e.amount) || 0) : sum
    }, 0)
    return {
      customer: selectedCustomer,
      net_due: netDue,
      total_credit: totalCredit,
      total_payment: totalPayment,
      events: custEvents,
    }
  }, [selectedCustomer, customerHistoryData, balances, events])

  const filteredBalances = useMemo(() => {
    if (!customerSearch.trim()) return balances
    const q = customerSearch.trim().toLowerCase()
    return balances.filter((b) => b.customer.toLowerCase().includes(q))
  }, [balances, customerSearch])

  useEffect(() => {
    if (!backendOnline && API_BASE && API_BASE.includes('render.com')) {
      const timer = window.setTimeout(() => refreshLedger(), 5000)
      return () => window.clearTimeout(timer)
    }
  }, [backendOnline, refreshLedger])

  const updateReminderConsent = useCallback(async (customer, optedIn) => {
    try {
      const response = await fetch(API_BASE + '/customers/' + encodeURIComponent(customer) + '/reminder-consent', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ opted_in: optedIn }),
      })
      if (!response.ok) throw new Error('Consent setting could not be saved')
      setReminderConsents((previous) => ({ ...previous, [customer]: optedIn }))
      setReply(optedIn ? `${customer} opted in to polite reminders.` : `${customer} opted out of reminders.`)
    } catch (cause) {
      setError(cause.message || 'Consent setting could not be saved')
    }
  }, [])

  const previewReminder = useCallback(async (customer) => {
    try {
      const response = await fetch(API_BASE + '/reminders/prepare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ customer_name: customer }),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Reminder preview could not be prepared')
      if (!result.eligible) {
        setReply(result.reason === 'customer_has_not_opted_in' ? 'No reminder prepared: this customer has not opted in.' : 'No reminder is needed for this balance.')
        setReminderPreview(null)
        return
      }
      setReminderPreview(result)
    } catch (cause) {
      setError(cause.message || 'Reminder preview could not be prepared')
    }
  }, [])

  const downloadExcel = useCallback(async () => {
    try {
      const response = await fetch(API_BASE + '/ledger/export.xlsx')
      if (!response.ok) throw new Error('Excel file could not be created')
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'voice-khata.xlsx'
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) {
      setError(cause.message || 'Excel file could not be downloaded')
    }
  }, [])

  const openInExcel = useCallback(() => {
    const workbookUrl = API_BASE + '/ledger/export.xlsx'
    window.location.href = 'ms-excel:ofe|u|' + workbookUrl
  }, [])

  const openSocket = useCallback(() => new Promise((resolve, reject) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      resolve(socketRef.current)
      return
    }
    if (!WS_BASE) {
      reject(new Error('WebSocket base URL is not defined'))
      return
    }
    const socket = new WebSocket(WS_BASE + '/stream')
    socket.binaryType = 'arraybuffer'
    socketRef.current = socket
    setSocketStatus('connecting')
    socket.onopen = () => {
      setSocketStatus('connected')
      socket.send(JSON.stringify({ type: 'configure', sample_rate: 16000, language_code: 'indic-auto' }))
      resolve(socket)
    }
    socket.onmessage = (message) => {
      let data
      try { data = JSON.parse(message.data) } catch { return }
      if (data.type === 'transcript') {
        setTranscript(data.text || '')
        setReply('')
      } else if (data.type === 'control' && data.action === 'stop_listening') {
        const capture = captureRef.current
        if (capture) {
          capture.processor.onaudioprocess = null
          capture.processor.disconnect()
          capture.source.disconnect()
          capture.mute.disconnect()
          capture.stream.getTracks().forEach((track) => track.stop())
          capture.context.close().catch(() => {})
          captureRef.current = null
        }
        setHandsFree(false)
        setRecording(false)
        setSocketStatus('connected')
        setReply('Listening stopped.')
      } else if (data.type === 'clarification') {
        setReply(data.text || 'Please say that again.')
        speakAnswer(data.text)
      } else if (data.type === 'confirmation_required') {
        setPendingEvent(data.event || null)
        setReply(data.text || 'Please confirm the entry.')
        speakAnswer(data.text)
      } else if (data.type === 'confirmation_cancelled') {
        setPendingEvent(null)
        setReply(data.text || 'Entry cancelled.')
        speakAnswer(data.text)
      } else if (data.type === 'query_result') {
        setReply(data.response_string || 'Here is the balance.')
        if (!speakAnswer(data.response_string)) {
          fetch(API_BASE + '/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: data.response_string || 'Here is the balance.' }) })
            .then((response) => response.ok ? response.blob() : Promise.reject(new Error('Speech unavailable')))
            .then((blob) => new Audio(URL.createObjectURL(blob)).play())
            .catch(() => {})
        }
        refreshLedger()
      } else if (data.type === 'ledger_result') {
        setPendingEvent(null)
        setReply(data.response_string || 'Done.')
        if (data.response_string) speakAnswer(data.response_string)
        refreshLedger()
      } else if (data.type === 'audio_chunk' && data.audio) {
        const audio = new Audio('data:' + (data.mime_type || 'audio/wav') + ';base64,' + data.audio)
        const fallbackSpeech = () => {
          if (!speakAnswer(data.text)) setError('Audio playback was blocked by the browser.')
        }
        audio.onerror = fallbackSpeech
        audio.play().catch(fallbackSpeech)
      } else if (data.type === 'tts_text') {
        setReply(data.text || '')
        if (!speakAnswer(data.text)) setError('Speech playback is unavailable in this browser.')
      } else if (['provider_unavailable', 'provider_error', 'error'].includes(data.type)) {
        setError(data.detail || data.message || 'Speech service returned an error.')
      }
    }
    socket.onerror = () => {
      setSocketStatus('error')
      setError('Backend speech API is disconnected or unreachable. Please check backend status.')
      reject(new Error('Backend speech API is disconnected or unreachable.'))
    }
    socket.onclose = () => {
      setSocketStatus('disconnected')
      if (socketRef.current === socket) socketRef.current = null
    }
  }), [refreshLedger])

  const startRecording = useCallback(async () => {
    setError('')
    setTranscript('')
    setReply('')

    try {
      const socket = await openSocket()
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Microphone access is unavailable in this browser.')
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      })
      const context = new AudioContext()
      const source = context.createMediaStreamSource(stream)
      const processor = context.createScriptProcessor(1024, 1, 1)
      const mute = context.createGain()
      mute.gain.value = 0
      bufferRef.current = []
      processor.onaudioprocess = (event) => {
        const samples = downsample(event.inputBuffer.getChannelData(0), context.sampleRate)
        bufferRef.current.push(...samples)
        while (bufferRef.current.length >= 512) {
          const frame = bufferRef.current.splice(0, 512)
          if (socket.readyState === WebSocket.OPEN) socket.send(pcmFrame(frame))
        }
      }
      source.connect(processor)
      processor.connect(mute)
      mute.connect(context.destination)
      captureRef.current = { stream, context, source, processor, mute }
      setRecording(true)
      setSocketStatus('listening')
      return true
    } catch (cause) {
      setError(cause.message || 'Could not start microphone.')
      setRecording(false)
      return false
    }
  }, [openSocket])

  const stopRecording = useCallback(async () => {
    const capture = captureRef.current
    if (capture) {
      capture.processor.onaudioprocess = null
      capture.processor.disconnect()
      capture.source.disconnect()
      capture.mute.disconnect()
      capture.stream.getTracks().forEach((track) => track.stop())
      await capture.context.close().catch(() => {})
      captureRef.current = null
    }
    const socket = socketRef.current
    const pending = bufferRef.current
    bufferRef.current = []
    if (pending.length && socket && socket.readyState === WebSocket.OPEN) socket.send(pcmFrame(pending))
    setRecording(false)
    setSocketStatus('processing')
    if (socket && socket.readyState === WebSocket.OPEN) {
      const silence = new Float32Array(512)
      for (let i = 0; i < 20; i += 1) {
        socket.send(pcmFrame(silence))
        await new Promise((resolve) => window.setTimeout(resolve, 32))
      }
      setSocketStatus('connected')
    }
  }, [])

  const toggleRecording = useCallback(() => {
    if (recording) {
      setHandsFree(false)
      stopRecording()
    }
    else startRecording()
  }, [recording, startRecording, stopRecording])

  const toggleHandsFree = useCallback(async () => {
    if (handsFree) {
      setHandsFree(false)
      if (recording) await stopRecording()
      return
    }
    if (recording) return
    const started = await startRecording()
    if (started) setHandsFree(true)
  }, [handsFree, recording, startRecording, stopRecording])

  const confirmPending = useCallback(async (answer) => {
    try {
      const socket = await openSocket()
      socket.send(JSON.stringify({ transcript: answer, confidence: 0.95 }))
      setSocketStatus('processing')
      setError('')
    } catch (cause) {
      setError(cause.message || 'Could not confirm this entry.')
    }
  }, [openSocket])

  const submitTyped = useCallback(async (event) => {
    event.preventDefault()
    const text = typedText.trim()
    if (!text) return
    try {
      const socket = await openSocket()
      socket.send(JSON.stringify({ transcript: text, confidence: 0.95 }))
      setTranscript(text)
      setTypedText('')
      setReply('')
      setSocketStatus('processing')
      setError('')
    } catch (cause) {
      setError(cause.message || 'Could not send that entry.')
    }
  }, [openSocket, typedText])

  useEffect(() => {
    const initialLoad = window.setTimeout(() => refreshLedger(), 0)
    return () => {
      window.clearTimeout(initialLoad)
      const capture = captureRef.current
      if (capture) {
        capture.processor.disconnect()
        capture.source.disconnect()
        capture.stream.getTracks().forEach((track) => track.stop())
        capture.context.close()
      }
      if (socketRef.current) socketRef.current.close()
    }
  }, [refreshLedger])

  const totalOwed = useMemo(() => balances.reduce((sum, row) => sum + Math.max(0, Number(row.net_due) || 0), 0), [balances])
  const status = recording ? 'Listening' : socketStatus === 'processing' ? 'Working' : backendOnline ? 'Ready' : 'Offline'

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Voice Khata home"><span className="brand-mark"><Icon name="book" size={20} /></span><span>voice<span className="brand-light">khata</span></span></a>
        <div className="topbar-right">
          <span className={'connection-pill ' + (backendOnline ? 'is-online' : 'is-offline')}><span className="connection-dot" />{backendOnline ? 'Backend connected' : 'Backend offline'}</span>
          <button className="icon-button" onClick={refreshLedger} disabled={refreshing} aria-label="Refresh ledger" title="Refresh ledger"><Icon name="refresh" size={18} /></button>
        </div>
      </header>

      <main id="top" className="page-content">
        <section className="welcome-row">
          <div><p className="eyebrow">YOUR DIGITAL BAHI KHATA</p><h1>Good business starts<br className="desktop-break" /> with a clear hisaab.</h1><p className="welcome-copy">Speak naturally. Every udhaar and payment stays organized.</p></div>
          <div className="today-chip">{new Date().toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}</div>
        </section>

        <section className="summary-grid" aria-label="Ledger overview">
          <article className="summary-card summary-primary"><div className="summary-label">TOTAL TO COLLECT <span className="summary-icon"><Icon name="book" size={16} /></span></div><div className="summary-value">{money(totalOwed)}</div><div className="summary-foot">Across {balances.length} {balances.length === 1 ? 'customer' : 'customers'}</div></article>
          <article className="summary-card"><div className="summary-label">CUSTOMERS</div><div className="summary-value">{String(balances.length).padStart(2, '0')}</div><div className="summary-foot">With an active balance</div></article>
          <article className="summary-card summary-note"><div className="summary-label">VOICE ASSISTANT</div><div className="summary-note-row"><span className="assistant-avatar"><Icon name="wave" size={17} /></span><div><strong>Speak your bahi</strong><span>Hindi & Hinglish ready</span></div></div><div className="summary-foot"><span className="mini-dot" />{status} for your next entry</div></article>
        </section>

        <section className="workspace-grid">
          <div className="voice-panel panel">
            <div className="panel-heading"><div><p className="eyebrow">QUICK ENTRY</p><h2>What happened today?</h2></div><span className="live-tag"><span /> LIVE</span></div>
            <p className="panel-description">Press the mic and say a name, amount, and what it was for.</p>
            <div className={'voice-orbit ' + (recording ? 'recording' : '')}><div className="orbit-ring orbit-ring-one" /><div className="orbit-ring orbit-ring-two" /><button className={'mic-button ' + (recording ? 'mic-active' : '')} onClick={toggleRecording} aria-label={recording ? 'Stop recording' : 'Start voice entry'}><Icon name={recording ? 'stop' : 'mic'} size={29} /></button></div>
            <div className="voice-action-label">{recording ? (handsFree ? 'Hands-free is listening · tap mic to stop' : 'Tap to finish speaking') : 'Tap to speak'}</div>
            <button className={'handsfree-toggle ' + (handsFree ? 'handsfree-on' : '')} onClick={toggleHandsFree} disabled={recording && !handsFree}>
              <span className="handsfree-dot" />{handsFree ? 'Hands-free mode on' : 'Turn on hands-free mode'}
            </button>
            {handsFree && <div className="handsfree-help">Say “stop listening” when you’re done.</div>}
            <div className="voice-hint">Try <b>“Ramesh ko 340 udhaar”</b> or <b>“Ramesh ka total?”</b></div>
            {(transcript || reply || pendingEvent) && <div className="conversation-card" aria-live="polite">{transcript && <div className="conversation-line"><span className="conversation-label">YOU SAID</span><p>“{transcript}”</p></div>}{reply && <div className="conversation-line reply-line"><span className="conversation-label"><Icon name="check" size={13} /> KHATA</span><p>{reply}</p></div>}{pendingEvent && <div className="confirmation-actions"><div className="confirmation-summary"><strong>{pendingEvent.customer_name}</strong><span>{pendingEvent.type === 'payment' ? 'payment' : pendingEvent.type === 'correction' ? 'corrected balance' : 'udhaar'} · {money(pendingEvent.amount)}</span></div><div className="confirmation-buttons"><button type="button" className="confirm-button" onClick={() => confirmPending('haan')}>Confirm entry</button><button type="button" className="decline-button" onClick={() => confirmPending('nahi')}>No, cancel</button></div><small>Or say “nahi, 430” to correct the amount.</small></div>}</div>}
            <form className="type-entry" onSubmit={submitTyped}><label htmlFor="typed-entry">Or type a phrase</label><div className="type-entry-row"><input id="typed-entry" value={typedText} onChange={(event) => setTypedText(event.target.value)} placeholder="e.g. Sita ko 500 udhaar" /><button type="submit" className="send-button" disabled={!typedText.trim()} aria-label="Send phrase"><Icon name="arrow" size={18} /></button></div></form>
            {error && (
              <div className="error-message" role="alert" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1 }}>
                  <Icon name="alert" size={16} />
                  <span>{error}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setError('')}
                  style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '1.1rem', padding: '0 4px', lineHeight: 1 }}
                  aria-label="Dismiss error"
                >
                  ✕
                </button>
              </div>
            )}
            <div className="privacy-note"><span>●</span>Your ledger stays on this device.</div>
          </div>

          <div className="ledger-panel panel">
            <div className="panel-heading ledger-heading">
              <div>
                <p className="eyebrow">CUSTOMER LEDGER</p>
                <h2>{selectedCustomer ? `${selectedCustomer}'s Hisaab` : 'Who owes you'}</h2>
              </div>
              <div className="ledger-actions">
                <button className="export-button" onClick={downloadExcel}>Download Excel</button>
                <button className="export-button" onClick={openInExcel}>Open in Excel</button>
                <button className="text-button" onClick={refreshLedger} disabled={refreshing}>
                  {refreshing ? 'Updating…' : 'Refresh'} <Icon name="refresh" size={15} />
                </button>
              </div>
            </div>

            {selectedCustomer && activeCustomerHistory ? (
              <div className="customer-detail-view">
                <div className="customer-detail-top">
                  <button 
                    type="button" 
                    className="back-customers-button" 
                    onClick={() => { setSelectedCustomer(null); setCustomerHistoryData(null); }}
                  >
                    <Icon name="back" size={14} /> Back to all customers
                  </button>
                  <span className={'customer-detail-badge ' + (activeCustomerHistory.net_due < 0 ? 'credit-balance' : '')}>
                    {activeCustomerHistory.net_due > 0 ? 'Owes you' : activeCustomerHistory.net_due < 0 ? 'You owe' : 'Settled'}
                  </span>
                </div>

                <div className="customer-profile-card">
                  <div className="customer-profile-header">
                    <div className="customer-profile-avatar">
                      {selectedCustomer.charAt(0).toUpperCase()}
                    </div>
                    <div className="customer-profile-name">
                      <h3>{selectedCustomer}</h3>
                      <p>Customer Statement & Ledger</p>
                    </div>
                    <div className="customer-profile-due">
                      <span className="due-label">Current Balance</span>
                      <strong className={activeCustomerHistory.net_due < 0 ? 'credit-balance' : ''}>
                        {money(Math.abs(activeCustomerHistory.net_due))}
                      </strong>
                    </div>
                  </div>

                  <div className="customer-stats-grid">
                    <div className="cust-stat-box">
                      <span>Total Udhaar Given</span>
                      <strong className="stat-credit">{money(activeCustomerHistory.total_credit || 0)}</strong>
                    </div>
                    <div className="cust-stat-box">
                      <span>Total Paid / Wapas</span>
                      <strong className="stat-payment">{money(activeCustomerHistory.total_payment || 0)}</strong>
                    </div>
                    <div className="cust-stat-box">
                      <span>Total Entries</span>
                      <strong>{activeCustomerHistory.events.length}</strong>
                    </div>
                  </div>

                  <div className="customer-profile-actions">
                    <label className="reminder-consent">
                      <input 
                        type="checkbox" 
                        checked={Boolean(reminderConsents[selectedCustomer])} 
                        onChange={(event) => updateReminderConsent(selectedCustomer, event.target.checked)} 
                      /> 
                      Opted in to payment reminders
                    </label>
                    {reminderConsents[selectedCustomer] && (
                      <button 
                        type="button" 
                        className="reminder-preview-button" 
                        onClick={() => previewReminder(selectedCustomer)}
                      >
                        Preview polite reminder
                      </button>
                    )}
                  </div>
                </div>

                {reminderPreview && (
                  <aside className="reminder-preview" style={{ marginTop: '12px' }}>
                    <strong>Polite reminder preview · {reminderPreview.customer_name}</strong>
                    <p>{reminderPreview.message}</p>
                    <small>Preview only. No message was sent.</small>
                    <button type="button" onClick={() => setReminderPreview(null)}>Close</button>
                  </aside>
                )}

                <div className="customer-history-section">
                  <div className="section-title-row">
                    <h4>All History & Entries</h4>
                    <span>{activeCustomerHistory.events.length} entries</span>
                  </div>

                  {activeCustomerHistory.events.length ? (
                    <div className="customer-timeline">
                      {activeCustomerHistory.events.map((ev) => {
                        const isPayment = ev.type === 'payment'
                        const isCorrection = ev.type === 'correction'
                        return (
                          <div key={ev.event_id || Math.random()} className="timeline-item">
                            <div className={'timeline-icon ' + (isPayment ? 'icon-pay' : isCorrection ? 'icon-corr' : 'icon-cred')}>
                              <Icon name={isPayment ? 'check' : isCorrection ? 'refresh' : 'plus'} size={14} />
                            </div>
                            <div className="timeline-info">
                              <div className="timeline-title-row">
                                <strong>{isPayment ? 'Payment received / Wapas' : isCorrection ? 'Entry corrected' : 'Udhaar added'}</strong>
                                <span className={'timeline-amt ' + (isPayment ? 'amt-pay' : 'amt-cred')}>
                                  {isPayment ? '− ' : '+ '}{money(ev.amount)}
                                </span>
                              </div>
                              <div className="timeline-meta">
                                <span>{shortDate(ev.date) || 'Recent'}</span>
                                {ev.meta?.source && <span className="timeline-tag">{ev.meta.source}</span>}
                                {ev.meta?.previous_amount && <span className="timeline-tag">Prev: {money(ev.meta.previous_amount)}</span>}
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="empty-history">
                      <p>No transactions recorded yet for {selectedCustomer}.</p>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <>
                <div className="customer-search-row">
                  <Icon name="search" size={15} />
                  <input
                    type="text"
                    className="customer-search-input"
                    placeholder="Search customer by name..."
                    value={customerSearch}
                    onChange={(e) => setCustomerSearch(e.target.value)}
                  />
                  {customerSearch && (
                    <button type="button" onClick={() => setCustomerSearch('')} className="customer-search-clear">
                      <Icon name="close" size={13} />
                    </button>
                  )}
                </div>

                {balances.length > 0 && (
                  <div className="customer-tabs-row">
                    <span className="customer-tabs-label">Filter:</span>
                    <button 
                      type="button" 
                      className={'customer-tab-chip ' + (!customerSearch ? 'active' : '')}
                      onClick={() => setCustomerSearch('')}
                    >
                      All ({balances.length})
                    </button>
                    {balances.slice(0, 10).map((c) => (
                      <button
                        key={'tab-' + c.customer}
                        type="button"
                        className="customer-tab-chip"
                        onClick={() => selectCustomer(c.customer)}
                        title={`Click to view ${c.customer}'s hisaab`}
                      >
                        {c.customer} ({money(Math.abs(c.net_due))})
                      </button>
                    ))}
                  </div>
                )}

                {filteredBalances.length ? (
                  <div className="customer-list">
                    <div className="customer-row customer-row-heading">
                      <span>Name (Click to view history)</span>
                      <span>Balance status</span>
                      <span>Total amount</span>
                    </div>
                    {filteredBalances.map((customer) => (
                      <article 
                        className="customer-row clickable-customer-row" 
                        key={(customer.customer_id || '') + '-' + customer.customer}
                        onClick={() => selectCustomer(customer.customer)}
                        title={`Click to view ${customer.customer}'s complete history and balance`}
                      >
                        <div className="customer-info">
                          <div className="customer-name-link">
                            <strong>{customer.customer}</strong>
                            <span className="view-history-pill">View History →</span>
                          </div>
                          <label className="reminder-consent" onClick={(e) => e.stopPropagation()}>
                            <input 
                              type="checkbox" 
                              checked={Boolean(reminderConsents[customer.customer])} 
                              onChange={(event) => updateReminderConsent(customer.customer, event.target.checked)} 
                            /> 
                            Opted in to reminders
                          </label>
                          {reminderConsents[customer.customer] && (
                            <button 
                              type="button" 
                              className="reminder-preview-button" 
                              onClick={(e) => { e.stopPropagation(); previewReminder(customer.customer); }}
                            >
                              Preview reminder
                            </button>
                          )}
                        </div>
                        <div className={'customer-status ' + (customer.net_due < 0 ? 'credit-balance' : '')}>
                          {customer.net_due < 0 ? 'You owe' : 'Owes you'}
                        </div>
                        <div className={'customer-balance ' + (customer.net_due < 0 ? 'credit-balance' : '')}>
                          <strong>{money(Math.abs(customer.net_due))}</strong>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : balances.length ? (
                  <div className="empty-history" style={{ marginTop: '14px' }}>
                    <p>No customer found matching “{customerSearch}”.</p>
                  </div>
                ) : (
                  <div className="empty-ledger">
                    <div className="empty-icon"><Icon name="book" size={23} /></div>
                    <strong>Your ledger is ready</strong>
                    <p>New customer balances will show up here after your first entry.</p>
                  </div>
                )}

                {reminderPreview && (
                  <aside className="reminder-preview">
                    <strong>Polite reminder preview · {reminderPreview.customer_name}</strong>
                    <p>{reminderPreview.message}</p>
                    <small>Preview only. No message was sent.</small>
                    <button type="button" onClick={() => setReminderPreview(null)}>Close</button>
                  </aside>
                )}

                <div className="recent-heading">
                  <div>
                    <p className="eyebrow">RECENT ACTIVITY</p>
                    <h3>Latest entries</h3>
                  </div>
                  <span className="recent-count">{events.length} entries</span>
                </div>
                {events.length ? (
                  <div className="activity-list">
                    {events.slice(0, 5).map((entry) => (
                      <div 
                        className="activity-row" 
                        key={entry.event_id} 
                        onClick={() => entry.customer_name && selectCustomer(entry.customer_name)}
                        style={{ cursor: entry.customer_name ? 'pointer' : 'default' }}
                        title={entry.customer_name ? `Click to see ${entry.customer_name}'s history` : ''}
                      >
                        <span className={'activity-mark ' + (entry.type === 'payment' ? 'payment-mark' : '')}>
                          <Icon name={entry.type === 'payment' ? 'check' : entry.type === 'correction' ? 'refresh' : 'plus'} size={14} />
                        </span>
                        <div className="activity-main">
                          <strong>{entry.customer_name || entry.type}</strong>
                          <span>{entry.type === 'payment' ? 'Payment received' : entry.type === 'credit' ? 'Udhaar added' : entry.type === 'correction' ? 'Entry corrected' : entry.type} · {shortDate(entry.date)}</span>
                        </div>
                        <strong className={'activity-amount ' + (entry.type === 'payment' ? 'payment-amount' : '')}>
                          {entry.type === 'payment' ? '−' : entry.type === 'correction' ? '↻ ' : '+'}{money(entry.amount)}
                        </strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="no-activity">Your recent entries will appear here.</p>
                )}
              </>
            )}
          </div>
        </section>
        <footer className="page-footer"><span>VOICE KHATA</span><span>Simple hisaab. Peace of mind.</span></footer>
      </main>
    </div>
  )
}

export default App
