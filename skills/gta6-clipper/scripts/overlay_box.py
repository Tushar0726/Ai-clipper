"""Find the streamer's facecam overlay box (anchored at the top-left corner of the frame) from its
persistent straight edges: a strong vertical line (right edge) and horizontal line (bottom edge)
that stay in place while the gameplay moves. Returns (L, T, W, H) in source pixels, or None."""
import cv2, numpy as np


def overlay_box(video, n=24):
    cap = cv2.VideoCapture(str(video))
    nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 600
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    gx = gy = None; k = 0
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(nfr * (i + 0.5) / n))
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        sx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)); sy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
        gx = sx if gx is None else np.minimum(gx, sx) if False else (gx + sx)
        gy = sy if gy is None else (gy + sy)
        k += 1
    cap.release()
    if not k:
        return None
    gx /= k; gy /= k
    s = W / 1920.0
    # right edge: column with the strongest, most persistent vertical edge across the top rows
    x0, x1 = int(300 * s), int(760 * s)
    col = gx[int(30 * s):int(260 * s), x0:x1].mean(axis=0)
    R = x0 + int(np.argmax(col))
    # bottom edge: row with the strongest horizontal edge across the box width
    y0, y1 = int(220 * s), int(520 * s)
    row = gy[y0:y1, int(30 * s):max(int(60 * s), R - int(30 * s))].mean(axis=1)
    B = y0 + int(np.argmax(row))
    cs = col.max() / (np.median(col) + 1e-3); rs = row.max() / (np.median(row) + 1e-3)
    if cs < 2.5 or rs < 2.5:
        return None
    R -= R % 2; B -= B % 2
    return (0, 0, R, B)
