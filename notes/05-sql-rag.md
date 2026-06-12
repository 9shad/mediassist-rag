# SQL RAG — Natural Language to Database Queries

## Overview

SQL RAG allows users to ask analytical questions about structured data (claims and maintenance tickets) in natural language. The system converts the question to SQL, executes it against the SQLite database, and presents the results as a natural language answer.

**Contrast with Hybrid RAG:**

| Aspect | Hybrid RAG | SQL RAG |
|---|---|---|
| **Data source** | Unstructured documents (PDFs/MD) | Structured database tables |
| **Retrieval** | Vector similarity search | SQL query execution |
| **Query type** | Factual/"what" questions | Analytical/"how many" questions |
| **RBAC** | All roles | Only `admin` and `billing_executive` |

## Architecture

```
User Query: "How many claims were approved last month?"
    │
    ▼
Query Router (orchestrator.py)
    │
    ├── Is analytical? (pattern match)
    ├── Is role allowed? (billing_executive or admin)
    │
    ▼
sql_rag_chain()
    │
    ├── 1. SQL Generation ──► Fallback regex patterns first, LLM as fallback
    │                        (both produce a SQL SELECT query from plain text)
    ├── 2. SQL Cleaning ──► Regex strips markdown, validates SELECT-only
    ├── 3. SQL Execution ──► sqlite3 against mediassist.db
    └── 4. Answer Generation ──► LLM turns results into natural language
                                 (SQL query excluded from prompt — guardrail)
```

## Implementation

**File:** `backend/app/retrieval/sql_rag.py`

### Step 1: Query Routing

**File:** `backend/app/retrieval/orchestrator.py`

```python
ANALYTICAL_PATTERNS = re.compile(
    r"(how many|count|total|average|sum|what.*percentage|statistics|"
    r"most|least|top.*bottom|compare|month|quarter|year|trend|"
    r"claims|maintenance|ticket|escalat|approv|denied|pending)",
    re.IGNORECASE,
)

def _is_analytical(query: str) -> bool:
    return bool(ANALYTICAL_PATTERNS.search(query))
```

The router uses regex to detect analytical intent. If the query matches and the user's role is in `SQL_RAG_ROLES` (`{admin, billing_executive}`), the query goes to SQL RAG. Otherwise, it goes to Hybrid RAG.

**Role restriction:**
```python
SQL_RAG_ROLES: set[Role] = {Role.BILLING_EXECUTIVE, Role.ADMIN}
```

### Step 2: SQL Generation

The LLM receives the database schema and the natural language question. To force the model to output valid SQL (not descriptive text), the assistant response is primed with `"SELECT"` so the model completes a SQL statement rather than explaining it:

```python
def _generate_sql(question: str) -> str:
    # Try fallback patterns FIRST
    for pattern, sql in FALLBACK_SQL_PATTERNS:
        if re.search(pattern, question):
            return sql

    # LLM with assistant priming as fallback
    response = httpx.post(
        f"{settings.llm_base_url}/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": "Output ONLY valid SQL."},
                {"role": "user", "content": prompt + "\n\nSELECT"},
            ],
        },
    )
    text = response.json()["choices"][0]["message"]["content"]
    return "SELECT" + (text or "")
```

#### Fallback Pattern Matching (Tried First)

Fallback patterns are checked **before** the LLM to ensure common queries work reliably regardless of LLM behavior:

```python
FALLBACK_SQL_PATTERNS = [
    (r"(?i)(how many|count of)\s+claims.*approved",
     "SELECT COUNT(*) FROM claims WHERE status = 'Approved'"),
    (r"(?i)list\s+(all\s+)?(open|in progress)\s+.*tickets?",
     "SELECT * FROM maintenance_tickets WHERE status IN ('Open', 'In Progress') ORDER BY category"),
    # ... 14 patterns covering common queries
]
```

If the LLM generates invalid SQL that fails at execution time, the system automatically retries with fallback patterns via `_handle_sql_error()`.

### Step 3: SQL Cleaning

Raw LLM output often contains markdown fences, explanations, or incomplete statements:

```python
def _clean_sql(raw: str) -> str:
    sql = raw.strip()
    sql = re.sub(r"^```sql\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"^```", "", sql)
    sql = re.sub(r"```$", "", sql)
    sql_match = re.search(r"(SELECT\s+.+)", sql, re.IGNORECASE | re.DOTALL)
    if sql_match:
        sql = sql_match.group(1)
    sql = sql.strip().rstrip(";") + ";"
    if not re.match(r"^\s*SELECT", sql, re.IGNORECASE):
        return "SELECT 'Only SELECT queries are allowed';"
    return sql
```

This ensures:
- Markdown code fences are stripped
- Only the first `SELECT` statement is extracted
- Only SELECT queries are allowed (security constraint)
- The query ends with a semicolon

### Step 4: SQL Execution

```python
def _execute_sql(sql: str) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(sql)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    result = [dict(zip(columns, row)) for row in rows]
    conn.close()
    return result
```

The cleaned SQL is executed against the SQLite database at `mediassist_data/mediassist.db`. Results are returned as a list of dictionaries.

### Step 5: Answer Generation

```python
def _generate_answer_from_results(question: str, sql: str, results: list[dict]) -> str:
    prompt = (
        f"Question: {question}\n\n"
        f"Query Results: {results}\n\n"
        f"Provide a clear, concise natural language answer based on these results. "
        f"Do NOT include the SQL query in your response."
    )
    return generate_answer(
        question=prompt,
        system_prompt="You answer database queries in plain natural language. Never show SQL or technical query details.",
        max_tokens=512,
    )
```

The LLM receives the original question and the results only — **the SQL query is never passed to the answer generator**. This prevents the LLM from accidentally including SQL syntax in user-facing responses (a key guardrail). If no LLM is configured, results are formatted as a simple table.

## Security Considerations

1. **SELECT-only constraint**: The system rejects any non-SELECT query (prevents INSERT, UPDATE, DELETE, DROP)
2. **SQL never shown to users**: The SQL query is excluded from the answer generation prompt — the LLM receives only question + results
3. **Role restriction**: Only `billing_executive` and `admin` can trigger SQL RAG — others get Hybrid RAG regardless of query content
4. **Read-only database**: The SQLite file is mounted read-only in the Docker volume
5. **Query sanitization**: The `_clean_sql` function strips anything before the SELECT statement, preventing injection via prompt manipulation

## Example Flow

**User:** "How many claims were denied in the cardiology department?"

**Generated SQL:**
```sql
SELECT COUNT(*) as denied_count FROM claims
WHERE department = 'Cardiology' AND status = 'Denied'
```

**LLM Answer:**
"There are currently 3 denied claims in the Cardiology department. The most recent denial was for claim CL-2024-0042 submitted on 2024-11-12."
