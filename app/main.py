# app/main.py
import os, time, logging
from app.utils import fetch_bgr, crop
from app.ocr_paddle import ocr_digits
from app.state import State
# from app.mqtt_pub import Mqtt
from app.mqtt_pub_dev import Mqtt
from app.config import load_config

DEBUG    = os.getenv("APP_DEBUG", "0") == "1"
CFG_PATH = "/app/config/sensors.yaml"

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
LOG = logging.getLogger("reader")

def digits_to_int(d: str) -> int:
    d = (d or "").lstrip("0")
    return int(d) if d else 0

def nearest_bucket(val: int, t1: int, t2: int) -> str:
    return "t1" if abs(val - t1) <= abs(val - t2) else "t2"

def poll_from(cfg) -> float:
    """
    Env POLL_INTERVAL_S má prednosť. Ak nie je, berie sa z configu
    global.poll_interval_s. Fallback 5.
    """
    g = cfg.get("global", {})
    cfg_poll = g.get("poll_interval_s", 5)
    return float(os.getenv("POLL_INTERVAL_S", str(cfg_poll)))

def process_all(mqtt: Mqtt, cfg, st: State):
    g = cfg.get("global", {})
    conf_min = float(g.get("conf_threshold", 0.60))
    upscale  = int(g.get("roi_upscale", 2))
    max_step = int(g.get("max_step_kwh", 50))  # limit skoku

    for s in cfg["sensors"]:
        sid  = s["id"]
        base = s["mqtt_topic_base"]
        url  = s["snapshot_url"]

        try:
            LOG.debug("[%s] fetching %s", sid, url)
            img = fetch_bgr(url)

            if "roi_display" not in s:
                LOG.warning("[%s] missing roi_display", sid)
                continue

            x, y, w, h = map(int, s["roi_display"])
            roi = crop(img, (x, y, w, h))

            digits, conf = ocr_digits(roi, upscale=upscale)
            LOG.info("[%s] OCR digits='%s' conf=%.2f", sid, digits, conf)

            mqtt.pub(base, "ocr_raw", digits or "")
            mqtt.pub(base, "ocr_conf", f"{conf:.2f}")

            if not digits or conf < conf_min:
                LOG.info("[%s] conf %.2f < %.2f → skip update", sid, conf, conf_min)
                continue

            v = digits_to_int(digits)

            # načítaj stav so správnymi defaultmi
            last_t1 = st.get(f"{sid}.t1", int(s.get("initial_t1", 0)))
            last_t2 = st.get(f"{sid}.t2", int(s.get("initial_t2", 0)))
            LOG.debug("[%s] state before: t1=%s t2=%s", sid, last_t1, last_t2)

            bucket = nearest_bucket(v, last_t1, last_t2)

            def accept_update(last_val: int, new_val: int) -> bool:
                if new_val < last_val:
                    return False
                if (new_val - last_val) > max_step:
                    LOG.warning("[%s] %s jump %s→%s > %s kWh → ignore",
                                sid, bucket, last_val, new_val, max_step)
                    return False
                return True

            if bucket == "t1":
                if accept_update(last_t1, v):
                    st[f"{sid}.t1"] = v
                    mqtt.pub(base, "t1", str(v), retain=True)
                    last_t1 = v
                    LOG.info("[%s] -> t1 := %s", sid, v)
            else:
                if accept_update(last_t2, v):
                    st[f"{sid}.t2"] = v
                    mqtt.pub(base, "t2", str(v), retain=True)
                    last_t2 = v
                    LOG.info("[%s] -> t2 := %s", sid, v)

            total = last_t1 + last_t2
            st[f"{sid}.total"] = total
            mqtt.pub(base, "total", str(total), retain=True)
            LOG.debug("[%s] state after:  t1=%s t2=%s total=%s", sid, last_t1, last_t2, total)

        except Exception as e:
            LOG.warning("[%s] iteration error: %s: %s", sid, e.__class__.__name__, e)

def main():
    cfg = load_config(CFG_PATH)
    cfg_mtime = os.path.getmtime(CFG_PATH)
    st   = State("/app/state/state.json")
    mqtt = Mqtt()

    poll = poll_from(cfg)
    LOG.info("vision-reader started; poll=%.2fs", poll)

    while True:
        t0 = time.time()
        try:
            # --- HOT RELOAD ---
            try:
                m = os.path.getmtime(CFG_PATH)
                if m != cfg_mtime:
                    cfg = load_config(CFG_PATH)
                    cfg_mtime = m
                    poll = poll_from(cfg)  # prepočítaj po reloade
                    LOG.info("config reloaded; poll=%.2fs", poll)
            except FileNotFoundError:
                LOG.warning("config file missing: %s", CFG_PATH)
            # -------------------

            process_all(mqtt, cfg, st)
            mqtt.loop(0.1)
        except Exception as e:
            LOG.error("top-level iteration error: %s: %s", e.__class__.__name__, e)
        dt = time.time() - t0
        if DEBUG:
            LOG.debug("loop done in %.3fs", dt)
        time.sleep(max(0.0, poll - dt))

if __name__ == "__main__":
    main()
