import pytest

from app.agents import procurement_agent
from app.core.stock_matching import match_exact, normalize
from scripts.stock_catalog import STOCK

from .fake_world import World, standard_world

NAMES = [name for name, _ in STOCK]


# ---------- same product, different wording: matches ----------

@pytest.mark.parametrize("asked,expected", [
    ("Laptop", "Laptop"),
    ("laptops", "Laptop"),
    ("LAPTOPS", "Laptop"),
    ("  laptop  ", "Laptop"),
    ("tab", "Tablet"),
    ("tabs", "Tablet"),
    ("tablets", "Tablet"),
    ("phone", "Mobile phone"),
    ("mobile", "Mobile phone"),
    ("smartphones", "Mobile phone"),
    ("mobile phones", "Mobile phone"),
    ("ceiling fans", "Ceiling fan"),
    ("fan, ceiling", "Ceiling fan"),
    ("24 inch monitor", "Monitor 24 inch"),
    ("24-inch monitors", "Monitor 24 inch"),
    ("monitor 24 inch", "Monitor 24 inch"),
    ("a4 paper reams", "A4 paper ream"),
    ("wi-fi routers", "Wi-Fi router"),
    ("cctv cameras", "CCTV camera"),
    ("5 pcs LED bulb", "LED bulb"),
    ("fridge", "Refrigerator"),
    ("office chairs", "Office chair"),
    ("network switches 24 port", "Network switch 24 port"),
])
def test_equivalent_wording_matches(asked, expected):
    assert match_exact(asked, NAMES) == expected


# ---------- not clearly the same product: does NOT match (goes to suppliers, never the wrong item) ----------

@pytest.mark.parametrize("asked", [
    "fan",                       # ceiling fan or table fan?
    "monitor",                   # 24 inch or 27 inch?
    "screens",                   # a word we do not guess
    "air conditioner",           # stock row has a capacity the request lacks
    "Dell laptop",               # a specific brand the stock row doesn't promise
    "gaming laptop",
    "laptop bag",                # a different product containing the word
    "mobile charger 65w",
    "48 inch monitor",           # a size we don't hold
    "server",
    "",
    "   ",
])
def test_anything_less_than_clearly_the_same_item_does_not_match(asked):
    assert match_exact(asked, NAMES) is None


def test_two_stock_rows_that_look_identical_are_never_guessed_between():
    assert match_exact("laptop", ["Laptop", "Laptops"]) is None


def test_normalising_ignores_order_case_plurals_and_punctuation():
    assert normalize("Monitors, 24-INCH") == normalize("24 inch monitor")
    assert normalize("batteries") == normalize("battery")
    assert normalize("switches") == normalize("switch")
    assert normalize("glass") == ("glass",) and normalize("bus") == ("bus",)    # not mangled


# ---------- the AI fallback is held to the same standard ----------

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def _case_for(w, text, items):
    w.teach(text, items)
    return w.submit(text)


def test_different_wording_is_fulfilled_from_stock_without_asking_the_ai(w, monkeypatch):
    def guard(system, user, temperature=0.1):
        if "Procurement Agent" in system:
            pytest.fail("the AI should not be needed to match plain different wording")
        return w._fake_ai(system, user, temperature)

    monkeypatch.setattr(procurement_agent.azure_openai_client, "ask_json", guard)
    case_id = _case_for(w, "5 laptops please", [{"description": "laptops", "quantity": 5}])
    assert w.stage(case_id) == "fulfilled_from_stock"
    assert w.stock["laptop"].quantity_available == 95          # deducted from the real stock row
    check = next(e for e in w.events[case_id] if e.event_type == "stock.checked").payload["checks"][0]
    assert check["description"] == "laptops" and check["stock_item"] == "Laptop"


def test_a_vague_request_the_ai_is_unsure_about_goes_to_suppliers(w):
    case_id = _case_for(w, "need some screens", [{"description": "screens", "quantity": 4}])
    assert w.stage(case_id) == "awaiting_quotes"               # the fake AI answers null


def test_a_clear_match_the_ai_finds_is_used(w):
    w.add_stock("Mobile phone", 25)
    w.stock_ai["handset"] = "Mobile phone"
    case_id = _case_for(w, "2 handsets", [{"description": "handset", "quantity": 2}])
    assert w.stage(case_id) == "fulfilled_from_stock"
    assert w.stock["mobile phone"].quantity_available == 23


def test_an_item_the_ai_invents_is_rejected(w):
    w.stock_ai["gizmo"] = "Quantum flux capacitor"            # not a real stock row
    case_id = _case_for(w, "a gizmo", [{"description": "gizmo", "quantity": 1}])
    assert w.stage(case_id) == "awaiting_quotes"


def test_an_ai_outage_never_blocks_a_request(w, monkeypatch):
    def down(system, user, temperature=0.1):
        if "Procurement Agent" in system:
            raise RuntimeError("Azure OpenAI is down")
        return w._fake_ai(system, user, temperature)

    monkeypatch.setattr(procurement_agent.azure_openai_client, "ask_json", down)
    case_id = _case_for(w, "need a gizmo", [{"description": "gizmo", "quantity": 1}])
    assert w.stage(case_id) == "awaiting_quotes"               # falls through to suppliers


def test_not_enough_of_a_matched_item_still_goes_to_suppliers(w):
    case_id = _case_for(w, "30 cameras", [{"description": "cctv cameras", "quantity": 30}])
    assert w.stage(case_id) == "awaiting_quotes"               # 20 in stock, 30 wanted
    assert w.stock["cctv camera"].quantity_available == 20     # nothing deducted


def test_a_mixed_request_is_all_or_nothing(w):
    case_id = _case_for(w, "laptops and a rack", [{"description": "laptops", "quantity": 2},
                                                  {"description": "server rack", "quantity": 1}])
    assert w.stage(case_id) == "awaiting_quotes"               # rack has 0 in stock
    assert w.stock["laptop"].quantity_available == 100         # laptops not deducted either


def test_the_stock_catalogue_has_no_ambiguous_names():
    """Two stock rows that normalise the same would make matching ambiguous: catch it in the data."""
    keys = [normalize(n) for n in NAMES]
    assert len(keys) == len(set(keys))
