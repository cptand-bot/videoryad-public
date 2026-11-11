# -*- coding: utf-8 -*-
"""Белый зал, вторая реализация: G24 (стена экранов). Запуск: shard_fable_g.py G24 <out>
Один кадр без видео: ZAL_FRAME=1.5 shard_fable_g.py G24 k.png

Снято с плёнки (исходник 5.0–10.0 с):
  · 5.37–5.60 с — камера опускает взгляд с таблички, сверху в кадр входят ДВЕ панели
    (fx 0.43–0.78 и 0.78–0.95, разный разворот); к 6.5 с они висят в верхней части
    кадра fx 0.40–0.57 (дальняя) и 0.58–0.85 (ближняя), fy 0.03–0.30;
  · 7.933 → 7.967 с — ВСЯ стена появляется ЗА ОДИН КАДР (1/30 с): пять панелей
    поперёк верха кадра fx 0.02–0.25 · 0.28–0.47 · 0.48–0.60 (позади, дальше) ·
    0.60–0.80 · 0.80–1.0, fy 0.0–0.30, верх срезан рамкой кадра; ни наезда, ни
    растворения, ни падения;
  · 8.0 → 10.0 с — камера практически стоит (край панели 0.28 → 0.27), панели
    не качаются, все эфиры играют.
Перевод в метры (d ≈ 6.5 м): ширина панели 0.20–0.27 кадра → 1.3–1.7 м,
высота 0.27–0.30 → 1.0–1.07 м; низ ряда fy 0.27–0.30 → y ≈ 2.3 м, верх выше 3.4 м.
"""
import sys, os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as Z
from zal_core import *

FPS = 30

# ---------------- эфиры: всё своё, кодом ----------------
TW, TH = 960, 540          # текстура одной панели
_BG = {}                   # кэш неподвижных подложек студий
_TICK = {}                 # кэш бегущих строк

def _grad(w, h, c0, c1, horiz=False):
    """линейный градиент как RGBA-картинка"""
    n = w if horiz else h
    k = np.linspace(0.0, 1.0, n, dtype=np.float32)
    col = np.array(c0, np.float32)[None, :] * (1 - k[:, None]) + np.array(c1, np.float32)[None, :] * k[:, None]
    if horiz:
        arr = np.repeat(col[None, :, :], h, axis=0)
    else:
        arr = np.repeat(col[:, None, :], w, axis=1)
    rgb = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return rgb.convert("RGBA")

def _skyline(d, w, h, y0, y1, color, seed):
    """силуэт небоскрёбов на заднике"""
    rng = np.random.default_rng(seed)
    x = 0
    while x < w:
        bw = int(rng.uniform(w * 0.03, w * 0.08))
        bh = int(rng.uniform((y1 - y0) * 0.35, (y1 - y0) * 1.0))
        d.rectangle([x, y1 - bh, x + bw, y1], fill=color)
        for yy in range(int(y1 - bh) + 8, int(y1), 14):
            for xx in range(x + 6, x + bw - 6, 12):
                if rng.uniform() < 0.45:
                    d.rectangle([xx, yy, xx + 4, yy + 6], fill=(color[0] + 40, color[1] + 40, color[2] + 50, 255))
        x += bw + int(rng.uniform(4, 18))

def _bookshelf(d, w, h, x0, x1, y0, y1, seed):
    rng = np.random.default_rng(seed)
    d.rectangle([x0, y0, x1, y1], fill=(92, 72, 56, 255))
    for r in range(4):
        yy = y0 + (y1 - y0) * r / 4
        d.rectangle([x0, yy, x1, yy + 6], fill=(60, 46, 36, 255))
        x = x0 + 8
        while x < x1 - 14:
            bw = int(rng.uniform(10, 22)); bh = int(rng.uniform(34, 52))
            c = [int(v) for v in rng.uniform(70, 190, 3)]
            d.rectangle([x, yy + (y1 - y0) / 4 - bh, x + bw, yy + (y1 - y0) / 4 - 2], fill=(c[0], c[1], c[2], 255))
            x += bw + 3

