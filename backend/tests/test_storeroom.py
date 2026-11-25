from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import storeroom_controller
from app.core import access, security
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.core.storeroom_catalog import DATASETS, FORBIDDEN_TABLES, KINDS, get_dataset, groups
from app.main import app
from app.repositories import role_repository, storeroom_repository, user_repository

client = TestClient(app)


# ---------- the catalogue itself ----------

def test_every_dataset_is_well_formed():
    assert len({d.key for d in DATASETS}) == len(DATASETS)
    for d in DATASETS:
        keys = [c.key for c in d.columns]
        assert len(keys) == len(set(keys)), f"{d.key}: duplicate column"
        assert all(c.kind in KINDS for c in d.columns), d.key
        assert d.search_exprs and d.order_sql and d.description
        assert all(c.label for c in d.columns)


def test_sensitive_tables_and_columns_can_never_be_exposed():
    for d in DATASETS:
        sql = (d.from_sql + " " + " ".join(c.expr for c in d.columns)).lower()
        for table in FORBIDDEN_TABLES:
            assert table.lower() not in sql, f"{d.key} reads {table}"
        for secret in ("password", "hash", "token", "otp", "secret"):
            assert secret not in sql, f"{d.key} touches a '{secret}' column"


def test_no_sql_in_the_catalogue_can_run_a_second_statement():
    for d in DATASETS:
        for text in (d.from_sql, d.order_sql, *d.search_exprs, *(c.expr for c in d.columns)):
            assert ";" not in text and "--" not in text, d.key


def test_datasets_are_grouped_in_a_sensible_order():
    labels = [label for label, _ in groups()]
    assert labels[0] == "Inventory" and "Suppliers" in labels and "Orders & delivery" in labels
    assert sum(len(ds) for _, ds in groups()) == len(DATASETS)


def test_unknown_dataset_is_none():
    assert get_dataset("users") is None and get_dataset("nope") is None


# ---------- search stays a parameter ----------

def test_a_search_term_is_matched_literally_not_as_a_wildcard():
    assert storeroom_repository._like("50%") == "%50[%]%"
    assert storeroom_repository._like("a_b") == "%a[_]b%"
    assert storeroom_repository._like("[x]") == "%[[]x[]]%"
    assert storeroom_repository._like("  fan  ") == "%fan%"


def test_search_builds_one_bound_parameter_per_column_and_never_embeds_the_text():
    stock = get_dataset("stock")
    where, params = storeroom_repository._where(stock, "x'; DROP TABLE Cases;--")
    assert "DROP" not in where and "?" in where
    assert len(params) == len(stock.search_exprs) and "DROP" in params[0]
    assert storeroom_repository._where(stock, "") == ("", [])
    assert storeroom_repository._where(stock, "   ") == ("", [])
    assert storeroom_repository._where(stock, None) == ("", [])


# ---------- shaping rows ----------

def test_rows_become_json_friendly():
    invoices = get_dataset("invoices")
    row = {c.key: None for c in invoices.columns}
    row.update(amount=Decimal("42000.50"), case="3F2B8C1A-1111-4222-8333-444455556666", issues='["Total differs", "Duplicate"]')
    shaped = storeroom_controller._shape(invoices, row)
    assert shaped["amount"] == 42000.5 and isinstance(shaped["amount"], float)
    assert shaped["issues"] == ["Total differs", "Duplicate"]
    assert shaped["case"] == "3F2B8C1A-1111-4222-8333-444455556666"


@pytest.mark.parametrize("raw,expected", [(None, []), ("", []), ("[]", []), ('["a"]', ["a"]), ("not json", ["not json"]), ('"single"', ["single"])])
def test_stored_json_lists_never_break_the_page(raw, expected):
    assert storeroom_controller._as_list(raw) == expected


@pytest.mark.parametrize("cell", ["=cmd|' /C calc'!A0", "+1+1", "-2+3", "@SUM(A1)"])
def test_a_cell_that_would_run_as_an_excel_formula_is_defused(cell):
    assert storeroom_controller._csv_cell(cell).startswith("'")


def test_ordinary_cells_are_left_alone():
    assert storeroom_controller._csv_cell("Acme Supplies") == "Acme Supplies"
    assert storeroom_controller._csv_cell(None) == "" and storeroom_controller._csv_cell(42000.5) == "42000.5"
    assert storeroom_controller._csv_cell(["a", "b"]) == "a; b"


