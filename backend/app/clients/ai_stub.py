"""A stand-in for Azure OpenAI for automated end-to-end tests only (core/test_switches.py refuses to start the app unless it is a *_test
database and not production). Simple fixed rules, so every run gives the same answers, costs nothing and needs no network.

To control exactly what a request means, start the request text with  TESTJSON:  followed by the JSON the Purchase Agent should "read":
    TESTJSON: {"items": [{"description": "Steel storage rack", "quantity": 8}], "cost_center": null}
Otherwise "Need 8 steel storage racks, urgent, needed by 2026-10-20" is read with simple patterns (a number, then the item).
"""

import ast
import json
import re

_MONEY = r"(?:Rs\.?|INR|₹)\s*"


def ask_json(system_prompt: str, user_prompt: str, temperature: float = 0.1, images: list[str] | None = None) -> dict:
    user_prompt = _with_picture_text(user_prompt, images)
    if "Procurement Agent" in system_prompt:
        return {"stock_item": None}                                   # only same-product wording matches stock; never a guess
    if "Purchase Agent" in system_prompt:
        return _read_request(user_prompt)
    if "raw vendor quote" in system_prompt:
        return _read_quote(user_prompt)
    if "Rank ALL the vendors" in system_prompt:
        return _rank(user_prompt)
    if "You are the PO Agent" in system_prompt and "to CANCEL a purchase order" in system_prompt:
        return _cancel_reply(user_prompt)
    if "You are the PO Agent" in system_prompt:
        return _po_reply(user_prompt)
    if "Invoice Agent" in system_prompt:
        return _invoice(user_prompt)
    raise AssertionError(f"The AI stub does not know this prompt: {system_prompt[:80]}")


def _with_picture_text(user_prompt: str, images: list[str] | None) -> str:
    """Tests cannot do real OCR. A fake page picture whose bytes start with TESTVISION: is "read" as the text after it; any other
    picture is unreadable (adds nothing), like a blurry scan."""
    import base64
    extra = []
    for image in images or []:
        try:
            raw = base64.b64decode(image)
        except Exception:
            continue
        if raw.startswith(b"TESTVISION:"):
            extra.append(raw[len(b"TESTVISION:"):].decode("utf-8", errors="replace"))
    if not extra:
        return user_prompt
    base = "" if user_prompt.startswith("(scanned document") else user_prompt      # the pipeline's placeholder for "see the pictures"
    return "\n".join(part for part in [base, *extra] if part)


def ask_text(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
    return "(test summary)"


def _read_request(text: str) -> dict:
    marker = "TESTJSON:"
    if marker in text:
        return json.loads(text.split(marker, 1)[1].strip())
    items = []
    for number, name in re.findall(r"(\d+)\s*(?:x|nos|pcs|units)?\s+([A-Za-z][A-Za-z0-9 \-/]*?)(?=\s+(?:for|by|needed|urgent|please|asap)\b|[.,;:\n]|$)", text, re.I):
        items.append({"description": name.strip(), "quantity": int(number)})
    needed = re.search(r"needed by (\d{4}-\d{2}-\d{2})", text, re.I)
    return {"items": items, "cost_center": None, "needed_by": needed.group(1) if needed else None, "urgent": bool(re.search(r"\burgent\b", text, re.I))}


def _read_quote(text: str) -> dict:
    price = re.search(_MONEY + r"([\d,]+)", text)
    days = re.search(r"(?<!valid )(?<!for )(\d+) days", text, re.I)
    terms = re.search(r"Terms: (.+)", text)
    valid = re.search(r"valid (?:for )?(\d+) days", text, re.I)
    return {"price": float(price.group(1).replace(",", "")) if price else None,
            "valid_days": int(valid.group(1)) if valid else None,
            "lead_time_days": int(days.group(1)) if days else None,
            "terms": terms.group(1).strip() if terms else None}


def _rank(user_prompt: str) -> dict:
    quotes = ast.literal_eval(user_prompt[len("Quotes: "):])
    by_price = sorted((q for q in quotes if q["price"] is not None), key=lambda q: q["price"])
    return {"ranking": [{"vendor_id": q["vendor_id"], "reason": f"{q['vendor_name']} is #{i + 1} on price."} for i, q in enumerate(by_price)],
            "recommended_vendor_id": by_price[0]["vendor_id"], "rationale": f"{by_price[0]['vendor_name']} is cheapest."}


def _cancel_reply(text: str) -> dict:
    low = text.lower()
    if any(w in low for w in ("cannot be cancelled", "can't cancel", "already shipped", "already dispatched")):
        return {"kind": "refused"}
    if any(w in low for w in ("cancelled", "agree", "no problem")):
        return {"kind": "agreed"}
    return {"kind": "other"}


def _po_reply(text: str) -> dict:
    low = text.lower()
    asked = re.search(r"(?:now|revised|new)[^0-9]{0,20}([\d,]{4,})", low)
    if asked:
        return {"kind": "problem", "issue": "Asks for a different price.", "new_price": float(asked.group(1).replace(",", ""))}
    if any(w in low for w in ("cannot", "can't", "unable", "sorry", "price has gone up")):
        return {"kind": "problem", "issue": "The supplier says they cannot deliver as ordered."}
    if any(w in low for w in ("confirm", "received your order", "will deliver", "order received", "accepted")):
        return {"kind": "confirmed", "issue": None}
    return {"kind": "other", "issue": None}


def _invoice(text: str) -> dict:
    if not text.lstrip().lower().startswith("invoice"):
        return {"is_invoice": False, "invoice_number": None, "total_amount": None, "po_number": None, "items": []}
    number = re.search(r"Invoice (\S+?)[ .,]", text)
    total = re.search(r"Total " + _MONEY + r"([\d,]+)", text)
    po = re.search(r"PO-\d+", text)
    qty = re.search(r"(\d+) x ([\w ]+?)[.,]", text)
    subtotal = re.search(r"Subtotal " + _MONEY + r"([\d,.]+?)[.,]? ", text + " ")
    rate = re.search(r"(?:GST|Tax) (\d+(?:\.\d+)?)%", text)
    tax_amount = re.search(r"Tax amount " + _MONEY + r"([\d,.]+?)[.,]? ", text + " ")
    return {"is_invoice": True, "invoice_number": number.group(1) if number else None,
            "subtotal": float(subtotal.group(1).replace(",", "")) if subtotal else None,
            "tax_rate_pct": float(rate.group(1)) if rate else None,
            "tax_amount": float(tax_amount.group(1).replace(",", "")) if tax_amount else None,
            "total_amount": float(total.group(1).replace(",", "")) if total else None,
            "po_number": po.group(0) if po else None,
            "items": [{"description": qty.group(2), "quantity": int(qty.group(1))}] if qty else []}
