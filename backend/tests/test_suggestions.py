"""The one-sentence suggestion on a decision: does it match, and what would the system do."""

from app.controllers import invoice_suggestions
from app.core.exceptions import PurchaseOrderNotFound
from app.core.suggestions import approval_suggestion, invoice_suggestion, rupees

PO = {"total_amount": 95000.0, "vendor_id": "v1", "po_number": "PO-1005"}


def inv(status="mismatch", total=120000.0, number="INV-2001", issues=None):
    return {"status": status, "total_amount": total, "invoice_number": number, "issues": issues or [], "case_id": "c1"}


def suggest(invoice, po=PO, received=True):
    return invoice_suggestion(invoice, po, received, 1.0)


def test_money_is_written_the_way_people_read_it():
    assert rupees(95000.0) == "₹95,000" and rupees(95000.5) == "₹95,000.50" and rupees(None) == "—"


def test_an_invoice_that_matched_says_so_and_asks_nothing_of_the_person():
    s = suggest(inv("matched", 95000.0))
    assert s == {"verdict": "match", "text": "Matches the order and the receipt. Nothing for you to do."}


def test_a_much_higher_total_says_by_how_much_and_suggests_rejecting():
    s = suggest(inv(issues=["Invoice total 120,000.00 differs from the purchase order total 95,000.00."]))
    assert s["verdict"] == "mismatch"
    assert s["text"] == ("Doesn't match: the total is ₹25,000 (26%) higher than the order (₹120,000 against ₹95,000). "
                         "Suggest: reject and ask for a corrected invoice.")


def test_a_slightly_higher_total_is_called_a_small_gap_for_the_person_to_judge():
    s = suggest(inv(total=97000.0, issues=["Invoice total 97,000.00 differs from the purchase order total 95,000.00."]))
    assert "₹2,000 (2%) higher" in s["text"] and "small gap" in s["text"] and "approve anyway only if the supplier explained it" in s["text"]


def test_a_lower_total_suggests_checking_whether_something_is_missing():
    s = suggest(inv(total=80000.0, issues=["Invoice total 80,000.00 differs from the purchase order total 95,000.00."]))
    assert "₹15,000 (16%) lower" in s["text"] and "whether anything is missing" in s["text"]


def test_a_second_problem_is_mentioned_and_stops_it_being_called_a_small_gap():
    s = suggest(inv(total=97000.0, issues=["Invoice total 97,000.00 differs from the purchase order total 95,000.00.",
                                           "The invoice bills 55 item(s) but 60 were ordered."]))
    assert "Also: The invoice bills 55 item(s) but 60 were ordered." in s["text"] and "small gap" not in s["text"] and "reject" in s["text"]


def test_a_possible_duplicate_is_called_out_first():
    s = suggest(inv(issues=["Invoice INV-2001 was already submitted by this vendor (possible duplicate)."]))
    assert s["verdict"] == "mismatch" and s["text"].startswith("Looks like a duplicate: invoice INV-2001") and s["text"].endswith("Suggest: reject.")


def test_an_unreadable_total_or_number_says_to_enter_it_by_hand():
    assert "Couldn't read the total" in suggest(inv(total=None))["text"] and suggest(inv(total=None))["verdict"] == "check"
    assert "Couldn't read the invoice number" in suggest(inv(number=None, total=95000.0))["text"]


def test_a_wrong_order_number_or_quantity_is_explained_even_when_the_total_is_right():
    s = suggest(inv(total=95000.0, issues=["The invoice quotes PO-9, but this case's order is PO-1005."]))
    assert s["verdict"] == "mismatch" and s["text"] == "Doesn't match: The invoice quotes PO-9, but this case's order is PO-1005. Suggest: reject and ask for a corrected invoice."


def test_a_correct_invoice_waiting_for_the_goods_says_it_matches_and_who_it_waits_for():
    s = suggest(inv("on_hold", 95000.0, issues=["Waiting for the goods to be confirmed as received."]), received=False)
    assert s["verdict"] == "waiting" and s["text"].startswith("Matches the order (₹95,000). Waiting for Receiving")


def test_a_decided_invoice_has_no_suggestion():
    assert suggest(inv("rejected")) is None and suggest(inv("approved")) is None


def test_without_an_order_to_compare_it_still_says_something_sensible():
    assert suggest(inv("mismatch", issues=["The purchase order has no agreed total to compare the invoice against."]), po=None)["verdict"] == "mismatch"


