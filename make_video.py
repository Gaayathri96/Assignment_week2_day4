"""Generate a 60-second animated video from tamil_prompt.json.

Every frame is drawn procedurally with Pillow (no stock footage), a simple
tanpura-drone + percussion soundtrack is synthesised with numpy, and the two
are muxed into an MP4 with ffmpeg (from the imageio-ffmpeg package).

    pip install pillow numpy imageio-ffmpeg
    python make_video.py            # writes tamil_culture.mp4
"""
import json
import math
import random
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 24
HERE = Path(__file__).parent
PROMPT = json.loads((HERE / "tamil_prompt.json").read_text(encoding="utf-8"))
SUBJ = PROMPT["1_SUBJECT"]

FONT_DIR = Path("C:/Windows/Fonts")


def font(name, size):
    for cand in (FONT_DIR / name, Path(name)):
        try:
            return ImageFont.truetype(str(cand), size)
        except OSError:
            pass
    return ImageFont.load_default(size)


F_TITLE = font("georgiab.ttf", 96)
F_SUB = font("georgiai.ttf", 38)
F_HEAD = font("georgiab.ttf", 40)
F_ITEM = font("georgia.ttf", 30)
F_SMALL = font("georgia.ttf", 22)

GOLD = (232, 180, 60)
KUMKUM = (196, 30, 58)
TURMERIC = (240, 190, 30)
MAROON = (110, 10, 35)
PEACOCK = (0, 110, 140)
LEAF = (60, 150, 50)
TERRACOTTA = (204, 102, 51)
BRONZE = (140, 90, 40)
JASMINE = (250, 248, 240)


# ----------------------------------------------------------------- helpers
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def gradient(top, bottom, w=W, h=H):
    a = np.linspace(0, 1, h)[:, None, None]
    col = np.array(top)[None, None, :] * (1 - a) + np.array(bottom)[None, None, :] * a
    return Image.fromarray(np.broadcast_to(col, (h, w, 3)).astype(np.uint8))


