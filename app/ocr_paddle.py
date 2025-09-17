# app/ocr_paddle.py
import os
import logging
import cv2
import numpy as np
from paddleocr import PaddleOCR
from app.ocr_pre import preprocess_for_ocr

# stíšiť PaddleOCR logy
os.environ.setdefault("PPocr_DEBUG", "0")
logging.getLogger("ppocr").setLevel(logging.WARNING)

_reader = None

def get_reader():
    """
    Lazy-inicializovaný PaddleOCR reader (CPU).
    """
    global _reader
    if _reader is None:
        # en + PP-OCRv4, cls vypnute (nepotrebujeme)
        _reader = PaddleOCR(use_angle_cls=False, lang="en")
    return _reader


def _ensure_bgr(img):
    """
    PaddleOCR čaká 3-kanálový obraz. Ak máme 1-kanál (gray/binary),
    prevedieme na BGR.
    """
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


def _prepare_simple_gray(bgr, upscale=2):
    """
    Jednoduchá príprava ROI: převod do gray + upscaling.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if upscale and upscale > 1:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return gray


def _run_paddle(img3):
    """
    Spustí PaddleOCR a vráti (digits, conf).
    - digits = len textu len z číslic
    - conf   = priemer confidence zo segmentov, ktoré prispeli aspoň jednou číslicou
    """
    res = get_reader().ocr(img3, cls=False)

    if not res or not res[0]:
        return "", 0.0

    parts = []
    confs = []

    # res[0] = list of [box, (text, score)]
    for _box, (txt, score) in res[0]:
        if not txt:
            continue
        only_digits = "".join(ch for ch in txt if ch.isdigit())
        if only_digits:
            parts.append(only_digits)
            confs.append(float(score))

    if not parts:
        # nič číselného – stále vráť 0 conf
        return "", 0.0

    joined = "".join(parts)
    mean_conf = float(np.mean(confs)) if confs else 0.0
    return joined, mean_conf


def ocr_digits(bgr, upscale=2, already_processed=False):
    """
    Prečíta čísla z BGR obrazka (ROI).
    - najprv jednoduchá cesta (gray + upscaling)
    - ak zlyhá alebo nič neprehliadol, skúsime robustný preprocess_for_ocr
    - ak already_processed=True, bgr sa berie ako už predspracovaný (1ch alebo 3ch)

    Returns: (digits_str, confidence_float)
    """
    # 1) buď už spracované, alebo jednoduchý gray pipeline
    if already_processed:
        first = bgr
    else:
        first = _prepare_simple_gray(bgr, upscale=upscale)

    first3 = _ensure_bgr(first)
    digits, conf = _run_paddle(first3)

    # 2) fallback – ak nič, skús robustné predspracovanie
    if not digits:
        proc = preprocess_for_ocr(bgr)  # vracia binárnu 1ch, zväčšenú
        proc3 = _ensure_bgr(proc)
        digits2, conf2 = _run_paddle(proc3)

        # vyber lepší výsledok (viac znakov / vyšší conf)
        if len(digits2) > len(digits) or conf2 > conf:
            digits, conf = digits2, conf2

    return digits, float(conf)
