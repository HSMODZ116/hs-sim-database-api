import os
import re
import time
import json
import requests
from flask import Flask, request, Response, url_for
from bs4 import BeautifulSoup

app = Flask(__name__)

# -------------------------
# Config
# -------------------------
TARGET_BASE = os.getenv("TARGET_BASE", "https://pakistandatabase.com")
TARGET_PATH = os.getenv("TARGET_PATH", "/databases/sim.php")
ALLOW_UPSTREAM = True
MIN_INTERVAL = float(os.getenv("MIN_INTERVAL", "1.0"))
LAST_CALL = {"ts": 0.0}

# Developer Copyright
DEVELOPER = "Haseeb Sahil"

# -------------------------
# Helpers
# -------------------------
def is_mobile(value: str) -> bool:
    return bool(re.fullmatch(r"92\d{9,12}", (value or "").strip()))

def is_cnic(value: str) -> bool:
    return bool(re.fullmatch(r"\d{13}", (value or "").strip()))

def classify_query(value: str):
    v = value.strip()
    if is_mobile(v):
        return "mobile", v
    if is_cnic(v):
        return "cnic", v
    raise ValueError("Invalid query. Use mobile with country code (92...) or CNIC (13 digits).")

def rate_limit_wait():
    now = time.time()
    elapsed = now - LAST_CALL["ts"]
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    LAST_CALL["ts"] = time.time()

def fetch_upstream(query_value: str):
    if not ALLOW_UPSTREAM:
        raise PermissionError("Upstream fetching disabled.")
    rate_limit_wait()

    session = requests.Session()
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/140.0.0.0 Safari/537.36"),
        "Referer": TARGET_BASE.rstrip("/") + "/",
        "Accept-Language": "en-US,en;q=0.9",
    }

    url = TARGET_BASE.rstrip("/") + TARGET_PATH
    data = {"search_query": query_value}

    resp = session.post(url, headers=headers, data=data, timeout=20)
    resp.raise_for_status()
    return resp.text

def parse_table(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "api-response"}) or soup.find("table")
    if not table:
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    results = []
    for tr in tbody.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        results.append({
            "mobile": cols[0] if len(cols) > 0 else None,
            "name": cols[1] if len(cols) > 1 else None,
            "cnic": cols[2] if len(cols) > 2 else None,
            "address": cols[3] if len(cols) > 3 else None,
        })

    return results


def make_response_object(query, qtype, results):
    return {
        "query": query,
        "query_type": qtype,
        "results_count": len(results),
        "results": results,
        "developer": DEVELOPER  
    }


def respond_json(obj, pretty=False):
    text = json.dumps(obj, indent=2 if pretty else None, ensure_ascii=False)
    return Response(text, mimetype="application/json; charset=utf-8")


# -------------------------
# Routes
# -------------------------

@app.route("/", methods=["GET"])
def home():
    sample_get = url_for("api_lookup_get", _external=False) + "?query=923323312487&pretty=1"
    return (
        "<h2>Pakistan Number/CNIC Info API - Live Mode</h2>"
        f"<p>Mode: LIVE | Developer: {DEVELOPER}</p>"
        "<p>Use GET or POST:</p>"
        f"<ul>"
        f"<li>GET /api/lookup?query=&lt;value&gt;&amp;pretty=1 — example: "
        f"<a href='{sample_get}'>{sample_get}</a></li>"
        f"<li>GET /api/lookup/&lt;value&gt; — example: /api/lookup/923323312487</li>"
        f"<li>POST /api/lookup with JSON <code>{{\"query\":\"923...\"}}</code></li>"
        f"</ul>"
    )


@app.route("/api/lookup", methods=["GET"])
def api_lookup_get():
    q = request.args.get("query") or request.args.get("q") or request.args.get("value")
    pretty = request.args.get("pretty") in ("1", "true", "True")

    if not q:
        return respond_json({"error": "Use ?query=<mobile or cnic>", "developer": DEVELOPER}, pretty), 400

    try:
        qtype, normalized = classify_query(q)
    except ValueError as e:
        return respond_json({"error": "Invalid query", "detail": str(e), "developer": DEVELOPER}, pretty), 400

    try:
        html = fetch_upstream(normalized)
    except Exception as e:
        return respond_json({"error": "Fetch failed", "detail": str(e), "developer": DEVELOPER}, pretty), 500

    results = parse_table(html)
    obj = make_response_object(normalized, qtype, results)
    return respond_json(obj, pretty)


@app.route("/api/lookup/<path:q>", methods=["GET"])
def api_lookup_path(q):
    pretty = request.args.get("pretty") in ("1", "true", "True")

    try:
        qtype, normalized = classify_query(q)
    except ValueError as e:
        return respond_json({"error": "Invalid query", "detail": str(e), "developer": DEVELOPER}, pretty), 400

    try:
        html = fetch_upstream(normalized)
    except Exception as e:
        return respond_json({"error": "Fetch failed", "detail": str(e), "developer": DEVELOPER}, pretty), 500

    results = parse_table(html)
    obj = make_response_object(normalized, qtype, results)
    return respond_json(obj, pretty)


@app.route("/api/lookup", methods=["POST"])
def api_lookup_post():
    pretty = request.args.get("pretty") in ("1", "true", "True")
    data = request.get_json(force=True, silent=True) or {}

    q = data.get("query") or data.get("number") or data.get("value")

    if not q:
        return respond_json({"error": "Send JSON {\"query\":\"...\"}", "developer": DEVELOPER}, pretty), 400

    try:
        qtype, normalized = classify_query(q)
    except ValueError as e:
        return respond_json({"error": "Invalid query", "detail": str(e), "developer": DEVELOPER}, pretty), 400

    try:
        html = fetch_upstream(normalized)
    except Exception as e:
        return respond_json({"error": "Fetch failed", "detail": str(e), "developer": DEVELOPER}, pretty), 500

    results = parse_table(html)
    obj = make_response_object(normalized, qtype, results)
    return respond_json(obj, pretty)


@app.route("/health", methods=["GET"])
def health():
    return respond_json({"status": "ok", "developer": DEVELOPER})


# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)