# ---------- over HTTP ----------

@pytest.fixture
def people(monkeypatch):
    users = {
        "alice": SimpleNamespace(user_id="alice", username="alice@x.co", role="user", is_active=True),
        "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True),
        "view": SimpleNamespace(user_id="view", username="view@x.co", role="viewer", is_active=True),
    }
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]),
        "viewer": set(DEFAULT_ROLE_PERMISSIONS["viewer"]), "user": set(DEFAULT_ROLE_PERMISSIONS["user"])})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    audited = []
    monkeypatch.setattr(storeroom_controller.audit, "record", lambda action, **kw: audited.append((action, kw)))
    calls = []

    def count(dataset, search=None):
        return 7

    def page(dataset, search, limit, offset):
        calls.append((dataset.key, search, limit, offset))
        return [{c.key: None for c in dataset.columns} | {"item": "Laptop", "quantity": 100}] if dataset.key == "stock" else []

    monkeypatch.setattr(storeroom_repository, "count", count)
    monkeypatch.setattr(storeroom_repository, "page", page)
    access.invalidate()
    yield calls, audited
    access.invalidate()


def as_(uid, role):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def test_requesters_cannot_open_the_store_room(people):
    for path in ("/store-room", "/store-room/stock", "/store-room/stock/export", "/store-room/requests"):
        assert client.get(path, headers=as_("alice", "user")).status_code == 403, path


def test_it_needs_a_login():
    assert client.get("/store-room").status_code == 401


@pytest.mark.parametrize("uid,role", [("mgr", "manager"), ("view", "viewer")])
def test_staff_can_browse_it(people, uid, role):
    assert client.get("/store-room", headers=as_(uid, role)).status_code == 200


def test_the_overview_lists_every_dataset_with_its_count(people):
    body = client.get("/store-room", headers=as_("mgr", "manager")).json()
    listed = [d["key"] for g in body["groups"] for d in g["datasets"]]
    assert listed == [d.key for d in DATASETS] and all(d["count"] == 7 for g in body["groups"] for d in g["datasets"])


def test_a_dataset_page_returns_columns_rows_and_the_total(people):
    calls, _ = people
    body = client.get("/store-room/stock?search=lap&limit=10&offset=20", headers=as_("mgr", "manager")).json()
    assert [c["key"] for c in body["columns"]] == ["item", "quantity", "level", "updated", "note"]
    assert body["rows"][0]["item"] == "Laptop" and body["total"] == 7 and body["limit"] == 10 and body["offset"] == 20
    assert calls[-1] == ("stock", "lap", 10, 20)


def test_an_unknown_dataset_is_not_found(people):
    assert client.get("/store-room/users", headers=as_("mgr", "manager")).status_code == 404
    assert client.get("/store-room/passwords/export", headers=as_("mgr", "manager")).status_code == 404


@pytest.mark.parametrize("query", ["limit=0", "limit=500", "offset=-1", "search=" + "x" * 101])
def test_silly_paging_or_search_is_rejected(people, query):
    assert client.get(f"/store-room/stock?{query}", headers=as_("mgr", "manager")).status_code == 422


def test_export_is_a_csv_download_and_is_audited_under_the_caller(people):
    _, audited = people
    r = client.get("/store-room/stock/export?search=lap", headers=as_("mgr", "manager"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="stock.csv"' in r.headers["content-disposition"]
    assert r.text.lstrip("﻿").splitlines()[0] == "Item,Available,Level,Last updated,Note"
    assert audited[0][0] == "storeroom.export" and audited[0][1]["actor_username"] == "mgr@x.co"


def test_staff_defaults_include_the_permission_but_requesters_do_not():
    assert "storeroom:read" in DEFAULT_ROLE_PERMISSIONS["manager"] and "storeroom:read" in DEFAULT_ROLE_PERMISSIONS["viewer"]
    assert "storeroom:read" not in DEFAULT_ROLE_PERMISSIONS["user"]


def test_the_stock_note_comes_from_the_latest_ledger_entry_being_a_cancelled_request_and_is_plain_text():
    from app.core.storeroom_catalog import DATASETS
    note = next(c for d in DATASETS if d.key == "stock" for c in d.columns if c.key == "note")
    assert note.kind == "note" and "cancelled_returned" in note.expr and "ORDER BY l.created_at DESC" in note.expr and "TOP 1" in note.expr
    assert "Returned to stock" in note.expr