# ------------------------------------------------------------------------------------------------ approvals

def opt(vid, name, price, days, terms):
    return {"vendor_id": vid, "vendor_name": name, "price": price, "lead_time_days": days, "terms": terms}


THREE = [opt("a", "Acme", 95000.0, 5, "net 30"), opt("g", "Globex", 98500.0, 3, "50% advance"), opt("i", "Initech", 92000.0, 7, "net 15")]


def test_the_approval_suggestion_names_the_pick_and_what_the_others_do_better():
    assert approval_suggestion(THREE, "a") == ("Suggest: approve Acme (₹95,000, 5 days, net 30). Initech is ₹3,000 cheaper but 2 days slower. "
                                               "Globex is 2 days faster but ₹3,500 dearer.")


def test_when_the_pick_is_also_the_cheapest_only_the_speed_trade_off_is_mentioned():
    s = approval_suggestion(THREE, "i")
    assert s.startswith("Suggest: approve Initech (₹92,000, 7 days, net 15).") and "cheaper" not in s and "Globex is 4 days faster" in s


def test_one_reply_says_so_and_a_missing_price_says_to_check_the_reply():
    assert approval_suggestion([THREE[0]], "a").startswith("Only Acme has replied (₹95,000, 5 days, net 30). Suggest: approve if that price is acceptable")
    assert "no readable price" in approval_suggestion([opt("a", "Acme", None, 5, None)], "a")


def test_no_replies_says_to_wait():
    assert approval_suggestion([], None) == "No supplier has replied yet. Wait for quotes before deciding."


# ------------------------------------------------------------------------------------- joining it to the order

def test_the_suggestions_are_worked_out_against_each_cases_order_and_receipt(monkeypatch):
    seen = {"po": 0, "delivery": 0}
    monkeypatch.setattr(invoice_suggestions.purchase_order_agent, "find_purchase_order", lambda cid: seen.__setitem__("po", seen["po"] + 1) or PO)
    monkeypatch.setattr(invoice_suggestions.delivery_agent, "get_delivery", lambda cid: seen.__setitem__("delivery", seen["delivery"] + 1) or {"delivery_status": "delivered"})
    out = invoice_suggestions.attach_suggestions([
        {**inv("mismatch", issues=["x"]), "invoice_id": "1"}, {**inv("on_hold", 95000.0), "invoice_id": "2"}, {**inv("rejected"), "invoice_id": "3"}])
    assert [o["verdict"] for o in out] == ["mismatch", "waiting", None] and out[2]["suggestion"] is None
    assert seen == {"po": 1, "delivery": 1}                                   # one lookup per case, not per invoice


def test_a_case_with_no_order_yet_still_gets_a_sentence(monkeypatch):
    def none(cid):
        raise PurchaseOrderNotFound(cid)
    monkeypatch.setattr(invoice_suggestions.purchase_order_agent, "find_purchase_order", lambda cid: None)
    monkeypatch.setattr(invoice_suggestions.delivery_agent, "get_delivery", none)
    out = invoice_suggestions.attach_suggestions([{**inv("mismatch", issues=["The purchase order has no agreed total to compare the invoice against."]), "invoice_id": "1"}])
    assert out[0]["verdict"] == "mismatch"


def test_a_suggestion_respects_the_needed_by_date():
    from datetime import date
    late = lambda vid, price: {"vendor_id": vid, "vendor_name": vid, "price": price, "lead_time_days": 5, "terms": "net 30", "tags": ["Too late"]}
    ok = {"vendor_id": "B", "vendor_name": "B", "price": 40000.0, "lead_time_days": 2, "terms": "net 30", "tags": ["Arrives in time"]}
    d = date(2026, 10, 7)
    none_in_time = approval_suggestion([late("A", 30000.0), late("B", 31000.0)], "A", d)
    assert none_in_time.startswith("None of the suppliers can deliver by 07 Oct") and "approve A" in none_in_time and "late" in none_in_time
    assert approval_suggestion([late("A", 30000.0), ok], "A", d).startswith("Suggest: approve B")        # the pick cannot make it, another can
    assert approval_suggestion([late("A", 30000.0), late("B", 31000.0)], "A").startswith("Suggest: approve A")   # no date: unchanged
