"""The installable app (PWA): a valid manifest with real icons, and a service worker that can never show stale or someone else's data.

The front end has no unit tests, so these read the files in frontend/public and frontend/index.html as the browser will."""

import json
import re
from pathlib import Path

from PIL import Image

PUBLIC = Path(__file__).resolve().parents[2] / "frontend" / "public"
INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
MAIN = Path(__file__).resolve().parents[2] / "frontend" / "src" / "main.tsx"


def manifest() -> dict:
    return json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))


def test_the_manifest_has_what_a_browser_needs_to_offer_installation():
    m = manifest()
    assert m["name"] and m["short_name"] and len(m["short_name"]) <= 12 and m["display"] == "standalone"
    assert m["start_url"] == "/" and m["scope"] == "/" and m["theme_color"].startswith("#") and m["background_color"].startswith("#")
    purposes = {(i["sizes"], i.get("purpose")) for i in m["icons"] if i["type"] == "image/png"}
    assert ("192x192", "any") in purposes and ("512x512", "any") in purposes and ("512x512", "maskable") in purposes


def test_every_icon_the_manifest_names_exists_and_is_the_size_it_claims():
    for icon in manifest()["icons"] + [i for s in manifest()["shortcuts"] for i in s["icons"]]:
        path = PUBLIC / icon["src"].lstrip("/")
        assert path.exists(), icon["src"]
        if icon["type"] == "image/png":
            width, height = icon["sizes"].split("x")
            assert Image.open(path).size == (int(width), int(height)), icon["src"]
    assert Image.open(PUBLIC / "icons" / "apple-touch-icon.png").size == (180, 180)


def test_the_shortcuts_go_to_real_pages():
    for shortcut in manifest()["shortcuts"]:
        assert shortcut["url"] in ("/approvals", "/my-work")


def test_the_page_links_the_manifest_the_theme_colour_and_the_iphone_icon():
    html = INDEX.read_text(encoding="utf-8")
    assert 'rel="manifest" href="/manifest.webmanifest"' in html and 'name="theme-color"' in html and 'rel="apple-touch-icon" href="/icons/apple-touch-icon.png"' in html
    assert "viewport-fit=cover" in html and 'name="apple-mobile-web-app-capable"' in html


def test_the_service_worker_only_stores_the_offline_page_and_never_touches_data():
    sw = (PUBLIC / "sw.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", sw, flags=re.S)                                  # (the comment explains it in words; the CODE is what counts)
    assert code.count("cache.addAll") == 1 and "'/offline.html'" in code and "/icons/icon-192.png" in code
    assert "cache.put" not in code and ".put(" not in code and "caches.open" in code and code.count("caches.open") == 1
    assert "request.mode !== 'navigate'" in code and "return" in code.split("request.mode !== 'navigate'")[1].split("\n")[0]       # anything but a page is left alone
    for forbidden in ("/auth", "/approvals", "/cases", "localStorage", "indexedDB", "Authorization", "clone()", "caches.match(request", "caches.match(event.request"):
        assert forbidden not in code, forbidden
    assert "push" not in code.lower() and "notification" not in code.lower()          # no push in this version
    assert "caches.match(OFFLINE)" in code                                           # the only thing ever served from the cache


def test_the_offline_page_is_static_and_carries_no_data_or_scripts_that_fetch():
    html = (PUBLIC / "offline.html").read_text(encoding="utf-8")
    assert "fetch(" not in html and "localStorage" not in html and "<script" not in html
    assert "location.reload()" in html


def test_the_worker_is_only_registered_by_a_real_build_and_failure_to_register_is_harmless():
    main = MAIN.read_text(encoding="utf-8")
    assert "import.meta.env.PROD" in main and "serviceWorker.register('/sw.js')" in main and ".catch(" in main
