import io, yaml, time
from flask import Flask, request, jsonify, send_file, render_template
import cv2, numpy as np, requests

app = Flask(__name__, static_folder="static", template_folder="templates")
CFG_PATH = "config/sensors.yaml"

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088)
