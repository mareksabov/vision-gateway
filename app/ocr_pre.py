# app/ocr_pre.py
import cv2
import numpy as np

def preprocess_for_ocr(bgr):
    # 1) na LCD obvykle stačí G kanál (zelený je najjasnejší)
    g = bgr[:,:,1]

    # 2) jemné odšumenie bez rozmazania hrán
    g = cv2.bilateralFilter(g, 5, 30, 30)

    # 3) gamma na zosvetlenie tieňov
    gamma = 0.7  # <1 zosvetlí
    lut = np.array([(i/255.0)**gamma*255 for i in range(256)]).astype("uint8")
    g = cv2.LUT(g, lut)

    # 4) lokálny kontrast (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    g = clahe.apply(g)

    # 5) adaptívny threshold (invert → čísla biele)
    th = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV, 31, 10
    )

    # 6) máličko zavrieť drobné diery
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((2,2), np.uint8), iterations=1)

    # 7) upscaling (OCR má rad veľké, ostré znaky)
    th = cv2.resize(th, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return th
