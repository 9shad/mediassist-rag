'use client'

import { useState, useEffect } from 'react'

const DEMO_ACCOUNTS = [
  { username: 'dr.mehta', password: 'doctor', label: 'Dr. Mehta', role: 'doctor' },
  { username: 'nurse.priya', password: 'nurse', label: 'Nurse Priya', role: 'nurse' },
  { username: 'billing.ravi', password: 'billing_executive', label: 'Ravi Sharma', role: 'billing_executive' },
  { username: 'tech.anand', password: 'technician', label: 'Anand Kumar', role: 'technician' },
  { username: 'admin.sys', password: 'admin', label: 'Admin Sys', role: 'admin' },
]

interface LoginFormProps {
  onLogin: (token: string, role: string, username: string, name: string, collections: string[]) => void
}

const ROLE_COLORS: Record<string, string> = {
  doctor: '#0066cc',
  nurse: '#00a86b',
  billing_executive: '#cc6600',
  technician: '#9933cc',
  admin: '#cc0033',
}

export default function LoginForm({ onLogin }: LoginFormProps) {
  const [selected, setSelected] = useState(DEMO_ACCOUNTS[0].username)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [theme, setTheme] = useState<'light' | 'dark'>('light')

  useEffect(() => {
    const stored = localStorage.getItem('medibot-theme')
    if (stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      setTheme('dark')
      document.documentElement.setAttribute('data-theme', 'dark')
    }
  }, [])

  const toggleTheme = () => {
    const next = theme === 'light' ? 'dark' : 'light'
    setTheme(next)
    document.documentElement.setAttribute('data-theme', next)
    localStorage.setItem('medibot-theme', next)
  }

  const account = DEMO_ACCOUNTS.find((a) => a.username === selected)!

  const handleLogin = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: account.username, password: account.password }),
      })
      if (!res.ok) throw new Error('Login failed')
      const data = await res.json()
      onLogin(data.access_token, data.role, data.username, data.name, data.collections)
    } catch {
      setError('Login failed. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <nav className="login-navbar">
        <div className="logo">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2a4 4 0 014 4c0 2-2 4-4 4s-4-2-4-4 2-4 4-4z"/>
            <path d="M16 14c2 0 4 2 4 4v2H4v-2c0-2 2-4 4-4"/>
          </svg>
          <span className="logo-text">MediBot</span>
        </div>
        <button className="icon-btn" onClick={toggleTheme} title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}>
          {theme === 'light' ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="5"/>
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
            </svg>
          )}
        </button>
      </nav>
      <div className="login-center">
        <div className="login-card">
          <div className="login-header">
            <div className="login-avatar">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M12 2a4 4 0 014 4c0 2-2 4-4 4s-4-2-4-4 2-4 4-4z"/>
                <path d="M16 14c2 0 4 2 4 4v2H4v-2c0-2 2-4 4-4"/>
              </svg>
            </div>
            <h1 className="login-title">MediBot</h1>
            <p className="login-subtitle">MediAssist Health Network — Internal Assistant</p>
          </div>

          <div className="login-field">
            <label className="login-label">Select Demo User</label>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="login-select"
            >
              {DEMO_ACCOUNTS.map((a) => (
                <option key={a.username} value={a.username}>{a.label}</option>
              ))}
            </select>
          </div>

          <div className="login-preview" style={{ borderLeftColor: ROLE_COLORS[account.role] || '#666' }}>
            <div className="preview-avatar" style={{ background: ROLE_COLORS[account.role] || '#666' }}>
              {account.label.charAt(0)}
            </div>
            <div className="preview-info">
              <div className="preview-name">{account.label}</div>
              <div className="preview-role">{account.role.replace('_', ' ')}</div>
            </div>
          </div>

          <button
            onClick={handleLogin}
            disabled={loading}
            className="login-btn"
          >
            {loading ? (
              <span className="login-btn-loading">
                <span className="spinner" />
                Logging in...
              </span>
            ) : (
              'Login'
            )}
          </button>
          {error && <p className="login-error">{error}</p>}
        </div>
      </div>

      <style>{`
        :root {
          --bg: #ffffff;
          --bg-secondary: #f7f7f8;
          --text: #1a1a2e;
          --text-secondary: #6b6b7b;
          --border: #e5e5ea;
          --accent: #0052cc;
          --accent-hover: #0041a3;
          --shadow: rgba(0,0,0,0.06);
          --card-bg: #ffffff;
          --navbar-bg: #ffffff;
          --input-bg: #f7f7f8;
        }
        [data-theme="dark"] {
          --bg: #1a1a2e;
          --bg-secondary: #16213e;
          --text: #e4e4e7;
          --text-secondary: #a1a1aa;
          --border: #2d2d44;
          --accent: #3b82f6;
          --accent-hover: #60a5fa;
          --shadow: rgba(0,0,0,0.3);
          --card-bg: #0f1729;
          --navbar-bg: #0f1729;
          --input-bg: #16213e;
        }
        .login-page { min-height: 100vh; background: var(--bg); display: flex; flex-direction: column; }
        .login-navbar {
          height: 56px; display: flex; align-items: center; justify-content: space-between;
          padding: 0 16px; background: var(--navbar-bg); border-bottom: 1px solid var(--border);
        }
        .logo { display: flex; align-items: center; gap: 8px; color: var(--text); }
        .logo-text { font-weight: 700; font-size: 18px; }
        .icon-btn {
          display: flex; align-items: center; justify-content: center;
          width: 36px; height: 36px; border: none; border-radius: 8px;
          background: transparent; color: var(--text-secondary); cursor: pointer;
          transition: background 0.15s;
        }
        .icon-btn:hover { background: var(--bg-secondary); color: var(--text); }
        .login-center { flex: 1; display: flex; align-items: center; justify-content: center; padding: 24px; }
        .login-card {
          width: 100%; max-width: 400px; padding: 40px 32px;
          background: var(--card-bg); border-radius: 16px;
          border: 1px solid var(--border); box-shadow: 0 8px 32px var(--shadow);
        }
        .login-header { text-align: center; margin-bottom: 32px; }
        .login-avatar {
          width: 64px; height: 64px; border-radius: 50%;
          background: var(--bg-secondary); display: flex; align-items: center; justify-content: center;
          margin: 0 auto 16px; color: var(--accent);
        }
        .login-title { margin: 0; font-size: 24px; font-weight: 700; color: var(--text); }
        .login-subtitle { margin: 4px 0 0; font-size: 14px; color: var(--text-secondary); }
        .login-field { margin-bottom: 20px; }
        .login-label { display: block; margin-bottom: 6px; font-size: 13px; font-weight: 600; color: var(--text); }
        .login-select {
          width: 100%; padding: 10px 12px; border-radius: 8px;
          border: 1px solid var(--border); background: var(--input-bg);
          color: var(--text); font-size: 14px; outline: none;
          transition: border-color 0.15s; cursor: pointer;
          appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b6b7b' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
          background-repeat: no-repeat; background-position: right 12px center;
        }
        .login-select:focus { border-color: var(--accent); }
        .login-preview {
          display: flex; align-items: center; gap: 12px;
          padding: 12px; border-radius: 10px; border-left: 3px solid;
          background: var(--bg-secondary); margin-bottom: 24px;
        }
        .preview-avatar {
          width: 40px; height: 40px; border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          color: #fff; font-weight: 600; font-size: 16px; flex-shrink: 0;
        }
        .preview-info { line-height: 1.3; }
        .preview-name { font-size: 14px; font-weight: 600; color: var(--text); }
        .preview-role { font-size: 12px; color: var(--text-secondary); text-transform: capitalize; }
        .login-btn {
          width: 100%; padding: 12px 16px; border: none; border-radius: 10px;
          background: var(--accent); color: #fff; font-size: 15px; font-weight: 600;
          cursor: pointer; transition: background 0.15s;
        }
        .login-btn:hover:not(:disabled) { background: var(--accent-hover); }
        .login-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .login-btn-loading { display: flex; align-items: center; justify-content: center; gap: 8px; }
        .spinner {
          width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3);
          border-top-color: #fff; border-radius: 50%; animation: spin 0.6s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .login-error { text-align: center; color: #ef4444; font-size: 13px; margin-top: 12px; }
      `}</style>
    </div>
  )
}
