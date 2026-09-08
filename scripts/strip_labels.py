"""Strip baked labels + leader lines from a Gemini figure on a white ground.

Discriminator: Gemini's labels and leader lines are pure neutral grey
(chroma ~0 after a light blur); everything it draws carries chroma, even
pale fills. Pass 1 keeps everything within `halo` px of a coloured region
and whitens the rest. Pass 2 finds leader stubs in the halo ring, follows
each one inward along its own direction, and inpaints the neutral-dark
pixels on that path (the part of the leader drawn over the fill).
"""
import sys, cv2, numpy as np

src, dst = sys.argv[1], sys.argv[2]
halo = int(sys.argv[3]) if len(sys.argv) > 3 else 5
chroma_thr = float(sys.argv[4]) if len(sys.argv) > 4 else 4.0
REACH = 90   # px a leader may run inside the drawing

img = cv2.imread(src)
f = img.astype(np.float32)
b = cv2.GaussianBlur(f, (0, 0), 1.2)
chroma = b.max(2) - b.min(2)
val = b.min(2)
raw_chroma = f.max(2) - f.min(2)
raw_val = f.min(2)
bg = cv2.medianBlur(raw_val.astype(np.uint8), 11).astype(np.float32)

colour = ((chroma > chroma_thr) & (val < 245)).astype(np.uint8)
colour = cv2.morphologyEx(colour, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
n, lab, stats, _ = cv2.connectedComponentsWithStats(colour, 8)
keep = np.zeros_like(colour)
for i in range(1, n):
    if stats[i, cv2.CC_STAT_AREA] >= 40:
        keep[lab == i] = 1

def disk(r):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))

core = cv2.dilate(keep, disk(halo))
tight = cv2.dilate(keep, disk(1))

out = img.copy()
out[core == 0] = (255, 255, 255)

# pass 2: leader lines = neutral components outside the drawing that touch
# the halo; take direction from the whole line, walk inward from the end
# nearest the drawing, inpaint dark pixels on that path.
neutral = ((chroma < 2.5) & (val < 235) & (tight == 0)).astype(np.uint8)
inpaint = np.zeros(neutral.shape, np.uint8)
ns, sl, sst, cen = cv2.connectedComponentsWithStats(neutral, 8)
H, W = neutral.shape
touch = cv2.dilate(tight, disk(halo + 1))
dist = cv2.distanceTransform((tight == 0).astype(np.uint8), cv2.DIST_L2, 3)
for i in range(1, ns):
    ys, xs = np.nonzero(sl == i)
    if len(xs) < 6 or not touch[ys, xs].any():
        continue
    near = dist[ys, xs] < 25          # only the part of the line near the drawing
    if near.sum() < 6:
        continue
    pts = np.stack([xs[near], ys[near]], 1).astype(np.float32)
    mean = pts.mean(0)
    _, sv, vt = np.linalg.svd(pts - mean, full_matrices=False)
    if sv[0] < 3 * max(sv[1], 1e-3):   # not line-like (a glyph) -> skip
        continue
    d = vt[0]
    proj = (pts - mean) @ d
    ends = [mean + d * proj.min(), mean + d * proj.max()]
    # inward end = the one inside touch
    for end, sign in ((ends[0], -1), (ends[1], 1)):
        xi, yi = int(round(end[0])), int(round(end[1]))
        if not (0 <= xi < W and 0 <= yi < H) or not touch[yi, xi]:
            continue
        for t in range(0, REACH):
            x, y = end + sign * d * t
            xi, yi = int(round(x)), int(round(y))
            if not (0 <= xi < W and 0 <= yi < H):
                break
            y0, y1 = max(0, yi - 2), min(H, yi + 3)
            x0, x1 = max(0, xi - 2), min(W, xi + 3)
            patch = raw_val[y0:y1, x0:x1] < bg[y0:y1, x0:x1] - 18
            inpaint[y0:y1, x0:x1][patch] = 1
# stubs left in the ring (any neutral dark pixel) also go
ring = (core == 1) & (cv2.dilate(keep, disk(4)) == 0)
inpaint[ring & (chroma < 2.0) & (val < 235)] = 1

inpaint = cv2.dilate(inpaint, disk(1))
out = cv2.inpaint(out, inpaint, 3, cv2.INPAINT_TELEA)
out[core == 0] = (255, 255, 255)

cv2.imwrite(dst, out)
print(dst, "coloured px:", int(keep.sum()), "inpainted px:", int(inpaint.sum()))
