"""Normalise every master: near-white -> pure white; add a white margin on any
edge the content touches; grow the canvas to 16:10. Never crops or scales.
Deterministic; idempotent."""
import os, sys
import numpy as np
from PIL import Image

MARGIN = 28
ASPECT = 16 / 10

def whiten(a):
    mn = a.min(2); mx = a.max(2)
    m = (mn >= 236) & ((mx - mn) <= 12)
    a[m] = 255
    return a

def content_bbox(a, thr=250):
    nz = np.argwhere(a.min(2) < thr)
    if len(nz) == 0:
        return 0, 0, a.shape[1], a.shape[0]
    y0, x0 = nz.min(0); y1, x1 = nz.max(0) + 1
    return x0, y0, x1, y1

def normalise(src, dst):
    im = Image.open(src).convert('RGB')
    a = whiten(np.array(im).astype(np.int16)).astype(np.uint8)
    # pad only (never crop, never scale): ensure a white margin where content
    # touches the edge, then grow the canvas to 16:10
    x0, y0, x1, y1 = content_bbox(a)
    h, w = a.shape[:2]
    pad_l = MARGIN if x0 == 0 else 0; pad_r = MARGIN if x1 == w else 0
    pad_t = MARGIN if y0 == 0 else 0; pad_b = MARGIN if y1 == h else 0
    crop = np.pad(a, ((pad_t, pad_b), (pad_l, pad_r), (0, 0)), constant_values=255)
    h, w = crop.shape[:2]
    W, H = w, h
    if W / H < ASPECT:
        W = int(round(H * ASPECT))
    else:
        H = int(round(W / ASPECT))
    canvas = np.full((H, W, 3), 255, np.uint8)
    ox = (W - w) // 2; oy = (H - h) // 2
    canvas[oy:oy + h, ox:ox + w] = crop
    Image.fromarray(canvas).save(dst)
    return (w, h), (W, H)

if __name__ == '__main__':
    src_dir, dst_dir = sys.argv[1], sys.argv[2]
    os.makedirs(dst_dir, exist_ok=True)
    for f in sorted(os.listdir(src_dir)):
        if f.endswith('.png'):
            c, o = normalise(f'{src_dir}/{f}', f'{dst_dir}/{f}')
            print(f[:60], c, '->', o)