def person(d, cx, cy, s, skin, hair, suit, t, seed, shirt=None, hair_kind="short"):
    """ведущий/гость: плечи, шея, голова, причёска; дышит и чуть качает головой.
    cx — центр, cy — линия низа плеч, s — высота головы в пикселях"""
    bob = math.sin(t * 1.4 + seed) * s * 0.03
    sway = math.sin(t * 0.9 + seed * 2.1) * s * 0.04
    # плечи
    sw = s * 1.95; sh = s * 1.25
    d.polygon([(cx - sw / 2 + sway, cy), (cx + sw / 2 + sway, cy),
               (cx + sw * 0.34 + sway, cy - sh), (cx - sw * 0.34 + sway, cy - sh)], fill=suit)
    if shirt:
        d.polygon([(cx - s * 0.22 + sway, cy - sh), (cx + s * 0.22 + sway, cy - sh),
                   (cx + sway, cy - sh * 0.45)], fill=shirt)
    # шея
    d.rectangle([cx - s * 0.17 + sway, cy - sh - s * 0.22 + bob, cx + s * 0.17 + sway, cy - sh + 4], fill=skin)
    # голова
    hx, hy = cx + sway, cy - sh - s * 0.62 + bob
    d.ellipse([hx - s * 0.36, hy - s * 0.5, hx + s * 0.36, hy + s * 0.5], fill=skin)
    # причёска
    if hair_kind == "short":
        d.chord([hx - s * 0.38, hy - s * 0.54, hx + s * 0.38, hy + s * 0.18], 190, 350, fill=hair)
    elif hair_kind == "long":
        d.chord([hx - s * 0.40, hy - s * 0.56, hx + s * 0.40, hy + s * 0.20], 185, 355, fill=hair)
        d.polygon([(hx - s * 0.40, hy - s * 0.1), (hx - s * 0.52, hy + s * 0.75),
                   (hx - s * 0.18, hy + s * 0.6), (hx - s * 0.34, hy + s * 0.05)], fill=hair)
        d.polygon([(hx + s * 0.40, hy - s * 0.1), (hx + s * 0.52, hy + s * 0.75),
                   (hx + s * 0.18, hy + s * 0.6), (hx + s * 0.34, hy + s * 0.05)], fill=hair)
    elif hair_kind == "bald":
        d.chord([hx - s * 0.36, hy - s * 0.5, hx + s * 0.36, hy + s * 0.1], 200, 340, fill=hair, width=0)
        d.ellipse([hx - s * 0.30, hy - s * 0.52, hx + s * 0.30, hy - s * 0.1], fill=skin)
    elif hair_kind == "glasses":
        d.chord([hx - s * 0.38, hy - s * 0.54, hx + s * 0.38, hy + s * 0.12], 190, 350, fill=hair)
        for gx in (-1, 1):
            d.ellipse([hx + gx * s * 0.18 - s * 0.13, hy - s * 0.12, hx + gx * s * 0.18 + s * 0.13, hy + s * 0.08],
                      outline=(28, 28, 30, 255), width=max(2, int(s * 0.035)))
    if hair_kind != "glasses":
        for gx in (-1, 1):
            d.ellipse([hx + gx * s * 0.15 - s * 0.045, hy - s * 0.06, hx + gx * s * 0.15 + s * 0.045, hy + s * 0.03],
                      fill=(36, 28, 26, 255))
    # петличка
    d.ellipse([cx + sway - s * 0.05, cy - sh * 0.55, cx + sway + s * 0.05, cy - sh * 0.55 + s * 0.1],
              fill=(30, 30, 32, 255))

def _live(d, x, y, t, color=(214, 30, 36, 255), label="ПРЯМОЙ ЭФИР", fs=24):
    f = font("ArialBlack.ttf", fs)
    tw = d.textlength(label, font=f)
    d.rectangle([x, y, x + tw + fs * 1.6, y + fs * 1.5], fill=color)
    if int(t * 2) % 2 == 0:
        d.ellipse([x + fs * 0.45, y + fs * 0.5, x + fs * 0.95, y + fs * 1.0], fill=(255, 255, 255, 255))
    d.text((x + fs * 1.2, y + fs * 0.22), label, font=f, fill=(255, 255, 255, 255))

