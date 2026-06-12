'use client'

import { useState } from 'react'
import LoginForm from '../components/LoginForm'
import ChatInterface from '../components/ChatInterface'

interface Session {
  token: string
  role: string
  username: string
  name: string
  collections: string[]
}

export default function Home() {
  const [session, setSession] = useState<Session | null>(null)

  if (!session) {
    return (
      <LoginForm
        onLogin={(token, role, username, name, collections) =>
          setSession({ token, role, username, name, collections })
        }
      />
    )
  }

  return (
    <ChatInterface
      token={session.token}
      role={session.role}
      username={session.username}
      name={session.name}
      collections={session.collections}
      onLogout={() => setSession(null)}
    />
  )
}
