import requests, numpy as np, cv2

def fetch_bgr(url, timeout=6):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    arr = np.frombuffer(r.content, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

def crop(img, xywh):
    x,y,w,h = map(int, xywh)
    return img[y:y+h, x:x+w]