def _ticker(key, words, fs, color, bg):
    if key not in _TICK:
        f = font("Arimo-Bold.ttf", fs)
        txt = "   •   ".join(words) + "   •   "
        d0 = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        tw = int(d0.textlength(txt, font=f)) + 4
        strip = Image.new("RGBA", (tw * 2, int(fs * 1.6)), bg)
        sd = ImageDraw.Draw(strip)
        sd.text((0, fs * 0.22), txt, font=f, fill=color)
        sd.text((tw, fs * 0.22), txt, font=f, fill=color)
        _TICK[key] = (strip, tw)
    return _TICK[key]

def ticker(img, key, words, t, y, h, fs, color, bg, speed=150, x0=0, x1=TW):
    strip, tw = _ticker(key, words, fs, color, bg)
    off = int(t * speed) % tw
    crop = strip.crop((off, 0, off + (x1 - x0), strip.size[1])).resize((x1 - x0, int(h)))
    img.alpha_composite(crop, (x0, int(y)))

def _clock(t, base="19:42"):
    s = int(t) % 60
    return f"{base}:{s:02d}"

# ---- восемь студий, каждая со своей подложкой, плашкой и людьми ----
STUDIOS = {}

def studio(fn):
    STUDIOS[fn.__name__] = fn; return fn

def _bg(key, maker):
    if key not in _BG:
        _BG[key] = maker()
    return _BG[key].copy()

@studio
def biz(t):
    """деловой канал: тёмно-синяя студия, два окна-гостя, небоскрёбы"""
    def mk():
        img = _grad(TW, TH, (14, 26, 64), (30, 52, 110))
        d = ImageDraw.Draw(img)
        _skyline(d, TW, TH, TH * 0.08, TH * 0.78, (22, 38, 84, 255), 11)
        # два окна
        for x0 in (TW * 0.05, TW * 0.52):
            d.rectangle([x0, TH * 0.12, x0 + TW * 0.43, TH * 0.78], fill=(40, 60, 118, 255), outline=(170, 190, 240, 255), width=4)
        return img
    img = _bg("biz", mk); d = ImageDraw.Draw(img)
    person(d, TW * 0.265, TH * 0.78, 92, (222, 184, 150, 255), (70, 50, 40, 255), (28, 30, 44, 255), t, 1, shirt=(230, 230, 236, 255), hair_kind="short")
    person(d, TW * 0.735, TH * 0.78, 92, (205, 160, 128, 255), (40, 32, 28, 255), (46, 46, 52, 255), t, 2, hair_kind="glasses")
    d.rectangle([0, TH * 0.78, TW, TH * 0.86], fill=(236, 238, 244, 255))
    d.rectangle([0, TH * 0.78, TW * 0.29, TH * 0.86], fill=(200, 24, 36, 255))
    d.text((TW * 0.02, TH * 0.795), "ДЕЛОВОЙ КАНАЛ", font=font("ArialBlack.ttf", 24), fill=(255, 255, 255, 255))
    d.text((TW * 0.31, TH * 0.795), "ГЛАВА КОМПАНИИ: ПЕРЕМЕНЫ БУДУТ БОЛЬШЕ", font=font("Arimo-Bold.ttf", 25), fill=(20, 22, 30, 255))
    ticker(img, "biz", ["РЫНКИ: ИНДЕКС ТЕХНОСЕКТОРА +2,4%", "НЕЙРОСЕТИ В БАНКАХ: ПЕРВЫЕ ИТОГИ", "АВТОР СТАТЬИ ОТВЕЧАЕТ КРИТИКАМ"],
           t, TH * 0.86, TH * 0.14, 30, (240, 240, 244, 255), (12, 18, 40, 255), speed=170)
    _live(d, TW * 0.04, TH * 0.04, t, fs=22)
    d.text((TW * 0.86, TH * 0.045), _clock(t, "09:14"), font=font("Oswald-Bold.ttf", 30), fill=(255, 255, 255, 255))
    return img

