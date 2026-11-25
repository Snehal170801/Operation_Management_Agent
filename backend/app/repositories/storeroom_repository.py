from app.core.storeroom_catalog import Dataset
from app.db.connection import get_connection

MAX_PAGE = 200


def _like(term: str) -> str:
    """A LIKE pattern matching `term` literally (so a typed % or _ is not a wildcard)."""
    escaped = "".join(f"[{ch}]" if ch in "[]%_" else ch for ch in term.strip())
    return f"%{escaped}%"


def _where(dataset: Dataset, search: str | None) -> tuple[str, list[str]]:
    if not search or not search.strip():
        return "", []
    clause = " OR ".join(f"{expr} LIKE ?" for expr in dataset.search_exprs)
    return f"WHERE ({clause}) ", [_like(search)] * len(dataset.search_exprs)


def _select(dataset: Dataset) -> str:
    return ", ".join(f"{c.expr} AS [{c.key}]" for c in dataset.columns)


def case_numbers(case_ids: list[str]) -> dict[str, str]:
    """{case id (lower-case): case number} for the given cases, in one query."""
    ids = sorted({i for i in case_ids if i})
    if not ids:
        return {}
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT case_id, case_number FROM dbo.Cases WHERE case_id IN ({', '.join('?' for _ in ids)})", *ids,
        )
        return {str(r.case_id).lower(): r.case_number for r in cur.fetchall()}
    finally:
        conn.close()


def count(dataset: Dataset, search: str | None = None) -> int:
    where, params = _where(dataset, search)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {dataset.from_sql} {where}", *params)
        return cur.fetchone()[0]
    finally:
        conn.close()


def page(dataset: Dataset, search: str | None, limit: int, offset: int) -> list[dict]:
    limit = max(1, min(limit, MAX_PAGE))
    where, params = _where(dataset, search)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_select(dataset)} FROM {dataset.from_sql} {where}"
            f"ORDER BY {dataset.order_sql} OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            *params, max(0, offset), limit,
        )
        keys = [c.key for c in dataset.columns]
        return [dict(zip(keys, row)) for row in cur.fetchall()]
    finally:
        conn.close()
