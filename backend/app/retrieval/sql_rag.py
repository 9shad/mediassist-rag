import re
import sqlite3
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.core.llm_client import generate_answer

SCHEMA_DESCRIPTION = """
Database: mediassist.db

Table: claims
  - claim_id (TEXT PRIMARY KEY)
  - patient_id (TEXT)
  - patient_name (TEXT)
  - department (TEXT) — e.g. Cardiology, Oncology, Pediatrics
  - claim_type (TEXT) — e.g. Insurance, TPA, Cashless
  - diagnosis_code (TEXT) — ICD code
  - insurer (TEXT)
  - claimed_amount (REAL)
  - approved_amount (REAL)
  - status (TEXT) — e.g. Approved, Denied, Pending, Escalated
  - submitted_date (TEXT) — ISO date
  - resolved_date (TEXT) — ISO date, nullable

Table: maintenance_tickets
  - ticket_id (TEXT PRIMARY KEY)
  - equipment_name (TEXT)
  - equipment_id (TEXT)
  - category (TEXT) — e.g. Imaging, Monitoring, Surgical, Laboratory
  - campus (TEXT) — e.g. Hyderabad Main, Bangalore South, Mumbai West
  - issue_type (TEXT) — e.g. Electrical, Mechanical, Software, Calibration
  - fault_code (TEXT)
  - raised_by (TEXT)
  - raised_date (TEXT) — ISO date
  - resolved_date (TEXT) — ISO date, nullable
  - status (TEXT) — e.g. Open, In Progress, Resolved, Escalated
  - resolution_note (TEXT)

Rules:
- Use only SELECT queries.
- Use date functions: date(), strftime(), julianday().
- Use GROUP BY for aggregations.
- Return raw numbers — don't format.
"""

SQL_SYSTEM_PROMPT = """You are a SQLite expert. Given a question and schema, output ONLY a valid SQLite SQL query. No explanation, no markdown, no backticks. Start directly with SELECT."""


def sql_rag_chain(question: str) -> str:
    sql_query = _generate_sql(question)
    cleaned_sql = _clean_sql(sql_query)
    logger.debug(f"Generated SQL: {cleaned_sql}")

    results = _execute_sql(cleaned_sql)

    if results and isinstance(results[0], dict) and "error" in results[0]:
        logger.error(f"SQL execution error: {results[0]['error']}")
        return _handle_sql_error(question)

    logger.debug(f"SQL results: {results}")

    answer = _generate_answer_from_results(question, cleaned_sql, results)
    return answer


FALLBACK_SQL_PATTERNS = [
    (r"(?i)how many\s+claims.*approved", "SELECT COUNT(*) FROM claims WHERE status = 'Approved'"),
    (r"(?i)how many\s+claims.*denied", "SELECT COUNT(*) FROM claims WHERE status = 'Denied'"),
    (r"(?i)how many\s+claims.*pending", "SELECT COUNT(*) FROM claims WHERE status = 'Pending'"),
    (r"(?i)how many\s+claims.*escalat", "SELECT COUNT(*) FROM claims WHERE status = 'Escalated'"),
    (r"(?i)total\s+(claim|approved|denied)\s+amount", "SELECT SUM(claimed_amount) as total_claimed, SUM(approved_amount) as total_approved FROM claims"),
    (r"(?i)average\s+claim", "SELECT AVG(claimed_amount) as avg_claim FROM claims"),
    (r"(?i)most\s+common\s+diagnosis", "SELECT diagnosis_code, COUNT(*) as count FROM claims GROUP BY diagnosis_code ORDER BY count DESC LIMIT 5"),
    (r"(?i)claims?\s+by\s+department", "SELECT department, COUNT(*) as count, SUM(claimed_amount) as total FROM claims GROUP BY department"),
    (r"(?i)how many\s+maintenance.*ticket", "SELECT COUNT(*) FROM maintenance_tickets"),
    (r"(?i)(open|in progress).*tickets?\s+by\s+category", "SELECT category, COUNT(*) as count FROM maintenance_tickets WHERE status IN ('Open', 'In Progress') GROUP BY category"),
    (r"(?i)list\s+(all\s+)?(open|in progress)\s+.*tickets?", "SELECT * FROM maintenance_tickets WHERE status IN ('Open', 'In Progress') ORDER BY category"),
    (r"(?i)most\s+common\s+(issue|fault).*equipment", "SELECT issue_type, COUNT(*) as count FROM maintenance_tickets GROUP BY issue_type ORDER BY count DESC LIMIT 5"),
    (r"(?i)equipment.*category.*most.*ticket", "SELECT category, COUNT(*) as count FROM maintenance_tickets GROUP BY category ORDER BY count DESC LIMIT 1"),
    (r"(?i)list\s+all\s+(claims|tickets)", "SELECT * FROM claims LIMIT 10"),
]