@studio
def morning(t):
    """утреннее шоу: тёплый градиент, ведущая, мягкая плашка"""
    def mk():
        img = _grad(TW, TH, (236, 120, 70), (120, 40, 90))
        d = ImageDraw.Draw(img)
        lay = Image.new("RGBA", (TW, TH), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
        ld.ellipse([TW * 0.45, -TH * 0.2, TW * 1.15, TH * 0.9], fill=(255, 200, 120, 90))
        img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(40)))
        d = ImageDraw.Draw(img)
        for i in range(6):
            d.line([(TW * (0.05 + i * 0.17), 0), (TW * (0.0 + i * 0.17), TH * 0.75)], fill=(255, 230, 200, 40), width=6)
        return img
    img = _bg("morning", mk); d = ImageDraw.Draw(img)
    person(d, TW * 0.36, TH * 0.86, 118, (236, 196, 170, 255), (104, 60, 40, 255), (236, 94, 150, 255), t, 3, hair_kind="long")
    d.rounded_rectangle([TW * 0.05, TH * 0.70, TW * 0.70, TH * 0.80], radius=18, fill=(255, 255, 255, 235))
    d.rounded_rectangle([TW * 0.05, TH * 0.80, TW * 0.52, TH * 0.88], radius=14, fill=(248, 86, 120, 255))
    d.text((TW * 0.075, TH * 0.712), "МАРИНА ЛЕБЕДЕВА", font=font("ArialBlack.ttf", 28), fill=(40, 20, 40, 255))
    d.text((TW * 0.075, TH * 0.812), "АВТОР НАШУМЕВШЕЙ СТАТЬИ ОБ ИИ", font=font("Arimo-Bold.ttf", 24), fill=(255, 255, 255, 255))
    d.text((TW * 0.72, TH * 0.06), "УТРО", font=font("ArialBlack.ttf", 44), fill=(255, 255, 255, 255))
    d.text((TW * 0.72, TH * 0.15), "СТОЛИЦЫ", font=font("ArialBlack.ttf", 30), fill=(255, 230, 120, 255))
    d.text((TW * 0.72, TH * 0.24), _clock(t, "07:52"), font=font("Oswald-Bold.ttf", 34), fill=(255, 255, 255, 255))
    return img

@studio
def news(t):
    """новости 24: сине-фиолетовая студия, ведущий, бегущая строка"""
    def mk():
        img = _grad(TW, TH, (36, 30, 110), (70, 50, 160))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, TW * 0.08, TH], fill=(120, 80, 48, 255))
        d.rectangle([TW * 0.08, 0, TW * 0.11, TH], fill=(210, 215, 240, 255))
        for i in range(8):
            d.rectangle([TW * (0.55 + i * 0.055), TH * 0.1, TW * (0.58 + i * 0.055), TH * 0.7], fill=(90, 70, 190, 255))
        return img
    img = _bg("news", mk); d = ImageDraw.Draw(img)
    person(d, TW * 0.33, TH * 0.84, 110, (214, 176, 146, 255), (30, 24, 22, 255), (24, 26, 36, 255), t, 4, shirt=(240, 240, 240, 255), hair_kind="short")
    d.rectangle([0, TH * 0.72, TW * 0.34, TH * 0.80], fill=(255, 212, 0, 255))
    d.text((TW * 0.02, TH * 0.73), "НОВОСТИ 24", font=font("ArialBlack.ttf", 30), fill=(20, 20, 24, 255))
    d.polygon([(0, TH * 0.80), (TW * 0.98, TH * 0.80), (TW, TH * 0.84), (TW * 0.98, TH * 0.88), (0, TH * 0.88)], fill=(246, 247, 250, 255))
    d.text((TW * 0.02, TH * 0.812), "СТАТЬЯ, КОТОРУЮ ОБСУЖДАЮТ ВСЕ: ЧТО ИЗМЕНИТСЯ ЗА ГОД", font=font("ArialBlack.ttf", 24), fill=(26, 26, 30, 255))
    ticker(img, "news", ["ИИ-ПОМОЩНИКИ ПРИШЛИ В СУДЫ И БОЛЬНИЦЫ", "ЭКСПЕРТЫ СПОРЯТ О ПРОГНОЗЕ", "ПРАВИТЕЛЬСТВО ГОТОВИТ ОТВЕТ"],
           t, TH * 0.88, TH * 0.12, 28, (255, 255, 255, 255), (20, 16, 60, 255), speed=140)
    _live(d, TW * 0.80, TH * 0.05, t, label="ЭФИР", fs=24)
    return img

