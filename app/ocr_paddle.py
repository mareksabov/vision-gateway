# app/ocr_paddle.py
import os, logging, cv2
from paddleocr import PaddleOCR

# stíšiť Paddle
os.environ.setdefault("PPocr_DEBUG", "0")
logging.getLogger("ppocr").setLevel(logging.WARNING)

_reader = None

def get_reader():
    global _reader
    if _reader is None:
        _reader = PaddleOCR(use_angle_cls=False, lang='en')  # CPU
    return _reader

def prepare_roi(bgr, upscale=2):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if upscale and upscale > 1:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return gray

def ocr_digits(bgr, upscale=2):
    import numpy as np
    roi = prepare_roi(bgr, upscale=upscale)
    roi3 = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
    res = get_reader().ocr(roi3, cls=False)

    best_text, best_conf = "", 0.0
    if res and res[0]:
        joined = "".join([x[1][0] for x in res[0]])
        confs = [float(x[1][1]) for x in res[0]]
        best_text, best_conf = joined, float(np.mean(confs))

    digits = "".join(ch for ch in (best_text or "") if ch.isdigit())
    return digits, best_conf
