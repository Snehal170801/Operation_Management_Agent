import uuid

from app.db.connection import get_connection


def find_all_vendors():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT vendor_id, name, email, phone, call_language, reliability_score, created_at, email_bounced_at, email_bounce_reason "
            "FROM dbo.Vendors ORDER BY name ASC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def find_vendor_by_email(email: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT vendor_id, name, email FROM dbo.Vendors WHERE LOWER(email) = LOWER(?)", email)
        return cur.fetchone()
    finally:
        conn.close()


def mark_email_bounced(vendor_id: str, reason: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.Vendors SET email_bounced_at = SYSUTCDATETIME(), email_bounce_reason = ? WHERE vendor_id = ?", reason[:300], vendor_id)
        conn.commit()
    finally:
        conn.close()


def find_vendor_by_id(vendor_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT vendor_id, name, reliability_score, created_at "
            "FROM dbo.Vendors WHERE vendor_id = ?",
            vendor_id,
        )
        return cur.fetchone()
    finally:
        conn.close()


def upsert_vendor(name: str, reliability_score: float, email: str | None = None,
                  phone: str | None = None, call_language: str | None = None) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT vendor_id FROM dbo.Vendors WHERE LOWER(name) = LOWER(?)", name)
        row = cur.fetchone()
        if row:
            # A missing email / phone / language keeps the one already on file.
            cur.execute(
                # A new address clears the "bounced" flag: it is a different address, so give it a chance.
                "UPDATE dbo.Vendors SET reliability_score = ?, "
                "email_bounced_at = CASE WHEN ? IS NOT NULL AND LOWER(?) <> LOWER(ISNULL(email, '')) THEN NULL ELSE email_bounced_at END, "
                "email_bounce_reason = CASE WHEN ? IS NOT NULL AND LOWER(?) <> LOWER(ISNULL(email, '')) THEN NULL ELSE email_bounce_reason END, "
                "email = COALESCE(?, email), phone = COALESCE(?, phone), call_language = COALESCE(?, call_language) "
                "WHERE vendor_id = ?",
                reliability_score, email, email, email, email, email, phone, call_language, row.vendor_id,
            )
        else:
            cur.execute(
                "INSERT INTO dbo.Vendors (vendor_id, name, reliability_score, email, phone, call_language) "
                "VALUES (?, ?, ?, ?, ?, COALESCE(?, 'hi'))",
                str(uuid.uuid4()), name, reliability_score, email, phone, call_language,
            )
        conn.commit()
    finally:
        conn.close()


def update_vendor(vendor_id: str, name: str, email: str | None, phone: str | None, call_language: str, reliability_score: float) -> bool:
    """Replace a supplier's details. A new e-mail address clears the "bounced" flag (it is a different address, so give it a chance).
    False when there is no such supplier."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Vendors SET name = ?, reliability_score = ?, phone = ?, call_language = ?, "
            "email_bounced_at = CASE WHEN LOWER(ISNULL(?, '')) <> LOWER(ISNULL(email, '')) THEN NULL ELSE email_bounced_at END, "
            "email_bounce_reason = CASE WHEN LOWER(ISNULL(?, '')) <> LOWER(ISNULL(email, '')) THEN NULL ELSE email_bounce_reason END, "
            "email = ? WHERE vendor_id = ?",
            name, reliability_score, phone, call_language, email, email, email, vendor_id,
        )
        changed = cur.rowcount
        conn.commit()
        return changed > 0
    finally:
        conn.close()


def insert_quote(quote_id: str, case_id: str, vendor_id: str, raw_quote_text: str,
                  price, lead_time_days, terms, valid_until=None) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.VendorQuotes "
            "(quote_id, case_id, vendor_id, raw_quote_text, price, lead_time_days, terms, valid_until) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            quote_id, case_id, vendor_id, raw_quote_text, price, lead_time_days, terms, valid_until,
        )
        conn.commit()
    finally:
        conn.close()


def find_all_quotes(limit: int = 5000):
    """Every quote that still counts, newest first (for the document store)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT TOP ({int(limit)}) q.quote_id, q.case_id, q.vendor_id, v.name AS vendor_name, q.price, q.created_at "
            "FROM dbo.VendorQuotes q JOIN dbo.Vendors v ON v.vendor_id = q.vendor_id WHERE q.superseded_at IS NULL ORDER BY q.created_at DESC",
        )
        return cur.fetchall()
    finally:
        conn.close()


def find_quotes_by_case_id(case_id: str, include_superseded: bool = False):
    """The quotes that count (the latest round). `include_superseded` also returns an earlier round's, for the record."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT q.quote_id, q.case_id, q.vendor_id, v.name AS vendor_name, "
            "q.raw_quote_text, q.price, q.lead_time_days, q.terms, q.created_at, q.superseded_at, q.valid_until "
            "FROM dbo.VendorQuotes q "
            "JOIN dbo.Vendors v ON v.vendor_id = q.vendor_id "
            "WHERE q.case_id = ? " + ("" if include_superseded else "AND q.superseded_at IS NULL ") + "ORDER BY q.created_at ASC",
            case_id,
        )
        return cur.fetchall()
    finally:
        conn.close()


def supersede_quotes(case_id: str) -> None:
    """The quotes so far no longer count (a new round was asked for). They stay on record."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.VendorQuotes SET superseded_at = SYSUTCDATETIME() WHERE case_id = ? AND superseded_at IS NULL", case_id)
        conn.commit()
    finally:
        conn.close()


def supersede_vendor_quotes(case_id: str, vendor_id: str) -> None:
    """This supplier's quotes no longer count (they are being asked for a fresh one). They stay on record."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.VendorQuotes SET superseded_at = SYSUTCDATETIME() WHERE case_id = ? AND vendor_id = ? AND superseded_at IS NULL", case_id, vendor_id)
        conn.commit()
    finally:
        conn.close()


def delete_vendor_selection(case_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dbo.VendorSelections WHERE case_id = ?", case_id)
        conn.commit()
    finally:
        conn.close()


def upsert_vendor_selection(case_id: str, vendor_id: str, rationale: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT case_id FROM dbo.VendorSelections WHERE case_id = ?", case_id)
        if cur.fetchone():
            cur.execute(
                "UPDATE dbo.VendorSelections SET vendor_id = ?, rationale = ?, "
                "created_at = SYSUTCDATETIME() WHERE case_id = ?",
                vendor_id, rationale, case_id,
            )
        else:
            cur.execute(
                "INSERT INTO dbo.VendorSelections (case_id, vendor_id, rationale) VALUES (?, ?, ?)",
                case_id, vendor_id, rationale,
            )
        conn.commit()
    finally:
        conn.close()


def find_vendor_selection_by_case_id(case_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT s.case_id, s.vendor_id, v.name AS vendor_name, s.rationale, s.created_at "
            "FROM dbo.VendorSelections s "
            "JOIN dbo.Vendors v ON v.vendor_id = s.vendor_id "
            "WHERE s.case_id = ?",
            case_id,
        )
        return cur.fetchone()
    finally:
        conn.close()
