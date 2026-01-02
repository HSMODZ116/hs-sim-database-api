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

# Developer
DEVELOPER = "Haseeb Sahil"

# -------------------------
# Helpers
# -------------------------
def is_mobile(value: str) -> bool:
    return bool(re.fullmatch(r"92\d{10}", value))

def is_local_mobile(value: str) -> bool:
    return bool(re.fullmatch(r"03\d{9}", value))

def is_cnic(value: str) -> bool:
    return bool(re.fullmatch(r"\d{13}", value))

def normalize_mobile(value: str) -> str:
    value = value.strip()
    if is_mobile(value):
        return value
    if is_local_mobile(value):
        return "92" + value[1:]
    return value

def classify_query(value: str):
    v = value.strip()
    if is_cnic(v):
        return "cnic", v

    normalized = normalize_mobile(v)
    if is_mobile(normalized):
        return "mobile", normalized

    raise ValueError(
        "Invalid query. Use CNIC (13 digits) or mobile (03XXXXXXXXX / 92XXXXXXXXXX)."
    )

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
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Referer": TARGET_BASE.rstrip("/") + "/",
        "Accept-Language": "en-US,en;q=0.9",
    }

    url = TARGET_BASE.rstrip("/") + TARGET_PATH
    data = {"search_query": query_value}

    resp = session.post(url, headers=headers, data=data, timeout=20)
    resp.raise_for_status()
    return resp.text

# -------------------------
# ✅ FIXED: Duplicate remover
# -------------------------
def parse_table(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "api-response"}) or soup.find("table")
    if not table:
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    results = []
    seen = set()

    for tr in tbody.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]

        mobile = cols[0] if len(cols) > 0 else None
        name = cols[1] if len(cols) > 1 else None
        cnic = cols[2] if len(cols) > 2 else None
        address = cols[3] if len(cols) > 3 else None

        key = (mobile, cnic, name)
        if key in seen:
            continue

        seen.add(key)

        results.append({
            "mobile": mobile,
            "name": name,
            "cnic": cnic,
            "address": address
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
    sample_get = url_for("api_lookup_get", _external=False) + "?query=03068060398&pretty=1"
    return f"""
<!DOCTYPE html>
<html>
<head>
<title>HS Pakistan SIM & CNIC Intelligence API</title>
</head>
<body style="background:#0b0f19;color:#e5e7eb;font-family:Arial;padding:30px">
<h1>🔍 HS Pakistan SIM & CNIC Intelligence API</h1>
<p>🟢 Status: LIVE</p>
<p>👑 Developer: {DEVELOPER}</p>
<p>Example: <a href="{sample_get}" style="color:#38bdf8">{sample_get}</a></p>
</body>
</html>
"""

@app.route("/api/lookup", methods=["GET"])
def api_lookup_get():
    q = request.args.get("query") or request.args.get("q") or request.args.get("value")
    pretty = request.args.get("pretty") in ("1", "true", "True")

    if not q:
        return respond_json({"error": "Use ?query=<mobile or cnic>"}, pretty), 400

    try:
        qtype, normalized = classify_query(q)
        html = fetch_upstream(normalized)
        results = parse_table(html)
        return respond_json(make_response_object(normalized, qtype, results), pretty)
    except Exception as e:
        return respond_json({"error": str(e)}, pretty), 500

@app.route("/api/lookup/<path:q>", methods=["GET"])
def api_lookup_path(q):
    pretty = request.args.get("pretty") in ("1", "true", "True")
    try:
        qtype, normalized = classify_query(q)
        html = fetch_upstream(normalized)
        results = parse_table(html)
        return respond_json(make_response_object(normalized, qtype, results), pretty)
    except Exception as e:
        return respond_json({"error": str(e)}, pretty), 500

@app.route("/api/lookup", methods=["POST"])
def api_lookup_post():
    pretty = request.args.get("pretty") in ("1", "true", "True")
    data = request.get_json(force=True, silent=True) or {}
    q = data.get("query") or data.get("number")

    if not q:
        return respond_json({"error": "Send JSON {\"query\":\"...\"}"}, pretty), 400

    try:
        qtype, normalized = classify_query(q)
        html = fetch_upstream(normalized)
        results = parse_table(html)
        return respond_json(make_response_object(normalized, qtype, results), pretty)
    except Exception as e:
        return respond_json({"error": str(e)}, pretty), 500

@app.route("/health")
def health():
    return respond_json({"status": "ok", "developer": DEVELOPER})

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)