@studio
def tech(t):
    """техно-эфир: бирюзовая студия, схемы на заднике, двое за столом"""
    def mk():
        img = _grad(TW, TH, (8, 44, 52), (16, 90, 96))
        d = ImageDraw.Draw(img)
        rng = np.random.default_rng(7)
        for i in range(40):
            x0, y0 = rng.uniform(0, TW), rng.uniform(0, TH * 0.7)
            x1, y1 = x0 + rng.uniform(-160, 160), y0 + rng.choice([0, rng.uniform(-90, 90)])
            d.line([(x0, y0), (x1, y1)], fill=(60, 200, 190, 90), width=3)
            d.ellipse([x1 - 5, y1 - 5, x1 + 5, y1 + 5], fill=(120, 240, 220, 160))
        d.rectangle([TW * 0.1, TH * 0.72, TW * 0.9, TH * 0.9], fill=(20, 60, 66, 255))
        return img
    img = _bg("tech", mk); d = ImageDraw.Draw(img)
    person(d, TW * 0.32, TH * 0.74, 96, (228, 190, 160, 255), (150, 110, 60, 255), (60, 110, 100, 255), t, 5, hair_kind="long")
    person(d, TW * 0.66, TH * 0.74, 96, (180, 135, 105, 255), (24, 20, 18, 255), (30, 34, 40, 255), t, 6, hair_kind="bald")
    d.rectangle([TW * 0.1, TH * 0.72, TW * 0.9, TH * 0.78], fill=(14, 50, 56, 255))
    d.rounded_rectangle([TW * 0.04, TH * 0.80, TW * 0.96, TH * 0.93], radius=10, fill=(0, 0, 0, 170))
    d.rectangle([TW * 0.04, TH * 0.80, TW * 0.30, TH * 0.93], fill=(0, 196, 170, 255))
    d.text((TW * 0.06, TH * 0.825), "ТЕХНО-ЭФИР", font=font("ArialBlack.ttf", 30), fill=(10, 30, 32, 255))
    d.text((TW * 0.32, TH * 0.826), "НЕЙРОСЕТИ: КТО ПОТЕРЯЕТ РАБОТУ ПЕРВЫМ", font=font("Arimo-Bold.ttf", 28), fill=(220, 255, 250, 255))
    _live(d, TW * 0.04, TH * 0.05, t, color=(0, 150, 130, 255), label="LIVE  19:40", fs=20)
    return img

@studio
def talk(t):
    """вечерний разговор: красно-чёрная студия, трое за столом"""
    def mk():
        img = _grad(TW, TH, (40, 8, 12), (120, 20, 30))
        d = ImageDraw.Draw(img)
        for i in range(12):
            d.rectangle([TW * (i * 0.085), 0, TW * (i * 0.085 + 0.012), TH], fill=(170, 40, 50, 120))
        d.rectangle([0, TH * 0.78, TW, TH], fill=(22, 10, 12, 255))
        return img
    img = _bg("talk", mk); d = ImageDraw.Draw(img)
    person(d, TW * 0.2, TH * 0.82, 84, (210, 170, 140, 255), (60, 40, 30, 255), (50, 20, 24, 255), t, 7, hair_kind="glasses")
    person(d, TW * 0.5, TH * 0.82, 90, (236, 200, 176, 255), (210, 190, 150, 255), (90, 20, 30, 255), t, 8, hair_kind="long")
    person(d, TW * 0.8, TH * 0.82, 84, (190, 150, 120, 255), (24, 20, 20, 255), (40, 40, 46, 255), t, 9, shirt=(220, 220, 224, 255))
    d.rectangle([0, TH * 0.82, TW, TH * 0.90], fill=(238, 232, 230, 255))
    d.polygon([(0, TH * 0.82), (TW * 0.3, TH * 0.82), (TW * 0.27, TH * 0.90), (0, TH * 0.90)], fill=(206, 20, 40, 255))
    d.text((TW * 0.02, TH * 0.833), "ВЕЧЕРНИЙ РАЗГОВОР", font=font("ArialBlack.ttf", 24), fill=(255, 255, 255, 255))
    d.text((TW * 0.31, TH * 0.833), "ПРОГНОЗ, КОТОРЫЙ РАЗДЕЛИЛ ЭКСПЕРТОВ", font=font("ArialBlack.ttf", 24), fill=(30, 20, 20, 255))
    ticker(img, "talk", ["ЗВОНКИ ЗРИТЕЛЕЙ ПОСЛЕ РЕКЛАМЫ", "ГОЛОСОВАНИЕ: ВЕРИТЕ ЛИ ВЫ ПРОГНОЗУ", "ДАЛЕЕ — ОБЗОР ПРЕССЫ"],
           t, TH * 0.90, TH * 0.10, 26, (255, 210, 210, 255), (12, 6, 8, 255), speed=120)
    return img

