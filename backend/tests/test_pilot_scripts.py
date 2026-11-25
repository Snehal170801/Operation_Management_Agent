from types import SimpleNamespace

import pytest

from scripts.seed_pilot import plus_address, plan


def args(**kw):
    base = dict(single_mailbox=None, admin=None, manager=None, user=None, vendor_mailbox=None)
    return SimpleNamespace(**{**base, **kw})


def test_supplier_emails_land_in_the_pilot_inbox():
    assert plus_address("pilot@co.com", "Acme") == "pilot+acme@co.com"


def test_tag_is_cleaned_into_a_safe_slug():
    assert plus_address("  pilot@co.com ", "Acme Supplies!") == "pilot+acmesupplies@co.com"


@pytest.mark.parametrize("bad", ["", "no-at-sign", "@co.com", "pilot@"])
def test_a_non_address_is_rejected(bad):
    with pytest.raises(ValueError):
        plus_address(bad, "acme")


# ---------- one email for everything ----------

def test_one_mailbox_gives_simple_usernames_and_only_the_manager_holds_the_email():
    accounts, suppliers = plan(args(single_mailbox="Me@Gmail.com"))
    assert [(u, r, e) for u, r, _, e in accounts] == [
        ("admin", "admin", None), ("manager", "manager", "me@gmail.com"), ("ravi", "user", None)]
    # a database may only hold an email once, so exactly one account carries it
    assert sum(1 for *_, e in accounts if e) == 1


def test_one_mailbox_is_used_for_every_supplier():
    _, suppliers = plan(args(single_mailbox="me@gmail.com"))
    assert set(suppliers.values()) == {"me@gmail.com"} and len(suppliers) == 3


def test_one_mailbox_must_be_an_address():
    with pytest.raises(ValueError):
        plan(args(single_mailbox="not-an-email"))


# ---------- separate addresses ----------

def test_separate_addresses_use_the_email_as_the_username_and_plus_addressed_suppliers():
    accounts, suppliers = plan(args(admin="a@co.com", manager="m@co.com", user="u@co.com", vendor_mailbox="p@co.com"))
    assert [(u, r) for u, r, _, _ in accounts] == [("a@co.com", "admin"), ("m@co.com", "manager"), ("u@co.com", "user")]
    assert suppliers["Acme Supplies"] == "p+acme@co.com" and suppliers["Initech Imports"] == "p+initech@co.com"


def test_separate_mode_says_what_is_missing():
    with pytest.raises(ValueError) as error:
        plan(args(admin="a@co.com"))
    assert "--manager" in str(error.value) and "--single-mailbox" in str(error.value)