def glow(img, x, y, r, color, strength=0.6, rings=8):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for i in range(rings, 0, -1):
        rr = r * i / rings
        a = int(255 * strength * (1 - i / (rings + 1)) / rings * 2)
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=color + (a,))
    img.alpha_composite(ov) if img.mode == "RGBA" else img.paste(
        Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB"))


def flame(d, x, y, s, t, phase=0.0):
    f = 1 + 0.18 * math.sin(t * 17 + phase) + 0.1 * math.sin(t * 29 + phase * 2)
    h = 26 * s * f
    sway = 3 * s * math.sin(t * 11 + phase)
    d.polygon([(x - 7 * s, y), (x + sway, y - h), (x + 7 * s, y)], fill=(255, 140, 20))
    d.polygon([(x - 3.5 * s, y), (x + sway * 0.6, y - h * 0.6), (x + 3.5 * s, y)], fill=(255, 235, 140))


def caption(img, t, dur, heading, items, period=1.6):
    """Lower-third with a heading and items from the prompt cycling through."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    fade = ease(t / 0.6) * ease((dur - t) / 0.4)
    d.rectangle([0, H - 130, W, H], fill=(15, 5, 10, int(170 * fade)))
    d.rectangle([0, H - 130, W, H - 126], fill=GOLD + (int(230 * fade),))
    d.text((48, H - 116), heading, font=F_HEAD, fill=GOLD + (int(255 * fade),))
    k = int(t / period) % len(items)
    ph = (t % period) / period
    a = ease(ph / 0.15) * ease((1 - ph) / 0.15) * fade
    d.text((50 + 12 * (1 - ease(ph / 0.15)), H - 62), "\u2022  " + items[k],
           font=F_ITEM, fill=JASMINE + (int(255 * a),))
    img.alpha_composite(ov)


def kolam(d, cx, cy, n, sp, prog, color=JASMINE, width=3):
    off = (n - 1) * sp / 2
    pts = [(cx - off + i * sp, cy - off + j * sp) for j in range(n) for i in range(n)]
    for x, y in pts:
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=color)
    total = len(pts)
    for k, (x, y) in enumerate(pts):
        lp = clamp(prog * (total + 4) - k * 0.9, 0, 1)
        if lp <= 0:
            continue
        r = sp * 0.5
        d.arc([x - r, y - r, x + r, y + r], 45, 45 + 360 * lp, fill=color, width=width)
    lp = clamp(prog * 1.3 - 0.3)
    if lp > 0:
        R = off + sp * 0.9
        d.arc([cx - R, cy - R, cx + R, cy + R], 0, 360 * lp, fill=color, width=width)
        for a in range(8):
            ang = a * math.pi / 4
            px, py = cx + (R + 14) * math.cos(ang), cy + (R + 14) * math.sin(ang)
            if a / 8 < lp:
                d.ellipse([px - 9, py - 9, px + 9, py + 9], outline=color, width=width)


def gopuram(d, cx, base, s=1.0, body=(196, 128, 72), dark=(150, 90, 50), sil=None):
    c1 = sil or body
    c2 = sil or dark
    bw, bh = 360 * s, 90 * s
    d.rectangle([cx - bw / 2, base - bh, cx + bw / 2, base], fill=c1)
    if not sil:
        d.rectangle([cx - 30 * s, base - 80 * s, cx + 30 * s, base], fill=(50, 25, 15))
        d.pieslice([cx - 30 * s, base - 110 * s, cx + 30 * s, base - 50 * s], 180, 360, fill=(50, 25, 15))
    y = base - bh
    w = 340 * s
    for i in range(9):
        h = 40 * s
        top_w = w - 30 * s
        d.polygon([(cx - w / 2, y), (cx - top_w / 2, y - h), (cx + top_w / 2, y - h), (cx + w / 2, y)],
                  fill=c1 if i % 2 == 0 else c2)
        if not sil:
            n = max(2, int(top_w / (34 * s)))
            for k in range(n):
                nx = cx - top_w / 2 + (k + 0.5) * top_w / n
                d.rectangle([nx - 6 * s, y - h + 8 * s, nx + 6 * s, y - 6 * s], fill=dark if i % 2 == 0 else body)
                d.ellipse([nx - 5 * s, y - h + 4 * s, nx + 5 * s, y - h + 14 * s], fill=(120, 70, 40))
        y -= h
        w = top_w - 4 * s
    d.chord([cx - w / 2 - 14 * s, y - 50 * s, cx + w / 2 + 14 * s, y + 30 * s], 180, 360, fill=c2)
    for k in range(5):
        kx = cx - w / 2 + (k + 0.5) * w / 5
        col = sil or GOLD
        d.ellipse([kx - 7 * s, y - 34 * s, kx + 7 * s, y - 20 * s], fill=col)
        d.polygon([(kx - 3 * s, y - 32 * s), (kx, y - 50 * s), (kx + 3 * s, y - 32 * s)], fill=col)
    return y


def palm(d, x, base, h, t, lean=0.0, trunk=(110, 80, 50), frond=(40, 110, 40)):
    pts = []
    for i in range(13):
        f = i / 12
        pts.append((x + lean * h * f * f, base - h * f))
    d.line(pts, fill=trunk, width=max(3, int(h / 28)))
    tx, ty = pts[-1]
    for k in range(9):
        ang = math.pi * (0.05 + k * 0.9 / 8) + 0.05 * math.sin(t * 2 + k)
        L = h * 0.42
        fp = []
        for j in range(8):
            f = j / 7
            fp.append((tx - math.cos(ang) * L * f, ty - math.sin(ang) * L * f + (L * 0.55) * f * f))
        d.line(fp, fill=frond, width=max(2, int(h / 45)))
        for j in range(2, 8):
            px, py = fp[j]
            d.line([(px, py), (px + 6, py + h / 20)], fill=frond, width=2)


# ----------------------------------------------------------------- scenes
def scene_title(t, dur):
    img = gradient((40, 8, 20), (90, 20, 30)).convert("RGBA")
    d = ImageDraw.Draw(img)
    kolam(d, 640, 300, 5, 52, t / (dur * 0.8), color=(232, 180, 60, 255))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    o = ImageDraw.Draw(ov)
    a = ease((t - 1.2) / 1.0)
    o.rectangle([0, 470, W, 640], fill=(20, 5, 10, int(150 * a)))
    o.text((640, 525), "TAMIL NADU", font=F_TITLE, fill=GOLD + (int(255 * a),), anchor="mm")
    b = ease((t - 2.0) / 1.0)
    o.text((640, 605), "A Living Heritage  \u2014  from the Sangam age to today", font=F_SUB,
           fill=JASMINE + (int(255 * b),), anchor="mm")
    img.alpha_composite(ov)
    return img


_civ_sky = None


def scene_civ(t, dur):
    global _civ_sky
    if _civ_sky is None:
        _civ_sky = gradient((45, 25, 70), (245, 150, 70))
    p = t / dur
    img = _civ_sky.copy().convert("RGBA")
    glow(img, 640, 470 - 140 * p, 220, (255, 210, 120), 0.9)
    d = ImageDraw.Draw(img)
    d.ellipse([640 - 70, 400 - 140 * p, 640 + 70, 540 - 140 * p], fill=(255, 215, 120))
    gopuram(d, 230, 600, 0.55, sil=(90, 45, 50))
    gopuram(d, 1050, 600, 0.6, sil=(90, 45, 50))
    gopuram(d, 640, 610, 1.0)
    d.rectangle([0, 600, W, H], fill=(90, 50, 30))
    d.rectangle([0, 596, W, 612], fill=(150, 95, 55))
    for b in range(6):
        bx = (b * 180 + t * 70) % (W + 200) - 100
        by = 140 + 30 * math.sin(b * 1.7) + 6 * math.sin(t * 3 + b)
        wing = 8 * math.sin(t * 9 + b)
        d.line([(bx - 14, by - wing), (bx, by), (bx + 14, by - wing)], fill=(40, 20, 30), width=3)
    caption(img, t, dur, "Civilization & History", SUBJ["civilization_and_history"], 1.4)
    return img


_pongal_bg = None


def scene_pongal(t, dur):
    global _pongal_bg
    if _pongal_bg is None:
        _pongal_bg = gradient((255, 225, 160), (245, 160, 90))
        dd = ImageDraw.Draw(_pongal_bg)
        dd.rectangle([0, 470, W, H], fill=(196, 132, 78))
        dd.rectangle([0, 470, W, 478], fill=(160, 100, 60))
    p = t / dur
    img = _pongal_bg.copy().convert("RGBA")
    d = ImageDraw.Draw(img)
    kolam(d, 200, 530, 4, 26, p * 1.2, color=(255, 255, 250, 255))
    kolam(d, 1080, 530, 4, 26, p * 1.2 - 0.1, color=(255, 255, 250, 255))
    # sugarcane
    for sx, ph in ((430, 0), (460, 1), (820, 2), (850, 3)):
        for k in range(10):
            y0 = 560 - k * 42
            d.rectangle([sx - 6, y0 - 40, sx + 6, y0], fill=(120, 55, 95))
            d.rectangle([sx - 7, y0 - 3, sx + 7, y0], fill=(200, 180, 110))
        tip = 560 - 420
        for lf in range(5):
            ang = -math.pi / 2 + (lf - 2) * 0.45 + 0.08 * math.sin(t * 2 + ph + lf)
            d.line([(sx, tip), (sx + 110 * math.cos(ang), tip + 110 * math.sin(ang) + 30)], fill=LEAF, width=4)
    # stove and fire
    for bx in (560, 720):
        d.rectangle([bx - 40, 520, bx + 40, 570], fill=(150, 50, 40))
    for k in range(5):
        flame(d, 600 + k * 20, 560, 2.0, t, k)
    glow(img, 640, 540, 120, (255, 150, 40), 0.5)
    d = ImageDraw.Draw(img)
    # pot
    d.ellipse([640 - 125, 330, 640 + 125, 540], fill=(170, 90, 45))
    d.rectangle([640 - 70, 300, 640 + 70, 345], fill=(160, 82, 40))
    d.ellipse([640 - 82, 286, 640 + 82, 318], fill=(140, 70, 35))
    d.ellipse([640 - 70, 291, 640 + 70, 313], fill=(245, 240, 225))
    for k in range(13):
        a = math.pi * (0.1 + 0.8 * k / 12)
        x, y = 640 - 115 * math.cos(a), 440 + 30 * math.sin(a)
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=JASMINE)
        d.ellipse([x - 4, y + 18, x + 4, y + 26], fill=KUMKUM)
    for lf in range(-3, 4):
        d.polygon([(640 + lf * 16, 340), (640 + lf * 22 - 6, 395), (640 + lf * 22 + 6, 395)], fill=(70, 140, 50))
    # overflow
    of = ease((p - 0.25) / 0.6)
    if of > 0:
        for side in (-1, 1):
            for k in range(int(10 * of) + 1):
                x = 640 + side * (70 + k * 4)
                y = 300 + k * 13
                r = 16 - k * 0.8
                d.ellipse([x - r, y - r, x + r, y + r], fill=(252, 250, 240))
        for k in range(9):
            x = 640 - 72 + k * 18
            d.ellipse([x - 14, 280 - 10 * of, x + 14, 304], fill=(252, 250, 240))
    # steam
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    o = ImageDraw.Draw(ov)
    for k in range(10):
        ph = (t * 0.5 + k / 10) % 1
        x = 640 + 50 * math.sin(k * 2.1 + ph * 4)
        y = 280 - ph * 220
        r = 12 + 30 * ph
        o.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, int(110 * (1 - ph))))
    img.alpha_composite(ov)
    caption(img, t, dur, "Thai Pongal \u2014 Village Life", PROMPT["3_ACTION"]["cultural_activities"], 1.4)
    return img


def scene_arts(t, dur):
    img = gradient((50, 5, 20), (110, 25, 35)).convert("RGBA")
    d = ImageDraw.Draw(img)
    d.polygon([(0, 560), (W, 560), (W, H), (0, H)], fill=(90, 50, 25))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    o = ImageDraw.Draw(ov)
    o.polygon([(560, 0), (720, 0), (900, 600), (380, 600)], fill=(255, 220, 150, 45))
    o.ellipse([380, 560, 900, 630], fill=(255, 220, 150, 60))
    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    # rotating halo mandala
    cx, cy = 640, 330
    rot = t * 0.4
    for ring, (n, R, col) in enumerate(((16, 230, (150, 30, 60)), (12, 170, (200, 120, 40)), (8, 100, (230, 170, 60)))):
        for k in range(n):
            a = rot * (1 if ring % 2 == 0 else -1) + k * 2 * math.pi / n
            px, py = cx + R * 0.55 * math.cos(a), cy + R * 0.55 * math.sin(a)
            pts = []
            for j in range(12):
                b = j / 12 * 2 * math.pi
                ex, ey = R * 0.45 * math.cos(b), R * 0.12 * math.sin(b)
                pts.append((px + ex * math.cos(a) - ey * math.sin(a), py + ex * math.sin(a) + ey * math.cos(a)))
            d.polygon(pts, fill=col)
    # dancer (aramandi pose, arms moving between adavu positions)
    fy = 600
    skin, cost = (140, 85, 55), (190, 20, 60)
    s = math.sin(t * 2.2)
    d.line([(cx - 72, fy), (cx - 92, fy - 70), (cx - 24, fy - 120)], fill=skin, width=14, joint="curve")
    d.line([(cx + 72, fy), (cx + 92, fy - 70), (cx + 24, fy - 120)], fill=skin, width=14, joint="curve")
    d.ellipse([cx - 86, fy - 8, cx - 58, fy + 4], fill=KUMKUM)
    d.ellipse([cx + 58, fy - 8, cx + 86, fy + 4], fill=KUMKUM)
    d.polygon([(cx - 30, fy - 125), (cx + 30, fy - 125), (cx + 80, fy - 50), (cx - 80, fy - 50)], fill=cost)
    for k in range(7):
        x = cx - 72 + k * 24
        d.line([(cx, fy - 120), (x, fy - 52)], fill=GOLD, width=2)
    d.rectangle([cx - 80, fy - 56, cx + 80, fy - 48], fill=GOLD)
    d.polygon([(cx - 26, fy - 125), (cx + 26, fy - 125), (cx + 32, fy - 215), (cx - 32, fy - 215)], fill=cost)
    d.rectangle([cx - 26, fy - 135, cx + 26, fy - 125], fill=GOLD)
    for side in (-1, 1):
        sx, sy = cx + side * 32, fy - 210
        lift = s * side
        ex, ey = sx + side * 55, sy + 10 - 30 * lift
        hx, hy = ex + side * 55, ey - 10 - 40 * lift
        d.line([(sx, sy), (ex, ey), (hx, hy)], fill=skin, width=12, joint="curve")
        d.ellipse([hx - 8, hy - 8, hx + 8, hy + 8], fill=skin)
        d.ellipse([ex - 7, ey - 7, ex + 7, ey + 7], outline=GOLD, width=3)
    d.rectangle([cx - 8, fy - 235, cx + 8, fy - 212], fill=skin)
    d.ellipse([cx - 22, fy - 280, cx + 22, fy - 232], fill=skin)
    d.ellipse([cx - 24, fy - 286, cx + 24, fy - 262], fill=(25, 15, 15))
    d.ellipse([cx + 14, fy - 276, cx + 40, fy - 250], fill=(25, 15, 15))
    for k in range(5):
        d.ellipse([cx + 18 + k * 3, fy - 250 + k * 4, cx + 26 + k * 3, fy - 242 + k * 4], fill=JASMINE)
    d.ellipse([cx - 3, fy - 266, cx + 3, fy - 260], fill=KUMKUM)
    # curtains
    for side in (0, 1):
        x0 = 0 if side == 0 else W - 170
        d.rectangle([x0, 0, x0 + 170, H], fill=MAROON)
        for k in range(6):
            fx = x0 + 15 + k * 28
            d.line([(fx, 0), (fx, H)], fill=(80, 5, 25), width=6)
    d.rectangle([0, 0, W, 50], fill=MAROON)
    for k in range(32):
        d.chord([k * 40, 25, k * 40 + 40, 75], 0, 180, fill=GOLD)
    # kuthuvilakku lamps
    for lx in (260, 1020):
        d.polygon([(lx - 40, 600), (lx + 40, 600), (lx + 20, 580), (lx - 20, 580)], fill=BRONZE)
        d.rectangle([lx - 5, 430, lx + 5, 580], fill=(190, 140, 60))
        d.ellipse([lx - 45, 418, lx + 45, 442], fill=(200, 150, 60))
        for k in range(5):
            flame(d, lx - 36 + k * 18, 425, 1.0, t, k + lx)
        glow(img, lx, 410, 90, (255, 170, 60), 0.35)
        d = ImageDraw.Draw(img)
    caption(img, t, dur, "Classical & Folk Arts", SUBJ["classical_and_folk_arts"], 1.2)
    return img


def scene_music(t, dur):
    img = gradient((5, 30, 55), (0, 90, 110)).convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    o = ImageDraw.Draw(ov)
    beat = 0.6
    for k in range(4):
        ph = ((t + k * beat / 2) % (beat * 2)) / (beat * 2)
        R = 80 + ph * 650
        o.ellipse([640 - R, 330 - R, 640 + R, 330 + R], outline=(240, 200, 90, int(160 * (1 - ph))), width=5)
    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    for k in range(48):
        x = 20 + k * 26
        hgt = 30 + 60 * abs(math.sin(t * 3 + k * 0.5)) * (0.6 + 0.4 * math.sin(t * 1.3 + k * 0.21))
        d.rectangle([x, 590 - hgt, x + 16, 590], fill=(230, 180, 60) if k % 2 else (40, 170, 170))
    # thavil
    tx, ty = 450, 360
    hit = 1 - ((t % beat) / beat)
    d.rectangle([tx - 110, ty - 85, tx + 110, ty + 85], fill=(120, 60, 30))
    d.ellipse([tx - 140, ty - 95, tx - 80, ty + 95], fill=(220, 200, 160))
    d.ellipse([tx + 80, ty - 95, tx + 140, ty + 95], fill=(220, 200, 160))
    for k in range(9):
        y = ty - 80 + k * 20
        d.line([(tx - 105, y), (tx + 105, y + 10)], fill=(200, 160, 90), width=3)
    d.ellipse([tx - 128 - hit * 6, ty - 50, tx - 92 + hit * 6, ty + 50], outline=GOLD, width=3)
    # nadaswaram
    nx0, ny0, nx1, ny1 = 760, 140, 940, 520
    L = math.hypot(nx1 - nx0, ny1 - ny0)
    ux, uy = (nx1 - nx0) / L, (ny1 - ny0) / L
    px, py = -uy, ux
    pts = [(nx0 + px * 8, ny0 + py * 8), (nx1 + px * 22, ny1 + py * 22), (nx1 - px * 22, ny1 - py * 22),
           (nx0 - px * 8, ny0 - py * 8)]
    d.polygon(pts, fill=(70, 35, 20))
    d.polygon([(nx1 + px * 22, ny1 + py * 22), (nx1 + px * 55 + ux * 60, ny1 + py * 55 + uy * 60),
               (nx1 - px * 55 + ux * 60, ny1 - py * 55 + uy * 60), (nx1 - px * 22, ny1 - py * 22)], fill=GOLD)
    for k in range(1, 8):
        f = k / 8
        cxk, cyk = nx0 + (nx1 - nx0) * f, ny0 + (ny1 - ny0) * f
        wd = 8 + 14 * f
        d.line([(cxk + px * wd, cyk + py * wd), (cxk - px * wd, cyk - py * wd)], fill=GOLD, width=3)
    for k in range(5):
        ph = (t * 0.7 + k / 5) % 1
        mx = nx1 + 80 + ph * 220 + 20 * math.sin(ph * 9)
        my = ny1 + 30 - ph * 300
        d.ellipse([mx - 10, my - 7, mx + 10, my + 7], fill=JASMINE)
        d.line([(mx + 9, my), (mx + 9, my - 34)], fill=JASMINE, width=3)
    caption(img, t, dur, "Music & Instruments", SUBJ["music_and_instruments"], 1.0)
    return img


random.seed(7)
STARS = [(random.randrange(W), random.randrange(330), random.random() * 6) for _ in range(140)]
LAMPS = [(60 + c * 92 + (r % 2) * 46, 500 + r * 40, random.random() * 6) for r in range(3) for c in range(14)]


def scene_festival(t, dur):
    p = t / dur
    img = gradient((8, 8, 30), (55, 25, 75)).convert("RGBA")
    d = ImageDraw.Draw(img)
    for x, y, ph in STARS:
        b = int(150 + 100 * math.sin(t * 3 + ph))
        d.point([(x, y), (x + 1, y)], fill=(b, b, b))
    d.polygon([(560, 480), (800, 230), (860, 215), (920, 240), (1200, 480)], fill=(28, 22, 40))
    glow(img, 860, 190, 140, (255, 160, 50), 0.8)
    d = ImageDraw.Draw(img)
    flame(d, 860, 215, 3.0, t)
    gopuram(d, 270, 480, 0.7, sil=(20, 15, 30))
    d.rectangle([0, 480, W, H], fill=(35, 20, 25))
    # fireworks
    for k, (bt, bx, by, col) in enumerate(((1.0, 380, 140, (255, 120, 160)), (2.4, 1050, 110, TURMERIC),
                                           (3.8, 600, 90, (120, 220, 255)), (4.7, 200, 120, GOLD))):
        ph = (t - bt) / 1.4
        if 0 < ph < 1:
            for j in range(24):
                a = j * 2 * math.pi / 24
                R = 110 * ease(ph)
                x, y = bx + R * math.cos(a), by + R * math.sin(a) + 30 * ph * ph
                c = tuple(int(v * (1 - ph)) for v in col)
                d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=c)
    lit = p * 1.4
    for i, (x, y, ph) in enumerate(LAMPS):
        d.chord([x - 22, y - 14, x + 22, y + 14], 0, 180, fill=(170, 80, 40))
        d.line([(x - 22, y), (x + 22, y)], fill=(210, 120, 60), width=3)
        if (x / W) < lit:
            glow(img, x, y - 12, 40, (255, 160, 60), 0.35, rings=4)
            d = ImageDraw.Draw(img)
            flame(d, x, y - 2, 0.9, t, ph)
    caption(img, t, dur, "Festivals & Celebrations", SUBJ["festivals_and_celebrations"], 1.0)
    return img


_wood = None
FOODS = [  # (x, y, kind, label)
    (440, 300, "rice", "Rice"), (330, 250, "dab", "Pickle"), (420, 215, "poriyal", "Poriyal"),
    (540, 205, "kootu", "Kootu"), (660, 210, "papad", "Appalam"), (780, 220, "vada", "Medu vada"),
    (880, 250, "payasam", "Payasam"), (960, 380, "banana", "Banana"), (600, 330, "pongal", "Sakkarai Pongal"),
    (740, 340, "idli", "Idli"),
]


def scene_food(t, dur):
    global _wood
    if _wood is None:
        _wood = Image.new("RGB", (W, H), (95, 55, 30))
        dd = ImageDraw.Draw(_wood)
        rnd = random.Random(3)
        for k in range(90):
            y = rnd.randrange(H)
            pts = [(x, y + 6 * math.sin(x / 90 + k)) for x in range(0, W + 40, 40)]
            dd.line(pts, fill=(80 + rnd.randrange(20), 45, 25), width=rnd.randrange(1, 4))
        leaf = [(130, 300)]
        for k in range(41):
            a = math.pi * k / 40
            leaf.append((640 - 520 * math.cos(a), 300 - 190 * math.sin(a) ** 0.8))
        for k in range(41):
            a = math.pi * k / 40
            leaf.append((640 + 520 * math.cos(a), 300 + 200 * math.sin(a) ** 0.8))
        dd.polygon(leaf, fill=(55, 140, 45))
        dd.line([(130, 300), (1160, 300)], fill=(120, 190, 90), width=5)
        for k in range(1, 26):
            x = 130 + k * 40
            dd.line([(x, 300), (x + 50, 130)], fill=(75, 160, 60), width=2)
            dd.line([(x, 300), (x + 50, 470)], fill=(75, 160, 60), width=2)
    p = t / dur
    img = _wood.copy().convert("RGBA")
    d = ImageDraw.Draw(img)
    for i, (x, y, kind, label) in enumerate(FOODS):
        sc = ease((p * 1.25 - i * 0.08) / 0.1)
        if sc <= 0:
            continue
        r = lambda v: v * sc
        if kind == "rice":
            d.ellipse([x - r(80), y - r(45), x + r(80), y + r(45)], fill=(250, 248, 238))
            d.ellipse([x - r(40), y - r(22), x + r(40), y + r(6)], fill=(240, 160, 40))
        elif kind == "dab":
            d.ellipse([x - r(22), y - r(16), x + r(22), y + r(16)], fill=(180, 30, 20))
        elif kind == "poriyal":
            d.ellipse([x - r(40), y - r(22), x + r(40), y + r(22)], fill=(140, 190, 60))
        elif kind == "kootu":
            d.ellipse([x - r(40), y - r(22), x + r(40), y + r(22)], fill=(225, 190, 90))
        elif kind == "papad":
            d.ellipse([x - r(55), y - r(45), x + r(55), y + r(45)], fill=(245, 215, 130))
        elif kind == "vada":
            d.ellipse([x - r(42), y - r(32), x + r(42), y + r(32)], fill=(170, 100, 40))
            d.ellipse([x - r(10), y - r(8), x + r(10), y + r(8)], fill=(55, 140, 45))
        elif kind == "payasam":
            d.ellipse([x - r(40), y - r(28), x + r(40), y + r(28)], fill=(200, 200, 205))
            d.ellipse([x - r(32), y - r(20), x + r(32), y + r(18)], fill=(240, 215, 170))
        elif kind == "banana":
            d.chord([x - r(70), y - r(40), x + r(70), y + r(60)], 200, 340, fill=(250, 220, 60))
        elif kind == "pongal":
            d.ellipse([x - r(50), y - r(32), x + r(50), y + r(32)], fill=(170, 95, 35))
            for k in range(5):
                d.ellipse([x - r(30) + k * r(14), y - r(8), x - r(24) + k * r(14), y - r(2)], fill=(240, 220, 160))
        elif kind == "idli":
            for k in range(2):
                d.ellipse([x - r(40) + k * r(42), y - r(24), x + r(2) + k * r(42), y + r(24)], fill=(250, 250, 245))
        if sc > 0.9:
            d.text((x, y + 48 * sc + 8), label, font=F_SMALL, fill=JASMINE, anchor="mm")
    # filter coffee
    dx = 1150
    d.polygon([(dx - 70, 600), (dx + 70, 600), (dx + 60, 560), (dx - 60, 560)], fill=(190, 195, 200))
    d.rectangle([dx - 70, 600, dx + 70, 612], fill=(170, 175, 180))
    d.polygon([(dx - 40, 560), (dx + 40, 560), (dx + 46, 450), (dx - 46, 450)], fill=(205, 210, 215))
    d.ellipse([dx - 46, 440, dx + 46, 460], fill=(150, 100, 60))
    d.text((dx, 630), "Filter coffee", font=F_SMALL, fill=JASMINE, anchor="mm")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    o = ImageDraw.Draw(ov)
    for k in range(6):
        ph = (t * 0.4 + k / 6) % 1
        x = dx + 18 * math.sin(ph * 7 + k)
        y = 440 - ph * 120
        o.ellipse([x - 10 - 12 * ph, y - 10, x + 10 + 12 * ph, y + 10], fill=(255, 255, 255, int(90 * (1 - ph))))
    img.alpha_composite(ov)
    caption(img, t, dur, "Food & Culinary Heritage", SUBJ["food_and_culinary_heritage"], 1.2)
    return img


_silk = None


def scene_crafts(t, dur):
    global _silk
    if _silk is None:
        arr = np.zeros((H, W, 3), np.float32)
        yy, xx = np.mgrid[0:H, 0:W]
        base = np.array(MAROON, np.float32)
        arr[:] = base
        arr += ((xx // 6 + yy // 6) % 2)[..., None] * 8
        _silk = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
        dd = ImageDraw.Draw(_silk)
        dd.rectangle([0, 420, W, 600], fill=(200, 150, 40))
        dd.rectangle([0, 432, W, 588], fill=(140, 20, 50))
        for k in range(0, W, 64):
            dd.polygon([(k, 588), (k + 32, 470), (k + 64, 588)], fill=(225, 175, 55))
            dd.polygon([(k + 18, 588), (k + 32, 520), (k + 46, 588)], fill=(140, 20, 50))
            dd.ellipse([k + 27, 455, k + 37, 465], fill=(225, 175, 55))
        dd.rectangle([0, 600, W, H], fill=(225, 175, 55))
        for k in range(0, W, 20):
            dd.line([(k, 604), (k + 10, 616)], fill=(160, 110, 30), width=2)
        rnd = random.Random(5)
        for j in range(5):
            for i in range(14):
                x = 45 + i * 92 + (j % 2) * 46
                y = 50 + j * 76
                dd.ellipse([x - 12, y - 12, x + 12, y + 12], fill=(225, 175, 55))
                dd.polygon([(x - 6, y - 8), (x + 10, y - 26), (x + 6, y - 2)], fill=(225, 175, 55))
                dd.ellipse([x - 5, y - 5, x + 5, y + 5], fill=MAROON)
    p = t / dur
    edge = int(W * (0.15 + 0.85 * ease(p / 0.85)))
    img = Image.new("RGBA", (W, H), (60, 40, 30, 255))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 7):
        col = (225, 175, 55) if (x // 7) % 5 == 0 else (150, 30, 60)
        d.line([(x, 0), (x, H)], fill=col, width=2)
    img.paste(_silk.crop((0, 0, edge, H)), (0, 0))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    o = ImageDraw.Draw(ov)
    sx = (t * 350) % (W + 600) - 300
    o.polygon([(sx, 0), (sx + 120, 0), (sx - 80, H), (sx - 200, H)], fill=(255, 240, 200, 40))
    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    d.rectangle([edge - 6, 0, edge + 6, H], fill=(90, 60, 35))
    sy = 300 + 260 * math.sin(t * 2.5)
    d.polygon([(edge - 10, sy - 40), (edge + 10, sy - 40), (edge + 6, sy + 40), (edge - 6, sy + 40)], fill=(200, 160, 100))
    caption(img, t, dur, "Kanchipuram Silk & Handicrafts", SUBJ["handicrafts_and_traditional_industries"], 1.0)
    return img


PANO_W = 2700
_pano = None


def build_pano():
    img = gradient((120, 180, 230), (255, 210, 160), PANO_W, H)
    d = ImageDraw.Draw(img)
    d.ellipse([1500, 90, 1600, 190], fill=(255, 240, 200))
    rnd = random.Random(11)
    for layer, (col, base, amp) in enumerate((((120, 150, 175), 330, 160), ((80, 120, 110), 380, 120),
                                              ((50, 100, 70), 430, 90))):
        pts = [(0, H)]
        for x in range(0, 1700, 20):
            y = base - amp * (0.5 + 0.5 * math.sin(x / (180 - layer * 30) + layer)) * (1 - x / 2000)
            y += rnd.uniform(-6, 6)
            pts.append((x, y))
        pts += [(1700, 470), (1700, H)]
        d.polygon(pts, fill=col)
    for r in range(8):
        y = 380 + r * 14
        for x in range(60, 800, 26):
            d.ellipse([x, y, x + 20, y + 9], fill=(40 + r * 5, 120, 55))
    d.rectangle([0, 470, 2000, H], fill=(95, 165, 60))
    for r in range(12):
        y = 480 + r * 20
        d.line([(0, y), (2000, y)], fill=(120, 190, 70), width=3)
    pts = [(1950, H), (2000, 470)]
    pts += [(PANO_W, 470), (PANO_W, H)]
    d.polygon([(1900, H), (2000, 470), (2080, 470), (2000, H)], fill=(235, 215, 165))
    d.rectangle([2040, 470, PANO_W, H], fill=(40, 120, 160))
    for k in range(30):
        y = 480 + k * 8
        d.line([(2060, y), (PANO_W, y)], fill=(70, 150, 185), width=1)
    gopuram(d, 1300, 470, 0.5)
    for (x, hgt, lean) in ((900, 260, 0.1), (960, 220, -0.08), (1550, 280, 0.12), (1640, 240, -0.1),
                           (1880, 300, 0.15), (1960, 250, -0.05), (300, 200, 0.06)):
        palm(d, x, 480, hgt, 0.0, lean)
    for hx in (1050, 1130):
        d.rectangle([hx - 35, 430, hx + 35, 475], fill=(230, 220, 200))
        d.polygon([(hx - 48, 435), (hx, 395), (hx + 48, 435)], fill=(180, 80, 50))
        d.rectangle([hx - 8, 448, hx + 8, 475], fill=(90, 50, 30))
    return img


REGIONS = list(PROMPT["4_LOCATION"]["regional_representation"].items())


def scene_regions(t, dur):
    global _pano
    if _pano is None:
        _pano = build_pano()
    p = ease(t / dur)
    off = int((PANO_W - W) * p)
    img = _pano.crop((off, 0, off + W, H)).convert("RGBA")
    d = ImageDraw.Draw(img)
    for k in range(4):
        bx = 2200 + k * 120 - off
        by = 540 + k * 30 + 6 * math.sin(t * 2 + k)
        d.polygon([(bx - 45, by), (bx + 45, by), (bx + 30, by + 18), (bx - 30, by + 18)], fill=(110, 60, 30))
        d.line([(bx, by), (bx, by - 70)], fill=(80, 50, 30), width=3)
        d.polygon([(bx + 2, by - 68), (bx + 40, by - 20), (bx + 2, by - 14)], fill=JASMINE)
    items = [f"{name.replace('_', ' ').title()}  \u2014  {', '.join(v[:2])}" for name, v in REGIONS]
    caption(img, t, dur, "Regions of Tamil Nadu", items, dur / len(items))
    return img


def scene_outro(t, dur):
    img = gradient((40, 8, 20), (15, 5, 10)).convert("RGBA")
    d = ImageDraw.Draw(img)
    pal = PROMPT["5_ESTHETICS"]["color_palette"]
    cols = [KUMKUM, TURMERIC, GOLD, MAROON, PEACOCK, LEAF, TERRACOTTA, BRONZE, JASMINE]
    for i, (name, col) in enumerate(zip(pal, cols)):
        a = ease((t - i * 0.15) / 0.5)
        x = 120 + i * 130
        y = 420 + 40 * (1 - a)
        R = 42 * a
        d.ellipse([x - R, y - R, x + R, y + R], fill=col, outline=GOLD, width=2)
        if a > 0.8:
            d.text((x, y + 66), name, font=font("georgia.ttf", 17), fill=JASMINE, anchor="mm")
    a = ease((t - 0.6) / 1.0)
    d.text((640, 200), "TAMIL NADU", font=F_TITLE, fill=tuple(int(c * a) for c in GOLD), anchor="mm")
    d.text((640, 285), "Pride \u00b7 Devotion \u00b7 Togetherness \u00b7 Hospitality", font=F_SUB,
           fill=tuple(int(c * a) for c in JASMINE), anchor="mm")
    d.text((640, 640), "Generated from tamil_prompt.json", font=F_SMALL,
           fill=tuple(int(c * a * 0.7) for c in JASMINE), anchor="mm")
    return img


SCENES = [(scene_title, 5), (scene_civ, 6), (scene_pongal, 7), (scene_arts, 6), (scene_music, 6),
          (scene_festival, 6), (scene_food, 6), (scene_crafts, 6), (scene_regions, 7), (scene_outro, 5)]
TOTAL = sum(d for _, d in SCENES)
assert TOTAL == 60


def render_frame(gt):
    acc = 0
    for fn, dur in SCENES:
        if gt < acc + dur:
            t = gt - acc
            img = fn(t, dur).convert("RGB")
            fade = ease(t / 0.4) * ease((dur - t) / 0.4)
            if fn is SCENES[0][0]:
                fade = ease((dur - t) / 0.4) * ease(t / 0.8)
            # gentle Ken Burns zoom
            z = 1 + 0.04 * (t / dur)
            cw, ch = W / z, H / z
            img = img.crop(((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2)).resize((W, H), Image.BILINEAR)
            if fade < 1:
                img = Image.fromarray((np.asarray(img, np.float32) * fade).astype(np.uint8))
            return img
        acc += dur
    return Image.new("RGB", (W, H))


# ----------------------------------------------------------------- audio
def make_audio(path, sr=44100):
    n = sr * TOTAL
    t = np.arange(n) / sr
    out = np.zeros(n, np.float32)
    sa = 130.81
    # tanpura: Pa - Sa' - Sa' - Sa plucked in a 2 s cycle
    pattern = [sa * 1.5, sa * 2, sa * 2, sa]
    step = 0.5
    pl = int(sr * 2.0)
    tt = np.arange(pl) / sr
    for i in range(int(TOTAL / step)):
        f = pattern[i % 4]
        tone = sum((0.6 / h) * np.sin(2 * np.pi * f * h * tt + h) for h in range(1, 9))
        tone *= np.exp(-tt * 1.4) * (1 + 0.3 * np.sin(2 * np.pi * 3 * tt))
        s = int(i * step * sr)
        e = min(n, s + pl)
        out[s:e] += 0.18 * tone[: e - s]
    # thavil-style percussion from 5 s to 55 s, 100 bpm, 8-beat pattern
    beat = 0.6
    rng = random.Random(1)
    bl = int(sr * 0.35)
    bt = np.arange(bl) / sr
    low = np.sin(2 * np.pi * (60 + 90 * np.exp(-bt * 25)) * bt) * np.exp(-bt * 9)
    slap = np.array([rng.gauss(0, 1) for _ in range(bl)]) * np.exp(-bt * 45)
    accents = [1.0, 0.0, 0.5, 0.7, 0.0, 0.6, 0.5, 0.3]
    k = 0
    tb = 5.0
    while tb < 55:
        a = accents[k % 8]
        intensity = 1.3 if 23 <= tb < 41 else 0.8
        if a:
            s = int(tb * sr)
            e = min(n, s + bl)
            hit = (low * 0.9 + slap * 0.25) if k % 2 == 0 else (slap * 0.5 + low * 0.3)
            out[s:e] += 0.35 * a * intensity * hit[: e - s]
        tb += beat / 2
        k += 1
    env = np.minimum(1, t / 2.5) * np.minimum(1, (TOTAL - t) / 3.0)
    out *= env
    out /= np.abs(out).max() + 1e-9
    out *= 0.85
    pcm = (out * 32767).astype(np.int16)
    stereo = np.stack([pcm, pcm], axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())


def main():
    out = HERE / "tamil_culture.mp4"
    wav = HERE / "_soundtrack.wav"
    make_audio(wav)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "24",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frames = TOTAL * FPS
    for i in range(frames):
        proc.stdin.write(render_frame(i / FPS).tobytes())
        if i % 120 == 0:
            print(f"frame {i}/{frames}", flush=True)
    proc.stdin.close()
    proc.wait()
    wav.unlink()
    print("wrote", out)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--stills":
        for k, (fn, dur) in enumerate(SCENES):
            render_frame(sum(d for _, d in SCENES[:k]) + dur * 0.6).save(HERE / f"_still_{k}.png")
    else:
        main()