@studio
def remote(t):
    """прямое включение: гость из кабинета с книжной полкой, рамка видеозвонка"""
    def mk():
        img = _grad(TW, TH, (92, 96, 104), (60, 62, 70))
        d = ImageDraw.Draw(img)
        _bookshelf(d, TW, TH, TW * 0.55, TW * 0.98, TH * 0.06, TH * 0.70, 21)
        d.rectangle([TW * 0.0, TH * 0.06, TW * 0.5, TH * 0.70], fill=(126, 130, 138, 255))
        d.rectangle([TW * 0.08, TH * 0.10, TW * 0.42, TH * 0.44], fill=(190, 205, 225, 255))
        return img
    img = _bg("remote", mk); d = ImageDraw.Draw(img)
    person(d, TW * 0.5, TH * 0.86, 124, (226, 186, 156, 255), (90, 80, 76, 255), (70, 74, 90, 255), t, 10, shirt=(200, 220, 240, 255), hair_kind="glasses")
    d.rectangle([0, TH * 0.70, TW, TH], fill=(26, 28, 34, 255))
    d.rectangle([TW * 0.03, TH * 0.74, TW * 0.36, TH * 0.82], fill=(255, 196, 0, 255))
    d.text((TW * 0.05, TH * 0.75), "ПРЯМОЕ ВКЛЮЧЕНИЕ", font=font("ArialBlack.ttf", 24), fill=(20, 20, 24, 255))
    d.text((TW * 0.05, TH * 0.845), "ИГОРЬ САВИН · АНАЛИТИК РЫНКА ТРУДА", font=font("Arimo-Bold.ttf", 28), fill=(255, 255, 255, 255))
    d.text((TW * 0.05, TH * 0.915), "«ОНИ УЖЕ ЧИТАЮТ ДОГОВОРЫ ЛУЧШЕ ЮРИСТОВ»", font=font("Arimo-Bold.ttf", 24), fill=(180, 190, 210, 255))
    d.text((TW * 0.80, TH * 0.74), "КАНАЛ 7", font=font("ArialBlack.ttf", 26), fill=(255, 255, 255, 255))
    return img

