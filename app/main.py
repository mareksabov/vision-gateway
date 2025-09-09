# app/main.py
import os, time, logging
from app.utils import fetch_bgr, crop
from app.ocr_paddle import ocr_digits
from app.state import State
from app.mqtt_pub import Mqtt

POLL = float(os.getenv("POLL_INTERVAL_S", "5"))
DEBUG = os.getenv("APP_DEBUG", "0") == "1"

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

def process_all(mqtt: Mqtt, cfg, st: State):
    for s in cfg["sensors"]:
        sid = s["id"]
        base = s["mqtt_topic_base"]
        url  = s["snapshot_url"]

        try:
            img = fetch_bgr(url)                          # načítaj snímku
            if DEBUG: logging.debug(f"[{sid}] got frame")

            # --- OCR čísla ---------------------------------------------------
            if "roi_display" in s:
                x, y, w, h = map(int, s["roi_display"])
                roi = crop(img, (x, y, w, h))

                txt, conf = ocr_digits(roi, upscale=int(s.get("roi_upscale", 2)))
                if DEBUG: logging.debug(f"[{sid}] OCR '{txt}' conf={conf:.2f}")

                mqtt.pub(base, "ocr_raw", txt or "(null)")
                mqtt.pub(base, "ocr_conf", f"{conf:.3f}")

                # heuristika: strip leading zeros → int
                if txt:
                    stripped = txt.lstrip("0")
                    if stripped == "": stripped = "0"
                    try:
                        v = int(stripped)
                        # vyber bližší z T1/T2 a aktualizuj (tu je len príklad)
                        last_t1 = st.get(f"{sid}.t1", int(s.get("t1_init", 0)))
                        last_t2 = st.get(f"{sid}.t2", int(s.get("t2_init", 0)))
                        if abs(v - last_t1) <= abs(v - last_t2):
                            st[f"{sid}.t1"] = v
                            mqtt.pub(base, "t1", str(v))
                        else:
                            st[f"{sid}.t2"] = v
                            mqtt.pub(base, "t2", str(v))
                        st[f"{sid}.total"] = v
                        mqtt.pub(base, "total", str(v))
                    except ValueError:
                        pass

        except Exception as e:
            logging.warning(f"[{sid}] iteration error: {e.__class__.__name__}: {e}")

def main():
    from app.config import load_config
    cfg = load_config("/app/config/sensors.yaml")
    st  = State("/app/state/state.json")
    mqtt = Mqtt()  # pripojí sa v __init__

    logging.info("vision-reader started; poll=%.2fs", POLL)
    # nekonečná slučka s pevnou periódou
    while True:
        t0 = time.time()
        try:
            process_all(mqtt, cfg, st)
        except Exception as e:
            logging.error("top-level iteration error: %s: %s", e.__class__.__name__, e)
        dt = time.time() - t0
        if DEBUG: logging.debug("loop done in %.3fs", dt)
        time.sleep(max(0.0, POLL - dt))

if __name__ == "__main__":
    main()
