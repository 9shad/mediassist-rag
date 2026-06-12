# Authentication — JWT-Based Login

## Overview

Authentication uses **JSON Web Tokens (JWT)** — a stateless, signed token that encodes the user's identity and permissions. After login, every API request includes the JWT, which the backend verifies without any server-side session storage.

## Login Flow

```
Client                           Server
  │                                │
  │  POST /api/v1/login            │
  │  {username, password}         │
  │ ──────────────────────────►   │
  │                                │
  │                                │  verify credentials
  │                                │  (lookup in DEMO_USERS)
  │                                │
  │                                │  create JWT:
  │                                │  {sub, role, collections, iat, exp}
  │                                │
  │  {access_token, role,         │
  │   username, name, collections} │
  │ ◄──────────────────────────   │
  │                                │
  │  store token in memory        │
  │  (React state)                │
```

## Implementation

### Login Endpoint

**File:** `backend/app/api/routes.py`

```python
@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    role = user["role"]
    collections = get_role_collections(role.value)
    token = create_access_token(role, req.username)
    return LoginResponse(
        access_token=token,
        role=role.value,
        username=req.username,
        name=user["name"],
        collections=collections,
    )
```

### User Authentication

**File:** `backend/app/core/security.py`

Users are hardcoded in `DEMO_USERS` (defined in `enums.py`):

```python
DEMO_USERS: dict[str, dict] = {
    "dr.mehta": {"password": "doctor", "role": Role.DOCTOR, "name": "Dr. Mehta"},
    "nurse.priya": {"password": "nurse", "role": Role.NURSE, "name": "Nurse Priya"},
    "billing.ravi": {"password": "billing_executive", "role": Role.BILLING_EXECUTIVE, "name": "Ravi Sharma"},
    "tech.anand": {"password": "technician", "role": Role.TECHNICIAN, "name": "Anand Kumar"},
    "admin.sys": {"password": "admin", "role": Role.ADMIN, "name": "Admin Sys"},
}

def authenticate_user(username: str, password: str) -> dict:
    user = DEMO_USERS.get(username)
    if not user or user["password"] != password:
        raise AuthenticationError("Invalid username or password")
    return user
```

In production, `DEMO_USERS` would be replaced with a database-backed user store with hashed passwords.

### JWT Token Creation

```python
def create_access_token(role: Role, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,               # Subject — the username
        "role": role.value,            # Role for RBAC
        "collections": ROLE_COLLECTIONS[role],  # Permitted collections
        "iat": now,                    # Issued at
        "exp": now + timedelta(minutes=settings.jwt_expiration_minutes),  # Expiry
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
```

**JWT Payload Fields:**
| Field | Value | Purpose |
|---|---|---|
| `sub` | `"billing.ravi"` | Identifies the user (used for chat history scoping) |
| `role` | `"billing_executive"` | Used for RBAC in Qdrant filter and SQL RAG routing |
| `collections` | `["general", "billing"]` | Pre-computed access list (useful for UI) |
| `iat` | `1718000000` | Prevents token replay from the distant past |
| `exp` | `1718000600` | 10-minute default expiry (configurable) |

### Token Verification

**File:** `backend/app/api/deps.py`

```python
def require_role(payload: dict = Depends(get_current_user)):
    role = payload.get("role")
    if not role:
        raise AuthenticationError("Role not found in token")
    return payload
```

```python
def get_current_user(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    payload = decode_access_token(token)
    return payload
```

All protected endpoints use `Depends(require_role)` which:
1. Extracts the `Authorization: Bearer <token>` header
2. Decodes and verifies the JWT signature
3. Returns the payload containing `sub`, `role`, and `collections`
4. If the token is expired or invalid, returns HTTP 401

## Security Properties

| Property | How It's Achieved |
|---|---|
| **Stateless** | No server-side sessions; token contains all info |
| **Tamper-proof** | HMAC-SHA256 signature using server secret |
| **Time-limited** | Token expires after `jwt_expiration_minutes` (default 10) |
| **Role-immutable** | Role is embedded in signed token at login; cannot be changed client-side |
| **No password exposure** | Password sent only once at `/login`; subsequent requests use token |

## Frontend Token Management

The frontend stores the token in React state (no localStorage for security — requires re-login on refresh):

```typescript
const [token, setToken] = useState<string | null>(null);

const handleLogin = async (username: string, password: string) => {
  const res = await fetch(`${API_URL}/api/v1/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json();
  setToken(data.access_token);
  // Store user info for display
};
```

The token is passed to all API calls via the `Authorization` header:

```typescript
const apiFetch = async (path: string, options: RequestInit, token: string) => {
  const res = await fetch(`${API_URL}/api/v1${path}`, {
    ...options,
    headers: {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) throw new Error('API error');
  return res.json();
};
```

## Differences from Session-Based Auth

| Aspect | JWT (this project) | Session-Based |
|---|---|---|
| **State** | Stateless (no DB lookup for auth) | Server must check session store |
| **Scalability** | Works with any number of backend instances | Needs shared session store (Redis) |
| **Revocation** | Can't revoke individual tokens (wait for expiry) | Can delete session immediately |
| **Size** | ~500 bytes per request (header + payload) | ~50 bytes (cookie + session ID) |
| **Clients** | Works with mobile, SPA, CLI | Browsers only (cookies) |

For this application, JWT is appropriate because:
- The backend is stateless (Docker-friendly)
- Token expiry is short (10 min)
- No revocation needed for demo users
- Multiple client types could consume the API
