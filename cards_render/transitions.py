#!/usr/bin/env python3
"""ПЕРЕХОДЫ МЕЖДУ СЦЕНАМИ (21.10.2026).

Ролик из шести десятков сцен клеился встык, и вся работа, вложенная в
элементы, на стыках пропадала. Здесь пять переходов одним языком с
остальным арсеналом: без тряски, без мельтешения, длительность 0,4-0,9 с.

  dip        — уход в чёрное и выход (классика, самый спокойный)
  flash      — засвет: кадр вспыхивает и проявляется следующий
  defocus    — уход в расфокус и выход из него уже на новом кадре
  torn_wipe  — рваный край бумаги проходит по кадру и открывает следующий
  film_run   — плёнка протягивается: кадр уезжает вверх через перфорацию

  transition(a, b, kind, p) — p от 0 (виден A) до 1 (виден B)
"""
import math
import os
import random
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torn_photo as tp

W, H, FPS = 1920, 1080, 25
KINDS = ("dip", "flash", "defocus", "torn_wipe", "film_run")


def _img(x):
    if isinstance(x, Image.Image):
        return x.convert("RGB")
    im = Image.open(x).convert("RGB")
    if im.size != (W, H):
        k = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
        im = im.crop(((im.width - W) // 2, (im.height - H) // 2,
                      (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    return im


def _mul(im, k):
    return Image.fromarray(np.clip(np.asarray(im, np.float32) * k, 0, 255).astype(np.uint8))


def _edge_mask(p, seed=23, amp=46, teeth=11):
    """Рваный край, идущий слева направо: 255 там, где уже виден новый кадр."""
    xs = tp._edge(H, 0, seed, amp, teeth, fibers=True)
    x0 = -140 + p * (W + 280)
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    for y in range(H):
        d.line([(0, y), (int(x0 + xs[y]), y)], fill=255)
    band = tp._edge_band((W, H), xs + x0, 17, seed)
    return m, band


def transition(a, b, kind="dip", p=0.5, seed=23):
    """Кадр перехода: p=0 — целиком A, p=1 — целиком B."""
    A, B = _img(a), _img(b)
    p = max(0.0, min(1.0, p))

    if kind == "dip":
        # два полушага: A гаснет, B разгорается
        if p < 0.5:
            return _mul(A, 1 - p * 2)
        return _mul(B, (p - 0.5) * 2)

    if kind == "flash":
        # вспышка в белое: короткая, иначе бьёт по глазам
        g = math.sin(math.pi * p) ** 1.6
        base = A if p < 0.5 else B
        arr = np.asarray(base, np.float32) + 255 * g * 0.92
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    if kind == "defocus":
        r = 26 * math.sin(math.pi * p)
        base = A if p < 0.5 else B
        im = base.filter(ImageFilter.GaussianBlur(max(0.01, r)))
        return _mul(im, 1 - 0.18 * math.sin(math.pi * p))

    if kind == "torn_wipe":
        m, band = _edge_mask(p, seed)
        im = Image.composite(B, A, m)
        paper = Image.new("RGB", (W, H), (242, 240, 234))
        im.paste(paper, (0, 0), band)
        return im

    if kind == "film_run":
        # кадр уезжает вверх, между кадрами пробегает межкадровая полоса
        off = int(p * (H + 120))
        im = Image.new("RGB", (W, H), (10, 10, 12))
        im.paste(A, (0, -off))
        im.paste(B, (0, H + 120 - off))
        d = ImageDraw.Draw(im)
        y = H - off + 60
        d.rectangle((0, y - 60, W, y), fill=(12, 12, 14))
        rnd = random.Random(seed)
        for x in range(26, W, 58):
            d.rounded_rectangle((x, y - 46, x + 30, y - 16), 5, fill=(228, 226, 220))
        return _mul(im, 0.92 + 0.08 * abs(0.5 - p) * 2)

    raise ValueError(f"переход неизвестен: {kind}")


def transition_clip(out_mp4, *, a, b, kind="dip", seconds=0.6, hold=0.9,
                    fps=FPS, ffmpeg="ffmpeg", seed=23):
    """Демо-клип: подержать A, перейти, подержать B."""
    tmp = tempfile.mkdtemp()
    i = 0
    A, B = _img(a), _img(b)
    for _ in range(int(hold * fps)):
        A.save(os.path.join(tmp, f"{i:04d}.jpg"), quality=92); i += 1
    n = max(1, int(seconds * fps))
    for k in range(n):
        transition(A, B, kind, (k + 1) / n, seed).save(
            os.path.join(tmp, f"{i:04d}.jpg"), quality=92); i += 1
    for _ in range(int(hold * fps)):
        B.save(os.path.join(tmp, f"{i:04d}.jpg"), quality=92); i += 1
    subprocess.run(["nice", "-n", "19", ffmpeg, "-v", "error", "-framerate", str(fps),
                    "-i", os.path.join(tmp, "%04d.jpg"), "-c:v", "libx264", "-preset",
                    "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-threads", "2",
                    "-y", out_mp4], check=True)
    return out_mp4