def _generate_sql(question: str) -> str:
    for pattern, sql in FALLBACK_SQL_PATTERNS:
        if re.search(pattern, question):
            logger.info(f"Using fallback SQL for: {pattern[0]}")
            return sql

    if not settings.llm_api_key:
        return "SELECT 'Unable to generate SQL without LLM API key'"

    prompt = f"Question: {question}\n\nSchema:\n{SCHEMA_DESCRIPTION}\n\nSQL Query:"
    try:
        import httpx
        response = httpx.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": SQL_SYSTEM_PROMPT + " Valid SQL only."},
                    {"role": "user", "content": prompt + "\n\nSELECT"},
                ],
                "max_tokens": 256,
                "temperature": 0.1,
            },
            timeout=15,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        if not text or not text.strip():
            return "SELECT 'Unable to generate SQL query'"
        sql = text.strip()
        if ";" in sql:
            sql = sql[: sql.index(";") + 1]
        return sql
    except Exception as e:
        logger.debug(f"SQL generation via LLM failed: {e}")
        return "SELECT 'Unable to generate SQL query'"


def _clean_sql(raw: str) -> str:
    sql = raw.strip()
    sql = re.sub(r"^```sql\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"^```", "", sql)
    sql = re.sub(r"```$", "", sql)

    sql_match = re.search(r"(SELECT\s+[\w\*\(\),\.\s'\"=<>!]+\s*(?:FROM\s+[\w\s,]+(?:\s+WHERE\s+[\w\s\.'\"=<>!]+(?:\s+(?:AND|OR)\s+[\w\s\.'\"=<>!]+)*)?(?:\s+GROUP\s+BY\s+[\w\s,]+)?(?:\s+ORDER\s+BY\s+[\w\s,]+(?:\s+(?:ASC|DESC))?)?(?:\s+LIMIT\s+\d+(?:\s+OFFSET\s+\d+)?)?\s*;?)?)", sql, re.IGNORECASE)
    if sql_match:
        sql = sql_match.group(1)

    sql = sql.strip().rstrip(";") + ";"

    if not re.match(r"^\s*SELECT\s+(FROM\s+\w+|[\w\*\(\),\.\s])", sql, re.IGNORECASE):
        logger.warning(f"Invalid SQL (not a SELECT): {sql[:80]}")
        return "SELECT 'Only SELECT queries are allowed';"

    return sql


def _execute_sql(sql: str) -> list[dict]:
    db_path = Path(settings.database_path)
    if not db_path.exists():
        logger.warning(f"Database not found at {db_path}")
        return [{"error": "database_not_found"}]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        logger.error(f"SQL execution error: {e}")
        return [{"error": str(e)}]
    finally:
        conn.close()


def _generate_answer_from_results(question: str, sql: str, results: list[dict]) -> str:
    if not settings.llm_api_key:
        return _format_results(question, results)

    prompt = (
        f"Question: {question}\n\n"
        f"Query Results: {results}\n\n"
        f"Provide a clear, concise natural language answer based on these results. "
        f"Do NOT include the SQL query or any query syntax in your response."
    )
    return generate_answer(
        question=prompt,
        system_prompt="You answer database queries in plain natural language. Never show SQL or technical query details.",
        max_tokens=512,
    )


def _format_results(question: str, results: list[dict]) -> str:
    lines = [f"Query results for: {question}", ""]
    if results and isinstance(results[0], dict):
        headers = list(results[0].keys())
        lines.append(" | ".join(str(h) for h in headers))
        lines.append("-" * len(lines[-1]))
        for row in results:
            lines.append(" | ".join(str(v) for v in row.values()))
    else:
        lines.append(str(results))
    return "\n".join(lines)


def _handle_sql_error(question: str) -> str:
    for pattern, sql in FALLBACK_SQL_PATTERNS:
        if re.search(pattern, question):
            logger.info(f"Retrying with fallback SQL for: {pattern[0]}")
            cleaned_sql = _clean_sql(sql)
            results = _execute_sql(cleaned_sql)
            if results and isinstance(results[0], dict) and "error" not in results[0]:
                return _generate_answer_from_results(question, cleaned_sql, results)
            break
    return "I encountered an error while querying the database. Please try rephrasing your question."