@studio
def analytics(t):
    """аналитика: ведущий сбоку, на экране растущие столбцы"""
    def mk():
        img = _grad(TW, TH, (18, 20, 28), (40, 44, 60))
        d = ImageDraw.Draw(img)
        d.rectangle([TW * 0.40, TH * 0.08, TW * 0.96, TH * 0.74], fill=(28, 32, 44, 255), outline=(90, 100, 130, 255), width=3)
        for i in range(5):
            y = TH * (0.14 + i * 0.12)
            d.line([(TW * 0.44, y), (TW * 0.94, y)], fill=(60, 66, 86, 255), width=1)
        d.text((TW * 0.44, TH * 0.10), "ДОЛЯ ЗАДАЧ, ПЕРЕДАННЫХ ИИ", font=font("Arimo-Bold.ttf", 20), fill=(180, 190, 210, 255))
        return img
    img = _bg("analytics", mk); d = ImageDraw.Draw(img)
    person(d, TW * 0.2, TH * 0.82, 100, (198, 156, 126, 255), (36, 30, 28, 255), (34, 36, 48, 255), t, 11, shirt=(230, 230, 236, 255))
    vals = [0.25, 0.38, 0.52, 0.66, 0.86, 1.0]
    k = out_cubic(seg(t % 6.0, 0.2, 2.6))
    for i, v in enumerate(vals):
        x0 = TW * (0.46 + i * 0.08); hgt = TH * 0.52 * v * k
        col = (255, 196, 0, 255) if i == len(vals) - 1 else (90, 150, 240, 255)
        d.rectangle([x0, TH * 0.70 - hgt, x0 + TW * 0.05, TH * 0.70], fill=col)
        d.text((x0, TH * 0.705), f"'{21 + i}", font=font("Arimo-Bold.ttf", 16), fill=(170, 176, 190, 255))
    d.rectangle([0, TH * 0.82, TW, TH * 0.92], fill=(14, 16, 22, 255))
    d.rectangle([0, TH * 0.82, TW * 0.012, TH * 0.92], fill=(255, 196, 0, 255))
    d.text((TW * 0.03, TH * 0.835), "РЫНОК И ИИ", font=font("ArialBlack.ttf", 24), fill=(255, 196, 0, 255))
    d.text((TW * 0.26, TH * 0.835), "ЦИФРЫ, О КОТОРЫХ СПОРЯТ: СКОЛЬКО ПРОФЕССИЙ ЗАТРОНЕТ", font=font("Arimo-Bold.ttf", 24), fill=(235, 236, 240, 255))
    d.text((TW * 0.88, TH * 0.03), _clock(t, "21:05"), font=font("Oswald-Bold.ttf", 28), fill=(200, 206, 220, 255))
    return img

@studio
def world(t):
    """мир сегодня: оранжево-тёмная студия, точки-карта, ведущая"""
    def mk():
        img = _grad(TW, TH, (30, 18, 10), (90, 44, 14))
        d = ImageDraw.Draw(img)
        rng = np.random.default_rng(3)
        for i in range(260):
            x, y = rng.uniform(TW * 0.35, TW * 0.98), rng.uniform(TH * 0.08, TH * 0.66)
            if (math.sin(x * 0.02) + math.cos(y * 0.03)) > -0.4:
                d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 170, 80, 150))
        return img
    img = _bg("world", mk); d = ImageDraw.Draw(img)
    person(d, TW * 0.22, TH * 0.84, 108, (240, 206, 180, 255), (26, 20, 18, 255), (200, 60, 30, 255), t, 12, hair_kind="long")
    # мигающие точки событий
    for i, (fx, fy) in enumerate([(0.52, 0.30), (0.70, 0.22), (0.84, 0.40), (0.62, 0.52)]):
        r = 6 + 5 * abs(math.sin(t * 2.2 + i))
        d.ellipse([TW * fx - r, TH * fy - r, TW * fx + r, TH * fy + r], fill=(255, 230, 120, 255))
    d.polygon([(0, TH * 0.76), (TW * 0.42, TH * 0.76), (TW * 0.40, TH * 0.84), (0, TH * 0.84)], fill=(255, 150, 30, 255))
    d.text((TW * 0.02, TH * 0.77), "МИР СЕГОДНЯ", font=font("ArialBlack.ttf", 26), fill=(30, 16, 8, 255))
    d.rectangle([0, TH * 0.84, TW, TH * 0.92], fill=(250, 246, 240, 255))
    d.text((TW * 0.02, TH * 0.852), "ЗАГОЛОВКИ НЕДЕЛИ: ОДНА СТАТЬЯ — ВО ВСЕХ ЭФИРАХ", font=font("ArialBlack.ttf", 24), fill=(40, 24, 10, 255))
    ticker(img, "world", ["БИРЖИ АЗИИ ОТКРЫЛИСЬ РОСТОМ", "СОВЕТ ПО ИИ СОБЕРЁТСЯ В ЧЕТВЕРГ", "ПОГОДА: НОЧЬЮ ДО −4"],
           t, TH * 0.92, TH * 0.08, 24, (255, 220, 170, 255), (20, 12, 6, 255), speed=110)
    return img

