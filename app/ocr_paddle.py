# app/ocr_paddle.py
import os, logging, re, cv2, numpy as np
from paddleocr import PaddleOCR
from app.ocr_pre import preprocess_for_ocr  # V4

# tichšie logy
os.environ.setdefault("PPocr_DEBUG", "0")
logging.getLogger("ppocr").setLevel(logging.WARNING)

DEBUG = os.getenv("APP_DEBUG", "0").strip() == "1"
DBG_DIR = "/app/debug"
TARGET_LEN = int(os.getenv("OCR_TARGET_LEN", "7"))

LOG = logging.getLogger("ocr")

_reader = None
def get_reader():
    global _reader
    if _reader is None:
        _reader = PaddleOCR(use_angle_cls=False, lang="en")  # CPU
    return _reader

def _ensure_dir(p):
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass

def _gamma(img, g=1.3):
    invG = 1.0 / max(g, 1e-6)
    table = (np.linspace(0, 1, 256) ** invG * 255).astype("uint8")
    return cv2.LUT(img, table)

def _enhance_color(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    v = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(v)
    v = _gamma(v, 1.6)
    hsv = cv2.merge([h, s, v])
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

def _prep_gray(bgr: np.ndarray, upscale: int) -> np.ndarray:
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(g)
    g = cv2.GaussianBlur(g, (3,3), 0)
    if upscale and upscale > 1:
        g = cv2.resize(g, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return g

def _binarize(g: np.ndarray) -> np.ndarray:
    th = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 51, 5
    )
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN,  k, iterations=1)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)
    return th

def _normalize_len(d: str, target_len: int = TARGET_LEN) -> str:
    d = re.sub(r"\D", "", d or "")
    if not d:
        return ""
    if len(d) > target_len:
        d = d[:target_len]       # orež zľava (častý extra znak na konci)
    elif len(d) < target_len:
        d = d.zfill(target_len)  # doplň nuly zľava
    return d

def _pick_digits(text: str, target_len: int = TARGET_LEN) -> str:
    text = text or ""
    only = re.sub(r"\D", "", text)
    if not only:
        return ""
    blocks = re.findall(r"\d{5,}", only)
    cand = max(blocks, key=len) if blocks else only
    return _normalize_len(cand, target_len)

def _save(path: str, img) -> None:
    if not DEBUG: return
    ok = cv2.imwrite(path, img)
    if not ok:
        LOG.warning("debug save failed: %s", path)

def _ocr_sorted(bgr_img):
    """
    OCR s pevnou čítacou stratégiou:
    - zoradí boxy zľava doprava podľa x-centra
    - rozseká viacznakové tokeny ('00') na jednotlivé znaky
    - vráti text len z číslic + priemernú konf.
    """
    res = get_reader().ocr(bgr_img, cls=False)
    if not res or not res[0]:
        return "", 0.0

    items = []
    confs = []
    for box, (txt, conf) in res[0]:
        # x-poradie podľa stredu bounding boxu
        xs = [p[0] for p in box]
        x_center = float(sum(xs)) / len(xs)
        # len číslice; ak je token dlhší, rozsekáme ho, no zachováme poradie
        token = re.sub(r"\D", "", txt or "")
        if not token:
            continue
        # ulož po znakoch s jemným offsetom, aby sa zachovalo poradie v rámci tokenu
        for i, ch in enumerate(token):
            items.append((x_center + i*0.001, ch))  # 0.001 stačí na stabilné sortovanie
            confs.append(float(conf) if isinstance(conf, (float, int)) else 0.0)

    if not items:
        return "", 0.0

    items.sort(key=lambda t: t[0])
    text = "".join(ch for _, ch in items)
    conf = float(np.mean(confs)) if confs else 0.0
    return text, conf

def _score(digits: str, conf: float) -> float:
    if not digits:
        return 0.0
    bonus = 0.05 if len(digits) == TARGET_LEN else -0.05
    return max(0.0, conf + bonus)

def ocr_digits(bgr: np.ndarray, upscale: int = 2):
    """
    V1 farba, V2 šedá, V3 binár, V4 LCD-preprocess; všetko cez _ocr_sorted.
    Vyberie kandidáta s najvyšším skóre.
    """
    if DEBUG: _ensure_dir(DBG_DIR)
    candidates = []

    # V1: farba
    col = _enhance_color(bgr.copy())
    if upscale and upscale > 1:
        col = cv2.resize(col, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    _save(f"{DBG_DIR}/v1_color.jpg", col)
    txt, c = _ocr_sorted(col)
    d = _pick_digits(txt)
    candidates.append((d, _score(d, c), "color", c, txt))

    # V2: šedá
    g = _prep_gray(bgr, upscale=upscale)
    _save(f"{DBG_DIR}/v2_gray.png", g)
    g_bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    txt, c = _ocr_sorted(g_bgr)
    d = _pick_digits(txt)
    candidates.append((d, _score(d, c), "gray", c, txt))

    # V3: binár
    th = _binarize(g)
    _save(f"{DBG_DIR}/v3_bin.png", th)
    th_bgr = cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)
    txt, c = _ocr_sorted(th_bgr)
    d = _pick_digits(txt)
    candidates.append((d, _score(d, c), "bin", c, txt))

    # V4: špeciálna predpríprava (ocr_pre.py)
    prep = preprocess_for_ocr(bgr)
    _save(f"{DBG_DIR}/v4_pre.png", prep)
    prep_bgr = cv2.cvtColor(prep, cv2.COLOR_GRAY2BGR)
    txt, c = _ocr_sorted(prep_bgr)
    d = _pick_digits(txt)
    candidates.append((d, _score(d, c), "pre", c, txt))

    if DEBUG:
        with open(f"{DBG_DIR}/log.txt", "a") as f:
            for d, s, name, c_raw, txt in candidates:
                f.write(f"{name}: txt='{txt}' → digits='{d}', conf={c_raw:.2f}, score={s:.3f}\n")

    if not candidates:
        return "", 0.0

    best_digits, best_score, best_name, best_conf, _ = max(candidates, key=lambda x: x[1])
    return best_digits, float(best_conf)
