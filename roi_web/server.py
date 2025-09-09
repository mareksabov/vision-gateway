import io, yaml, time
from flask import Flask, request, jsonify, send_file
import cv2, numpy as np, requests

app = Flask(__name__)
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
    return """
<!doctype html><html><head><meta charset="utf-8"><title>ROI Config</title>
<style>body{font-family:sans-serif} #c{border:1px solid #333;max-width:100%}</style></head>
<body>
<h2>ROI Configurator</h2>
<label>Sensor: <select id="sel"></select></label>
<button onclick="loadImg()">Load</button>
<canvas id="c"></canvas><br>
<button onclick="save()">Save ROI</button>
<script>
let sensors=[], sid=null, roi=null, img=null, c=document.getElementById('c'), ctx=c.getContext('2d');
fetch('/sensors').then(r=>r.json()).then(d=>{sensors=d; let s=document.getElementById('sel');
sensors.forEach((x,i)=>{let o=document.createElement('option');o.value=i;o.text=x.id;s.add(o);}); sid=0;});
function loadImg(){
  sid = +document.getElementById('sel').value;
  fetch('/shot?sid='+sid+'&_='+(Date.now())).then(r=>r.blob()).then(b=>{
    let u=URL.createObjectURL(b); img=new Image(); img.onload=()=>{c.width=img.width;c.height=img.height;ctx.drawImage(img,0,0);};
    img.src=u;
  });
}
let dragging=false, sx=0, sy=0;
c.onmousedown=e=>{dragging=true; sx=e.offsetX; sy=e.offsetY;};
c.onmousemove=e=>{ if(!dragging||!img)return; let x=Math.min(sx,e.offsetX), y=Math.min(sy,e.offsetY);
  let w=Math.abs(e.offsetX-sx), h=Math.abs(e.offsetY-sy); ctx.drawImage(img,0,0); ctx.strokeStyle='red';
  ctx.lineWidth=2; ctx.strokeRect(x,y,w,h); roi=[x,y,w,h]; };
c.onmouseup=()=>dragging=false;
function save(){
  if(!roi){alert('Draw ROI first.');return;}
  fetch('/save_roi', {method:'POST', headers:{'Content-Type':'application/json'},
   body:JSON.stringify({sid:sid, roi:roi})}).then(r=>r.json()).then(j=>alert('Saved: '+JSON.stringify(j)));
}
</script></body></html>"""

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