def screen_tex(kind, t, lit=1.0):
    """панель целиком: чёрная рамка + эфир"""
    pic = STUDIOS[kind](t)
    bez = 14
    img = Image.new("RGBA", (TW + bez * 2, TH + bez * 2), (16, 16, 18, 255))
    ImageDraw.Draw(img).rectangle([3, 3, TW + bez * 2 - 4, TH + bez * 2 - 4], outline=(60, 60, 64, 255), width=2)
    if lit < 1.0:
        dark = Image.new("RGBA", (TW, TH), (8, 8, 10, int(255 * (1 - lit))))
        pic.alpha_composite(dark)
    img.alpha_composite(pic, (bez, bez))
    return img

# ---------------- расстановка стены ----------------
PW, PH = 1.65, 1.0          # метры (плёнка: ширина 0.20–0.27 кадра, высота 0.27–0.30)
POP = 1.2                   # момент, когда появляется вся стена (с)
# (x, y, z, yaw°, kind, когда) — ближний ряд z=7.0: ±1.3 и ±3.1 (просвет по центру, как в плёнке),
# дальний z=9.5: по центру и в боковых щелях
PANELS = [
    # две панели, которые висят с самого начала (в плёнке 5.4–7.9 с: дальняя по центру, ближняя правее)
    dict(x=0.0,  y=2.95, z=9.5, yaw=-7,  kind="biz",       on=0.0),
    dict(x=1.3,  y=2.90, z=7.0, yaw=-9,  kind="news",      on=0.0),
    # остальная стена — одним кадром
    dict(x=-3.1, y=2.90, z=7.0, yaw=12,  kind="talk",      on=POP),
    dict(x=-1.3, y=2.90, z=7.0, yaw=-5,  kind="morning",   on=POP),
    dict(x=3.1,  y=2.90, z=7.0, yaw=-13, kind="remote",    on=POP),
    dict(x=-2.2, y=2.95, z=9.5, yaw=10,  kind="tech",      on=POP),
    dict(x=2.2,  y=2.95, z=9.5, yaw=-8,  kind="analytics", on=POP),
    dict(x=4.6,  y=2.95, z=9.5, yaw=9,   kind="world",     on=POP),
]
ROLL = math.radians(-2.0)   # общий наклон сетки: левый край ниже

def hang_panel(img, cam, p, t):
    tex = screen_tex(p["kind"], t)
    c = quad((p["x"], p["y"], p["z"]), PW, PH, yaw=math.radians(p["yaw"]), roll=ROLL)
    tl, tr = c[0], c[1]
    for k in (0.12, 0.88):
        pt = (tl[0] + (tr[0] - tl[0]) * k, tl[1] + (tr[1] - tl[1]) * k, tl[2] + (tr[2] - tl[2]) * k)
        wire(img, cam, pt, color=(112, 114, 118, 230), width=2)
    extrude(img, cam, c, tex, depth=0.07, steps=3, shade=(26, 26, 28))

def g24(t):
    cam = Cam(z=0.15 * t)                     # камера почти стоит (плёнка 8–10 с)
    img = room(cam)
    vis = [p for p in PANELS if t >= p["on"]]
    vis.sort(key=lambda p: -p["z"])           # дальний ряд первым
    for p in vis:
        hang_panel(img, cam, p, t)
    return img

SCENES = {"G24": (g24, 4.5)}

def render(code, out):
    fn, dur = SCENES[code]
    n = int(dur * FPS)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = "ffmpeg"
    p = subprocess.Popen([exe, "-y", "-nostdin", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{Z.W}x{Z.H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                          "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                         stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(fn(i / FPS).convert("RGB").tobytes())
    p.stdin.close(); p.wait()
    print("готово:", out, n, "кадров")

if __name__ == "__main__":
    code = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else f"{code}.mp4"
    if os.environ.get("ZAL_FRAME"):
        t = float(os.environ["ZAL_FRAME"])
        SCENES[code][0](t).convert("RGB").save(out)
        print("кадр", t, "->", out)
    else:
        render(code, out)
