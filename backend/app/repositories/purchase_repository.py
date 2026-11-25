import uuid

from app.db.connection import get_connection


def insert_purchase_request(purchase_request_id: str, case_id: str,
                             cost_center: str, raw_request: str, needed_by=None, urgent: bool = False) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.PurchaseRequests "
            "(purchase_request_id, case_id, cost_center, raw_request, needed_by, urgent) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            purchase_request_id, case_id, cost_center, raw_request, needed_by, 1 if urgent else 0,
        )
        conn.commit()
    finally:
        conn.close()


def insert_purchase_request_items(purchase_request_id: str, items: list[dict]) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        for item in items:
            cur.execute(
                "INSERT INTO dbo.PurchaseRequestItems "
                "(item_id, purchase_request_id, description, quantity) "
                "VALUES (?, ?, ?, ?)",
                str(uuid.uuid4()), purchase_request_id, item["description"], item["quantity"],
            )
        conn.commit()
    finally:
        conn.close()


def find_purchase_request_by_case_id(case_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT purchase_request_id, case_id, cost_center, raw_request, created_at, needed_by, urgent "
            "FROM dbo.PurchaseRequests WHERE case_id = ?",
            case_id,
        )
        return cur.fetchone()
    finally:
        conn.close()


def find_items_by_purchase_request_id(purchase_request_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT item_id, description, quantity "
            "FROM dbo.PurchaseRequestItems WHERE purchase_request_id = ? "
            "ORDER BY created_at ASC",
            purchase_request_id,
        )
        return cur.fetchall()
    finally:
        conn.close()


def update_request_terms(purchase_request_id: str, needed_by, urgent: bool) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.PurchaseRequests SET needed_by = ?, urgent = ? WHERE purchase_request_id = ?", needed_by, 1 if urgent else 0, purchase_request_id)
        conn.commit()
    finally:
        conn.close()


def update_item_quantity(purchase_request_id: str, description: str, quantity: int) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseRequestItems SET quantity = ? WHERE purchase_request_id = ? AND description = ?",
            quantity, purchase_request_id, description,
        )
        conn.commit()
    finally:
        conn.close()
