import json, os, io
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template
import yaml, time
import cv2, numpy as np, requests

app = Flask(__name__, static_folder="static", template_folder="templates")
CFG_PATH = os.getenv("CONFIG_PATH", "/app/config/sensors.yaml")

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # /app
STATE_PATH = ROOT / "state" / "state.json"   # /app/state/state.json

def load_cfg():
    with open(CFG_PATH, "r") as f: return yaml.safe_load(f)

def save_cfg(cfg):
    with open(CFG_PATH, "w") as f: yaml.safe_dump(cfg, f, sort_keys=False)

def fetch_img(url):
    r = requests.get(url, timeout=5)
    arr = np.frombuffer(r.content, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/sensors")
def sensors():
    cfg = load_cfg()
    return jsonify([{"id":s["id"],"snapshot_url":s["snapshot_url"],"roi_display":s.get("roi_display",[0,0,0,0])} for s in cfg["sensors"]])

@app.get("/shot")
def shot():
    cfg = load_cfg(); sid = int(request.args.get("sid","0"))
    s = cfg["sensors"][sid]; img = fetch_img(s["snapshot_url"])
    _, buf = cv2.imencode(".jpg", img)
    return send_file(io.BytesIO(buf.tobytes()), mimetype="image/jpeg")

@app.post("/save_roi")
def save_roi():
    data = request.get_json()
    cfg = load_cfg()
    sid = int(data["sid"]); roi = [int(x) for x in data["roi"]]
    cfg["sensors"][sid]["roi_display"] = roi
    save_cfg(cfg)
    return jsonify({"ok":True, "roi":roi})

def _load_state():
    if not STATE_PATH.exists():
        print("STATE NOT FOUND AT PATH: " + STATE_PATH)
        return {}
    with STATE_PATH.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def _save_state_atomic(data: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)

# --- GET: return flat values for one sensor
@app.get("/api/state/<sensor_id>")
def api_state_get_sensor(sensor_id):
    st = _load_state()
    t1 = st.get(f"{sensor_id}.t1")
    t2 = st.get(f"{sensor_id}.t2")
    total = st.get(f"{sensor_id}.total")
    return jsonify({
        "sensor_id": sensor_id,
        "last": {
            f"{sensor_id}.t1": t1,
            f"{sensor_id}.t2": t2,
            f"{sensor_id}.total": total
        }
    })

# --- POST: update t1 and/or t2 (optional), then total = t1 + t2
@app.post("/api/state/tariffs")
def api_state_set_tariffs():
    """
    Body JSON:
      { "sensor_id": "electricity_main", "t1": 13485, "t2": 999 }
    You may send only t1, only t2, or both. total is always recomputed (t1+t2).
    """
    data = request.get_json(force=True) or {}
    sid = data.get("sensor_id")
    if not sid:
        return jsonify({"ok": False, "error": "sensor_id missing"}), 400

    st = _load_state()

    def _num(x):
        if x is None: return None
        if isinstance(x, str): x = x.replace(",", ".")
        return float(x)

    # current values (fallback 0.0 if not present)
    cur_t1 = float(st.get(f"{sid}.t1", 0.0))
    cur_t2 = float(st.get(f"{sid}.t2", 0.0))

    # overrides from payload (optional)
    new_t1 = _num(data.get("t1"))
    new_t2 = _num(data.get("t2"))

    # apply only provided fields
    t1 = cur_t1 if new_t1 is None else new_t1
    t2 = cur_t2 if new_t2 is None else new_t2

    # recompute total
    total = float(t1) + float(t2)

    # write back (flat schema only)
    st[f"{sid}.t1"] = float(t1)
    st[f"{sid}.t2"] = float(t2)
    st[f"{sid}.total"] = float(total)

    _save_state_atomic(st)
    return jsonify({
        "ok": True,
        "saved": {
            f"{sid}.t1": st[f"{sid}.t1"],
            f"{sid}.t2": st[f"{sid}.t2"],
            f"{sid}.total": st[f"{sid}.total"],
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088)
