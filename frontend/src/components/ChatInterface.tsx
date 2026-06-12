'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Source { source_document: string; section_title: string; collection: string }
interface TokenUsage { total_tokens: number; prompt_tokens: number; completion_tokens: number }

interface Message {
  id: string; type: 'user' | 'bot'; text: string; thinkText?: string
  sources?: Source[]; retrievalType?: string; usage?: TokenUsage; followups?: string[]
}

interface Conversation {
  id: string; title: string; role: string; username: string
  created_at: string; updated_at: string; messages?: Message[]
}

interface ChatInterfaceProps {
  token: string; role: string; username: string; name: string
  collections: string[]; onLogout: () => void
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const ROLE_COLORS: Record<string, string> = {
  doctor: '#0066cc', nurse: '#00a86b', billing_executive: '#cc6600',
  technician: '#9933cc', admin: '#cc0033',
}

const ROLE_LABELS: Record<string, string> = {
  doctor: 'Doctor', nurse: 'Nurse', billing_executive: 'Billing Executive',
  technician: 'Technician', admin: 'Admin',
}

const ROLE_SUGGESTIONS: Record<string, string[]> = {
  doctor: [
    'What is the malaria treatment protocol?',
    'What are the infection control procedures for ICU?',
    'List the symptoms of severe dengue',
    'What is the standard nursing care for post-surgery patients?',
  ],
  nurse: [
    'What is the standard nursing care for post-surgery patients?',
    'How do I monitor vital signs for ICU patients?',
    'What are the infection control procedures?',
    'What is the protocol for administering blood products?',
  ],
  billing_executive: [
    'How many claims were approved this month?',
    'What is the total claimed amount by department?',
    'Show me insurance billing codes for cardiology',
    'List all pending claims and their status',
  ],
  technician: [
    'How do I calibrate the MRI machine?',
    'What is the maintenance schedule for X-ray equipment?',
    'List common fault codes for ventilators',
    'How do I troubleshoot the CT scanner error E-47?',
  ],
  admin: [
    'How many approved claims across all departments?',
    'What is the equipment maintenance status?',
    'Show me the clinical protocol for malaria treatment',
    'List all open maintenance tickets by category',
  ],
}

const API_PREFIX = '/api/v1'

async function apiFetch(path: string, options: RequestInit = {}, token: string) {
  const res = await fetch(`${API_URL}${API_PREFIX}${path}`, {
    ...options,
    headers: { ...options.headers, Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export default function ChatInterface({ token, role, username, name, collections, onLogout }: ChatInterfaceProps) {
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(true)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const streamBotMsg = useRef<Message | null>(null)
  const streamingRef = useRef(false)

  useEffect(() => {
    const stored = localStorage.getItem('medibot-theme')
    if (stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      setTheme('dark')
      document.documentElement.setAttribute('data-theme', 'dark')
    }
  }, [])

  useEffect(() => {
    apiFetch('/conversations', {}, token).then(setConversations).catch(() => {})
  }, [token])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const loadMessages = useCallback(async (convId: string) => {
    try {
      const conv = await apiFetch(`/conversations/${convId}`, {}, token)
      const msgs: Message[] = (conv.messages || []).map((m: any) => ({
        id: m.id, type: m.type, text: m.text, thinkText: m.think_text,
        sources: m.sources, retrievalType: m.retrieval_type || (m.type === 'bot' ? 'Hybrid RAG' : undefined),
        usage: m.usage && m.usage.total_tokens ? m.usage : undefined,
      }))
      setMessages(msgs)
    } catch { setMessages([]) }
  }, [token])

  useEffect(() => {
    if (streamingRef.current) return
    if (activeId) loadMessages(activeId)
    else setMessages([])
  }, [activeId, loadMessages])

  const toggleTheme = () => {
    const next = theme === 'light' ? 'dark' : 'light'
    setTheme(next)
    document.documentElement.setAttribute('data-theme', next)
    localStorage.setItem('medibot-theme', next)
  }

  const newConversation = async () => {
    try {
      const conv = await apiFetch('/conversations', { method: 'POST' }, token)
      setConversations((prev) => [conv, ...prev])
      setActiveId(conv.id)
      setMessages([])
      inputRef.current?.focus()
    } catch (e) {
      console.error('Failed to create conversation:', e)
    }
  }

  const switchConversation = (id: string) => {
    setActiveId(id)
  }

  const deleteConversation = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    const conv = conversations.find((c) => c.id === id)
    if (!confirm(`Delete "${conv?.title || 'untitled'}" and all its messages?`)) return
    try {
      await apiFetch(`/conversations/${id}`, { method: 'DELETE' }, token)
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeId === id) {
        const next = conversations.filter((c) => c.id !== id)
        if (next.length > 0) setActiveId(next[0].id)
        else { setActiveId(null); setMessages([]) }
      }
    } catch {}
  }

  const sendMessage = async () => {
    if (!input.trim() || loading) return
    const question = input.trim()
    setInput('')

    streamingRef.current = true
    let convId = activeId
    if (!convId) {
      try {
        const conv = await apiFetch('/conversations', { method: 'POST' }, token)
        convId = conv.id
        setConversations((prev) => [conv, ...prev])
        setActiveId(convId)
      } catch { streamingRef.current = false; return }
    }

    if (!convId) return

    const userMsg: Message = { id: crypto.randomUUID(), type: 'user', text: question }
    const botMsg: Message = { id: crypto.randomUUID(), type: 'bot', text: '', thinkText: '' }

    setMessages((prev) => [...prev, userMsg, botMsg])
    setLoading(true)
    streamBotMsg.current = botMsg

    try {
      const res = await fetch(`${API_URL}/api/v1/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question, conversation_id: convId }),
      })
      if (!res.ok) throw new Error('Request failed')
      const reader = res.body?.getReader()
      if (!reader) throw new Error('No reader')
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        let eventType = ''
        let eventData = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim()
          else if (line.startsWith('data: ')) eventData = line.slice(6)
          else if (line === '' && eventType && eventData) {
            const data = JSON.parse(eventData)
            if (eventType === 'think') botMsg.thinkText = (botMsg.thinkText || '') + data
            else if (eventType === 'answer') botMsg.text += data
            else if (eventType === 'sources') {
              botMsg.sources = data.sources
              botMsg.retrievalType = data.retrieval_type === 'hybrid_rag' ? 'Hybrid RAG' : 'SQL RAG'
              botMsg.usage = data.usage
              botMsg.followups = data.followups
            }
            setMessages((prev) => prev.map((m) => (m.id === botMsg.id ? { ...botMsg } : m)))
            eventType = ''
            eventData = ''
          }
        }
      }

      // Update title in sidebar after first message
      setConversations((prev) => prev.map((c) =>
        c.id === convId && c.title === 'New Chat'
          ? { ...c, title: question.length > 55 ? question.slice(0, 55) + '…' : question }
          : c
      ))
    } catch {
      botMsg.text = 'Sorry, I encountered an error processing your request.'
      setMessages((prev) => prev.map((m) => (m.id === botMsg.id ? { ...botMsg } : m)))
    } finally {
      setLoading(false)
      streamBotMsg.current = null
      streamingRef.current = false
    }
  }

  const roleColor = ROLE_COLORS[role] || '#666'
  const roleLabel = ROLE_LABELS[role] || role

  return (
    <div className="app-container">
      <nav className="navbar">
        <div className="nav-left">
          <button className="icon-btn sidebar-toggle" onClick={() => setHistoryOpen(!historyOpen)} title="Toggle history">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
          </button>
          <div className="logo">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 12h6M12 9v6"/>
              <rect x="3" y="3" width="18" height="18" rx="5"/>
              <path d="M7 7h10v10H7z" fill="none"/>
            </svg>
            <span className="logo-text">MediBot</span>
          </div>
        </div>
        <div className="nav-right">
          <button className="icon-btn" onClick={toggleTheme} title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}>
            {theme === 'light' ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
            )}
          </button>
          <div className="user-badge" style={{ borderLeftColor: roleColor }}>
            <div className="user-avatar" style={{ background: roleColor }}>{name.charAt(0).toUpperCase()}</div>
            <div className="user-info">
              <div className="user-name">{name}</div>
              <div className="user-role">{roleLabel}</div>
            </div>
            <div className="role-tooltip">
              <strong>{roleLabel}</strong>
              <div className="tooltip-collections">
                {collections.map((c) => (
                  <span key={c} className="collection-tag" style={{ background: roleColor + '22', color: roleColor }}>{c}</span>
                ))}
              </div>
            </div>
          </div>
          <button className="icon-btn logout-btn" onClick={onLogout} title="Logout">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/></svg>
          </button>
        </div>
      </nav>

      <div className="main-area">
        <aside className={`history-panel ${historyOpen ? 'open' : ''}`}>
          <div className="history-header">
            <span className="history-title">Chat History</span>
            <button className="new-chat-btn" onClick={newConversation} title="New chat">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
              New Chat
            </button>
          </div>
          <div className="history-list">
            {conversations.length === 0 && <div className="history-empty">No conversations yet</div>}
            {conversations.map((conv) => (
              <div key={conv.id} className={`history-item ${conv.id === activeId ? 'active' : ''}`} onClick={() => switchConversation(conv.id)}>
                <div className="history-item-content">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                  <span className="history-item-title">{conv.title}</span>
                </div>
                <button className="delete-conv-btn" onClick={(e) => deleteConversation(e, conv.id)} title="Delete conversation">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2M10 11v6M14 11v6"/></svg>
                </button>
              </div>
            ))}
          </div>
        </aside>

        <main className="chat-area">
          {messages.length === 0 ? (
            <div className="welcome">
              <div className="welcome-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 12h6M12 9v6"/>
                  <rect x="2" y="2" width="20" height="20" rx="5"/>
                </svg>
              </div>
              <h2>Welcome to MediBot</h2>
              <p>Ask a question about your permitted collections: {collections.join(', ')}.</p>
              <div className="welcome-suggestions">
                {(ROLE_SUGGESTIONS[role] || ROLE_SUGGESTIONS.admin).map((s) => (
                  <button key={s} className="suggestion-chip" onClick={() => { setInput(s); inputRef.current?.focus() }}>{s}</button>
                ))}
              </div>
            </div>
          ) : (
            <div className="messages">
              {messages.map((msg) => (
                <div key={msg.id} className={`message ${msg.type}`}>
                  <div className="message-bubble">
                    {msg.type === 'bot' && msg.thinkText && (
                      <details className="think-block">
                        <summary className="think-summary">Model reasoning</summary>
                        <div className="think-content">{msg.thinkText}</div>
                      </details>
                    )}
                    <div className="message-text"><ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown></div>
                    {msg.retrievalType && (
                      <span className={`retrieval-badge ${msg.retrievalType === 'SQL RAG' ? 'sql' : 'hybrid'}`}>{msg.retrievalType}</span>
                    )}
                    {msg.sources && msg.sources.length > 0 && (
                      <details className="sources-block">
                        <summary className="sources-summary">Sources ({msg.sources.length})</summary>
                        <div className="sources-list">
                          {msg.sources.map((s, i) => (
                            <div key={i} className="source-item">
                              <span className="source-doc">{s.source_document}</span>
                              {s.section_title && <span className="source-section">— {s.section_title}</span>}
                              <span className="source-collection">{s.collection}</span>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                    {msg.usage && (
                      <div className="usage-footer">{msg.usage.total_tokens} tokens · {msg.usage.prompt_tokens} prompt · {msg.usage.completion_tokens} completion</div>
                    )}
                    {msg.type === 'bot' && msg.followups && msg.followups.length > 0 && (
                      <div className="followup-chips">
                        {msg.followups.map((f, i) => (
                          <button key={i} className="followup-chip" onClick={() => { setInput(f); inputRef.current?.focus() }}>{f}</button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {loading && !messages[messages.length - 1]?.text && (
                <div className="typing"><span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" /></div>
              )}
              <div ref={endRef} />
            </div>
          )}

          <div className="input-area">
            <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()} placeholder="Type your question..." disabled={loading} className="chat-input" />
            <button onClick={sendMessage} disabled={loading || !input.trim()} className="send-btn">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
            </button>
          </div>
        </main>
      </div>

      <style>{`
        :root {
          --bg: #ffffff; --bg-secondary: #f7f7f8; --bg-tertiary: #ececf1;
          --text: #1a1a2e; --text-secondary: #6b6b7b; --border: #e5e5ea;
          --accent: #0052cc; --accent-hover: #0041a3; --shadow: rgba(0,0,0,0.06);
          --bubble-user: #0052cc; --bubble-user-text: #ffffff;
          --bubble-bot: #f0f0f5; --bubble-bot-text: #1a1a2e;
          --navbar-bg: #ffffff; --sidebar-bg: #f7f7f8; --hover: #f0f0f5; --code-bg: #f4f4f8;
        }
        [data-theme="dark"] {
          --bg: #1a1a2e; --bg-secondary: #16213e; --bg-tertiary: #0f3460;
          --text: #e4e4e7; --text-secondary: #a1a1aa; --border: #2d2d44;
          --accent: #3b82f6; --accent-hover: #60a5fa; --shadow: rgba(0,0,0,0.3);
          --bubble-user: #3b82f6; --bubble-user-text: #ffffff;
          --bubble-bot: #1e293b; --bubble-bot-text: #e4e4e7;
          --navbar-bg: #0f1729; --sidebar-bg: #0f1729; --hover: #1e293b; --code-bg: #1e293b;
        }
        * { box-sizing: border-box; }
        body { background: var(--bg); color: var(--text); }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        .app-container { display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
        .navbar { height: 56px; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; background: var(--navbar-bg); border-bottom: 1px solid var(--border); flex-shrink: 0; z-index: 100; }
        .nav-left, .nav-right { display: flex; align-items: center; gap: 8px; }
        .logo { display: flex; align-items: center; gap: 8px; color: var(--text); }
        .logo-text { font-weight: 700; font-size: 18px; }
        .icon-btn { display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; border: none; border-radius: 8px; background: transparent; color: var(--text-secondary); cursor: pointer; transition: background 0.15s, color 0.15s; }
        .icon-btn:hover { background: var(--hover); color: var(--text); }
        .logout-btn:hover { color: #ef4444; }
        .sidebar-toggle { display: flex; }
        .user-badge { display: flex; align-items: center; gap: 8px; padding: 4px 12px 4px 4px; border-radius: 8px; border-left: 3px solid; position: relative; cursor: default; transition: background 0.15s; }
        .user-badge:hover { background: var(--hover); }
        .user-badge:hover .role-tooltip { opacity: 1; visibility: visible; transform: translateY(0); }
        .user-avatar { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 600; font-size: 14px; flex-shrink: 0; }
        .user-info { line-height: 1.3; }
        .user-name { font-size: 13px; font-weight: 600; color: var(--text); }
        .user-role { font-size: 11px; color: var(--text-secondary); }
        .role-tooltip { position: absolute; top: calc(100% + 8px); right: 0; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px; min-width: 180px; box-shadow: 0 4px 20px var(--shadow); z-index: 200; opacity: 0; visibility: hidden; transform: translateY(-4px); transition: all 0.2s; }
        .tooltip-collections { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
        .collection-tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 500; }
        .main-area { display: flex; flex: 1; overflow: hidden; }
        .history-panel { width: 280px; background: var(--sidebar-bg); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; transition: margin-left 0.25s, opacity 0.2s; }
        .history-panel:not(.open) { margin-left: -280px; opacity: 0; pointer-events: none; }
        @media (max-width: 767px) { .history-panel { position: fixed; left: 0; top: 56px; bottom: 0; z-index: 90; } .history-panel:not(.open) { margin-left: -280px; } }
        .history-header { padding: 16px; border-bottom: 1px solid var(--border); }
        .history-title { font-weight: 600; font-size: 14px; display: block; margin-bottom: 12px; }
        .new-chat-btn { display: flex; align-items: center; gap: 6px; width: 100%; padding: 8px 12px; border: 1px dashed var(--border); border-radius: 8px; background: transparent; color: var(--accent); font-size: 13px; font-weight: 500; cursor: pointer; transition: background 0.15s; }
        .new-chat-btn:hover { background: var(--hover); }
        .history-list { flex: 1; overflow-y: auto; padding: 8px; }
        .history-empty { text-align: center; padding: 24px 16px; color: var(--text-secondary); font-size: 13px; }
        .history-item { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-radius: 8px; cursor: pointer; transition: background 0.15s; margin-bottom: 2px; }
        .history-item:hover { background: var(--hover); }
        .history-item.active { background: var(--hover); }
        .history-item-content { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; }
        .history-item-content svg { flex-shrink: 0; color: var(--text-secondary); }
        .history-item-title { font-size: 13px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .delete-conv-btn { background: none; border: none; cursor: pointer; padding: 4px; border-radius: 4px; color: var(--text-secondary); opacity: 0; transition: all 0.15s; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .history-item:hover .delete-conv-btn { opacity: 0.5; }
        .delete-conv-btn:hover { opacity: 1 !important; background: var(--bg-secondary); color: #e53e3e; }
        .chat-area { flex: 1; display: flex; flex-direction: column; background: var(--bg); min-width: 0; }
        .welcome { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 24px; text-align: center; color: var(--text-secondary); }
        .welcome-icon { color: var(--text-secondary); margin-bottom: 16px; opacity: 0.5; }
        .welcome h2 { color: var(--text); margin: 0 0 8px; font-size: 22px; }
        .welcome p { margin: 0 0 24px; font-size: 15px; }
        .welcome-suggestions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; max-width: 500px; }
        .suggestion-chip { padding: 8px 14px; border: 1px solid var(--border); border-radius: 16px; background: var(--bg); color: var(--text-secondary); font-size: 13px; cursor: pointer; transition: all 0.15s; }
        .suggestion-chip:hover { border-color: var(--accent); color: var(--accent); background: var(--bg-secondary); }
        .messages { flex: 1; overflow-y: auto; padding: 24px 16px; }
        .message { display: flex; margin-bottom: 16px; }
        .message.user { justify-content: flex-end; }
        .message.bot { justify-content: flex-start; }
        .message-bubble { max-width: 72%; padding: 12px 16px; border-radius: 16px; line-height: 1.5; font-size: 14px; }
        .message.user .message-bubble { background: var(--bubble-user); color: var(--bubble-user-text); border-bottom-right-radius: 4px; }
        .message.bot .message-bubble { background: var(--bubble-bot); color: var(--bubble-bot-text); border-bottom-left-radius: 4px; }
        .message-text p { margin: 0 0 8px; }
        .message-text p:last-child { margin-bottom: 0; }
        .message-text ul, .message-text ol { padding-left: 20px; margin: 4px 0; }
        .message-text li { margin: 2px 0; }
        .message-text strong { font-weight: 600; }
        .message-text code { background: var(--code-bg); padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
        .message-text pre { background: var(--code-bg); padding: 8px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
        .message-text pre code { background: none; padding: 0; }
        .think-block { margin-bottom: 8px; }
        .think-summary { font-size: 11px; color: var(--text-secondary); cursor: pointer; opacity: 0.7; user-select: none; }
        .think-summary:hover { opacity: 1; }
        .think-content { font-size: 12px; color: var(--text-secondary); font-style: italic; padding: 8px; border-left: 2px solid var(--border); margin-top: 4px; line-height: 1.5; }
        .retrieval-badge { display: inline-block; font-size: 10px; padding: 2px 8px; border-radius: 4px; font-weight: 500; margin-top: 6px; }
        .retrieval-badge.hybrid { background: #e8f4e8; color: #166534; }
        .retrieval-badge.sql { background: #e8eef4; color: #1e40af; }
        [data-theme="dark"] .retrieval-badge.hybrid { background: #064e3b; color: #6ee7b7; }
        [data-theme="dark"] .retrieval-badge.sql { background: #1e3a5f; color: #93c5fd; }
        .sources-block { margin-top: 8px; }
        .sources-summary { font-size: 12px; cursor: pointer; opacity: 0.7; user-select: none; }
        .sources-summary:hover { opacity: 1; }
        .sources-list { margin-top: 6px; display: flex; flex-direction: column; gap: 4px; }
        .source-item { font-size: 12px; padding: 6px 8px; background: var(--code-bg); border-radius: 4px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
        .source-doc { font-weight: 500; }
        .source-section { color: var(--text-secondary); }
        .source-collection { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: var(--bg-tertiary); margin-left: auto; }
        .typing { display: flex; gap: 4px; padding: 16px 16px; }
        .typing-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-secondary); animation: pulse 1.4s infinite; }
        .typing-dot:nth-child(2) { animation-delay: 0.2s; }
        .typing-dot:nth-child(3) { animation-delay: 0.4s; }
        @keyframes pulse { 0%,60%,100% { opacity: 0.3; } 30% { opacity: 1; } }
        .input-area { display: flex; gap: 8px; padding: 16px 24px 24px; border-top: 1px solid var(--border); background: var(--bg); }
        .chat-input { flex: 1; padding: 12px 16px; border-radius: 12px; border: 1px solid var(--border); background: var(--bg-secondary); color: var(--text); font-size: 14px; outline: none; transition: border-color 0.15s; }
        .chat-input:focus { border-color: var(--accent); }
        .chat-input::placeholder { color: var(--text-secondary); }
        .send-btn { display: flex; align-items: center; justify-content: center; width: 44px; height: 44px; border: none; border-radius: 12px; background: var(--accent); color: #fff; cursor: pointer; transition: background 0.15s, opacity 0.15s; flex-shrink: 0; }
        .send-btn:hover:not(:disabled) { background: var(--accent-hover); }
        .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .usage-footer { font-size: 10px; color: var(--text-secondary); margin-top: 6px; opacity: 0.6; }
        .followup-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
        .followup-chip { padding: 6px 12px; border: 1px solid var(--border); border-radius: 12px; background: transparent; color: var(--text-secondary); font-size: 12px; cursor: pointer; transition: all 0.15s; }
        .followup-chip:hover { border-color: var(--accent); color: var(--accent); background: var(--bg-secondary); }
      `}</style>
    </div>
  )
}
