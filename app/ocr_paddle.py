# app/ocr_paddle.py
import os, logging, re, cv2, numpy as np
from paddleocr import PaddleOCR

# tichšie logy
os.environ.setdefault("PPocr_DEBUG", "0")
logging.getLogger("ppocr").setLevel(logging.WARNING)

DEBUG = os.getenv("APP_DEBUG", "0") == "1"
DBG_DIR = "/app/debug"

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
    # gamma korekcia pre stmavené zábery
    invG = 1.0 / max(g, 1e-6)
    table = (np.linspace(0, 1, 256) ** invG * 255).astype("uint8")
    return cv2.LUT(img, table)

def _enhance_color(bgr: np.ndarray) -> np.ndarray:
    # vezmi V z HSV (jas), uprav kontrast/gammu a späť na BGR
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
        cv2.THRESH_BINARY_INV, 31, 7
    )
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN,  k, iterations=1)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)
    return th

def _pick_digits(text: str) -> str:
    # vyber najlepší blok 5–8 číslic; ak dlhšie, vezmi pravých 6
    text = text or ""
    blocks = re.findall(r"\d{5,8}", text)
    if not blocks:
        only = re.sub(r"\D", "", text)
        if not only: return ""
        cand = only
    else:
        m = max(len(b) for b in blocks)
        cand = [b for b in blocks if len(b) == m][-1]
    if len(cand) > 7:
        cand = cand[-7:]
    return cand

def _ocr_image(bgr_img):
    res = get_reader().ocr(bgr_img, cls=False)
    best_text, conf = "", 0.0
    if res and res[0]:
        parts = [x[1][0] for x in res[0]]
        confs = [float(x[1][1]) for x in res[0] if isinstance(x[1][1], (float,int))]
        best_text = "".join(parts)
        conf = float(np.mean(confs)) if confs else 0.0
    return best_text, conf

def ocr_digits(bgr: np.ndarray, upscale: int = 2):
    """
    Skúsi viac variantov (farba, šedá, binár) a vráti (digits, conf)
    s najvyšším skóre. V debug režime ukladá medzikroky do /app/debug.
    """
    if DEBUG: _ensure_dir(DBG_DIR)

    # V1: vylepšená farba (pre detektor je často najlepšia)
    col = _enhance_color(bgr.copy())
    if upscale and upscale > 1:
        col = cv2.resize(col, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    if DEBUG: cv2.imwrite(f"{DBG_DIR}/v1_color.jpg", col)

    # V2: šedá
    g = _prep_gray(bgr, upscale=upscale)
    g_bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    if DEBUG: cv2.imwrite(f"{DBG_DIR}/v2_gray.png", g)

    # V3: binár
    th = _binarize(g)
    th_bgr = cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)
    if DEBUG: cv2.imwrite(f"{DBG_DIR}/v3_bin.png", th)

    candidates = []

    for name, img in [("color", col), ("gray", g_bgr), ("bin", th_bgr)]:
        txt, c = _ocr_image(img)
        digits = _pick_digits(txt)
        # penalizácia prázdneho výsledku
        score = c if digits else 0.0
        candidates.append((digits, score, name))
        if DEBUG:
            with open(f"{DBG_DIR}/log.txt", "a") as f:
                f.write(f"{name}: txt='{txt}' → digits='{digits}', conf={c:.2f}\n")

    # vyber naj s conf
    best = max(candidates, key=lambda x: x[1]) if candidates else ("", 0.0, "none")
    return best[0], float(best[1])
