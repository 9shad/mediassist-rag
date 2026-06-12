const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export async function login(username: string, password: string) {
  const res = await fetch(`${API_URL}/api/v1/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error('Login failed')
  return res.json()
}

export async function chat(question: string, token: string) {
  const res = await fetch(`${API_URL}/api/v1/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) throw new Error('Chat request failed')
  return res.json()
}

export async function getCollections(role: string, token: string) {
  const res = await fetch(`${API_URL}/api/v1/collections/${role}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to fetch collections')
  return res.json()
}
