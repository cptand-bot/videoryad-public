# -*- coding: utf-8 -*-
"""ЧЕТЫРЕ СЦЕНЫ «БЕЛОГО ЗАЛА», ВТОРАЯ ПАЧКА (перенесены в бой 13.11).

ЧТО ЭТО. Продолжение `template/zal_scenes2.py`: тот же белый павильон, те же
правила, четыре ДРУГИХ приёма образца, утверждённых пользователем в песочнице
`~/zal-fable`. Каждый — целая сцена с объёмом, а не наклейка поверх кадра.

    zal_g01   G01  четыре плана и две склейки: табло со счётом на тросах →
                   пролёт сквозь облако висящих листов под объёмной фразой →
                   камера клюёт вниз, листы падают и ложатся на пол →
                   пустой зал: тёмные слова висят, ударные встают из пола
    zal_g48   G48  камера отъезжает, и зал оказывается КАРТИНОЙ В РАМЕ внутри
                   того же зала; под рамой плашка со счётчиком кадров, внутри
                   рамы кадр продолжает жить (камера едет, глобус крутится)
    zal_g44   G44  выноска со значением у точки шкалы: столб-шкала от пола до
                   потолка, уголь у основания, плашка со значением подлетает
                   справа-сверху с перелётом и дрожью и встаёт вплотную
    zal_g18   G18  большое число во весь кадр: значение на треть высоты,
                   пояснение вчетверо мельче, под ними лист-подтверждение с
                   маркером по словам; камера наезжает

ОТКУДА СНЯТО И ЧТО НЕ ТРОГАТЬ. Числа сняты с плёнки образца покадрово
(шарды `shard_fable_h.py` G01, `shard_fable_i.py` G48, `shard_fable_j.py`
G44 и G18). Пользователь запретил доводку этих приёмов прямым словом («не
будем больше её раскатывать»), поэтому ПЕРЕНЕСЕНЫ ОДИН В ОДИН: траектории
камеры (`g01_cam`, наезд G18, отъезд G48), времена склеек (1.0 · 4.333 у
G01), глубины объёма, наклоны (крен −7°, рыскание −8° у плашки G44),
тайминги слов (0.950 / 1.217 / 1.450 … у G44, 0.567 / 0.700 / 0.800 / 0.867
у маркера G18), ход перелёта `out_back(u, 2.6)` и затухающая дрожь
`exp(-e/0.10)·cos(2π·e/0.22)`. Менять их нельзя.

ЧТО ПАРАМЕТРИЗОВАНО. В песочнице содержание образца вписано в код прямо —
это демонстрация, и она ЦЕЛИКОМ ПО-АНГЛИЙСКИ («I WASN'T», «EXAGGERATING.»,
«IF ANYTHING...», «FAR», «ENOUGH.», «DAY 243», «IT'S HERE.», «ONE MORE
THING.», «I DIDN'T MAKE THIS VIDEO.», «FRAME», «LESS THAN ONE PERCENT…»,
«<1%», «70%», лист Fox News). В бою латиница на экране запрещена на всех
каналах, поэтому из кода убрано ВСЁ содержание: оно приходит полями задания
сцены, а запасной вариант берётся из `text`, а не из слов образца. Зашитыми
остались только геометрия зала и времена движений.

    text        фраза сцены — крупные слова (G01 планы B/C, G48 внутри рамы,
                G44 строки блока, G18 заголовок листа)
    na_polu     ударные слова, встающие из пола (G01), строка на полу (G48)
    kick        короткая вводная (G44 «до блока»), тёмные висящие слова (G01),
                ярлык листа (G18)
    accent      слово под маркером: G01 надпись на полу, G48 строка над рамой,
                G44/G18 маркер в строке
    value       число: табло G01, карточка G48, плашка выноски G44, крупное
                число G18
    value_sub   подпись к числу: нижняя строка табло G01, слово у основания
                шкалы G44, пояснение под числом G18
    sheets      строки листов: висящие листы G01, пояснение у шкалы G44,
                подстроки листа G18
    say         мелкий текст на больших листах G01
    author      подпись на листе G18

ГАММА ПРИХОДИТ ПО КАНАЛУ, в коде сцены не задаётся: акцент берётся через
`zal_scene.цвета` поверх `template/palitra.py` (ПЛАНЕТА — сталь, «5 МИНУТ» —
золото), ровно как в `zal_scenes2.py`. Жёлтый образца остаётся только там,
где канала в палитре нет.

ДВЕ ПРАВКИ ПОД КИРИЛЛИЦУ, И ОБЕ НЕ ПРО ДВИЖЕНИЕ.
  1. `COND_MIN`: сжатие по ширине у образца доходит до 0.74 — на латинице
     это узкий гротеск, на кириллице «Ш» и «Щ» слипаются в гребёнку. Ниже
     0.86 не сжимаем (та же константа, что `COND` в `zal_scenes2`).
  2. Ширина мерится шрифтом: русские слова длиннее английских, поэтому там,
     где образец ставил слова по фиксированным координатам (три тёмных и два
     ударных слова плана D у G01), они раскладываются ПО ИЗМЕРЕННОЙ ширине с
     зазором образца, а капитель ужимается, если строка не влезает в зал.
     Коротким словам это ничего не меняет — раскладка совпадает с образцом.

ДЛИТЕЛЬНОСТЬ. У каждого приёма своя длина на плёнке (G01 5,0 с · G48 4,0 с ·
G44 5,0 с · G18 4,5 с). Если сцене задан `dur`, таймлайн приёма
укладывается в него ПРОПОРЦИОНАЛЬНО (`_время`), а не обрезается: иначе
плашка не села бы, листы не упали, число не доехало, а прогон отчитался бы
успехом.

Возвращает RGB-кадр 1920×1080 — этого ждёт `style_cards.render_anim`.
Модуль самодостаточный: кроме `zal_core` и `zal_scene` (цвет канала и
разбивка фразы) ничего не импортирует, абсолютных путей не содержит и
работает на раннере, где рядом лежат только `zal_core.py`, `palitra.py`,
папка `fonts` и задание.
"""
import math
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as zc
from zal_core import (W, H, F, CEIL, WALL, FAR, clamp01, seg, out_back,
                      out_cubic, Cam, quad, paste_quad, room, wire, embers,
                      text_tex, word_tiles, maket_tex, font)
# ЦВЕТ КАНАЛА И РАЗБИВКУ ФРАЗЫ БЕРЁМ У ВИДА `zal`, А НЕ ПИШЕМ СВОИ — иначе
# источник цветов стал бы вторым, и правка палитры доезжала бы до части сцен.
import zal_scene as _zs

FONT_B = "Oswald-Bold.ttf"
FONT_A = "ArialBlack.ttf"
FONT_S = "Arimo-Bold.ttf"

CAP = 0.715                  # высота капители Arial Black в долях кегля
COND_MIN = 0.86              # ниже не сжимаем: кириллица слипается
INK = (22, 22, 24, 255)      # тёмные буквы образца
INK_SIDE = (58, 58, 60)
DARK = (30, 27, 26, 255)
DARK_SIDE = (16, 14, 13)

# БЕЗОПАСНАЯ ЗОНА (13.11, пункт 0-В, его слово): «не вылезут за кадр, ни
# вверх, ни вниз, ни справа, ни слева… и с учётом субтитров, потому что
# субтитры порой перекрывают надписи на вот этих карточках наших».
# Рамка 5% (96..1824 по ширине, 54..1026 по высоте) и запретная нижняя полоса
# субтитров 18% (ниже 885). Проверяет `template/safe_area.py`.
ПОЛЕ_X, ПОЛЕ_Y, SUB_Y = 96, 54, 886
ЗАПАС = 10                   # отступ от границы, чтобы OCR не ловил впритык
РАМКА = (ПОЛЕ_X + ЗАПАС, ПОЛЕ_Y + ЗАПАС, W - ПОЛЕ_X - ЗАПАС, SUB_Y - ЗАПАС)


def _коробка(cam, corners):
    """Экранная коробка четырёхугольника: (x0, y0, x1, y1)."""
    pts = [cam.proj(p) for p in corners]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _в_рамке(cam, corners, рамка=РАМКА):
    x0, y0, x1, y1 = _коробка(cam, corners)
    return (x0 >= рамка[0] and y0 >= рамка[1] and x1 <= рамка[2] and y1 <= рамка[3])


def _глубина_над_полосой(cam, граница=SUB_Y - ЗАПАС):
    """Минимальная ДАЛЬНОСТЬ от камеры, при которой линия пола на экране выше
    `граница`. Слово, стоящее на полу, нельзя поднять «в воздух» — его ставят
    ДАЛЬШЕ ПО ГЛУБИНЕ, и основание уходит вверх само (так же считает
    `_глубина_пола` у боевых приёмов в `zal_scenes2.py`)."""
    d = граница - H / 2.0
    if d <= 1.0:
        return 0.0
    return max(0.0, cam.y) * F / d


def _увести_по_x(cam, центр, w, h, yaw=0.0, рамка=РАМКА, шагов=3):
    """Сдвиг ВДОЛЬ X, пока надпись не войдёт в безопасную рамку по ширине.
    Для того, что стоит на полу: поднимать такое нельзя, а поперёк — можно.
    Русское слово длиннее английского («ЯНВАРЬ» против «FEB»), и образцовое
    место у основания шкалы уводило его за левую кромку на 4 px."""
    cx, cy, cz = центр
    for _ in range(шагов):
        x0, _y0, x1, _y1 = _коробка(cam, quad((cx, cy, cz), w, h, yaw=yaw))
        dz = max(0.3, cz - cam.z)
        if x0 < рамка[0]:
            cx += (рамка[0] - x0 + 2) * dz / F
        elif x1 > рамка[2]:
            cx -= (x1 - рамка[2] + 2) * dz / F
        else:
            break
    return (cx, cy, cz)


def _внутри_или_вон(cam, центр, w, h, yaw=0.0, шагов=3):
    """ПОЛОВИНЫ БУКВ В КАДРЕ НЕ БЫВАЕТ. Надпись, которая по ходу приёма уходит
    вверх из кадра, не должна зависать срезанной верхней кромкой: если её
    коробка ПЕРЕСЕКАЕТ кромку, дотолкиваем до полного ухода. Целиком внутри
    или целиком за кадром — третьего нет (дефект с облачной пробы 13.11:
    «стоит поперёк верха кадра и срезан примерно наполовину»)."""
    cx, cy, cz = центр
    for _ in range(шагов):
        x0, y0, x1, y1 = _коробка(cam, quad((cx, cy, cz), w, h, yaw=yaw))
        if y1 < 0 or y0 >= РАМКА[1]:
            break
        cy += (y1 + 6) * max(0.3, cz - cam.z) / F
    return (cx, cy, cz)


def _вписать_в_рамку(cam, центр, w, h, yaw=0.0, рамка=РАМКА, шагов=4):
    """Размер и место объекта, при которых его экранная коробка влезает в
    безопасную рамку: сперва ужимаем по ширине и высоте, потом сдвигаем вниз
    или вверх. Возвращает (центр, w, h). ХОД И ВРЕМЕНА НЕ ТРОГАЕТ — только
    размещение (пункт 0-В, 13.11)."""
    cx, cy, cz = центр
    for _ in range(шагов):
        x0, y0, x1, y1 = _коробка(cam, quad((cx, cy, cz), w, h, yaw=yaw))
        шир, выс = max(1.0, x1 - x0), max(1.0, y1 - y0)
        k = min(1.0, (рамка[2] - рамка[0]) / шир, (рамка[3] - рамка[1]) / выс)
        if k < 0.999:
            w, h = w * k, h * k
            continue
        dz = max(0.3, cz - cam.z)
        if y0 < рамка[1]:                       # ушло за верхнюю кромку — опускаем
            cy -= (рамка[1] - y0) * dz / F
        elif y1 > рамка[3]:                     # залезло в полосу субтитров
            cy += (y1 - рамка[3]) * dz / F
        else:
            break
    return (cx, cy, cz), w, h




# ---------------------------------------------------------------------------
# ГАММА, ТЕКСТ, ВРЕМЯ
# ---------------------------------------------------------------------------
def цвета(channel):
    """(акцент канала RGBA, чернила на нём RGBA). Один источник — палитра."""
    bg, fg, _d = _zs.цвета(channel)
    return bg, fg


def _тень_цвета(c, k=0.68):
    """Боковая грань объёма: тот же цвет, уведённый в тень."""
    return tuple(int(v * k) for v in c[:3])


def _строки(text, строк=2, знаков=18):
    """Фраза сцены → строки заглавными, рвём по словам (общий код с `zal`)."""
    return _zs.разбить(text, строк=строк, знаков=знаков)


def _слова(text, n=None):
    """Текст → список слов заглавными (первые n, если задано)."""
    ws = [w for w in str(text or "").upper().split() if w]
    return ws[:n] if n else ws


def _первый(*варианты):
    """Первый непустой из вариантов (аргумент сцены → запасной из `text`)."""
    for v in варианты:
        if isinstance(v, (list, tuple)):
            v = " ".join(str(x) for x in v if str(x).strip())
        s = str(v or "").strip()
        if s:
            return s
    return ""


def _маркер(слова, accent):
    """Индексы слов строки, попадающих в `accent` — их накроет маркер.

    Сверяем по СЛОВАМ, а не по подстроке: иначе «ЦЕНА» подсветила бы кусок
    слова «ЦЕНАМИ», и маркер лёг бы на половину буквы.
    """
    acc = _слова(accent)
    if not acc or not слова:
        return None
    чист = [w.strip(".,:;!?»«—-") for w in слова]
    acc = [w.strip(".,:;!?»«—-") for w in acc]
    n = len(acc)
    for i in range(len(чист) - n + 1):
        if чист[i:i + n] == acc:
            return set(range(i, i + n))
    return None


def _цифры(value, предел=4):
    """Значение → знаки для перекидного табло (цифры, %, <, пробел убран)."""
    s = re.sub(r"\s+", "", str(value or ""))
    s = "".join(ch for ch in s if ch.isdigit() or ch in "<>%+-,.")
    return s[:предел]


def _число_из(text):
    """Первое число во фразе — запасной вариант, когда `value` не задан."""
    m = re.search(r"\d[\d\s]*[%]?", str(text or ""))
    return re.sub(r"\s+", "", m.group(0)) if m else ""


def _ev(sfx, at, role):
    if sfx is not None:
        sfx.append({"at": round(float(at), 2), "role": role})


def _время(t, dur, полное):
    """`t` сцены → время приёма. Таймлайн приёма (`полное` секунд) кладётся
    в длительность сцены ПРОПОРЦИОНАЛЬНО, а не обрезается."""
    tt = float(t)
    if dur and float(dur) > 0.05:
        return tt * (полное / float(dur))
    return tt


def _старты(база, n, шаг_по_умолчанию=0.20):
    """Времена входа слов: у образца их ровно столько, сколько слов в его
    фразе. Русская фраза длиннее или короче — список обрезается или
    продолжается ШАГОМ ОБРАЗЦА, а не выдуманным."""
    б = [float(x) for x in база]
    if not б:
        return [0.0] * n
    if n <= len(б):
        return б[:n]
    шаг = (б[-1] - б[0]) / (len(б) - 1) if len(б) > 1 else шаг_по_умолчанию
    шаг = max(0.05, шаг)
    while len(б) < n:
        б.append(б[-1] + шаг)
    return б


def _знак(img, watermark):
    """Подпись канала в левом нижнем углу — как у остальных сцен зала."""
    if not watermark:
        return
    ImageDraw.Draw(img, "RGBA").text(
        # ЗНАК КАНАЛА — В СТОРОНЕ ОТ СОДЕРЖИМОГО (14.11, его слово по
        # сцене 4 дашборда 8791 и «это не только к этому каналу, ко
        # всем»): «почему она перекрывает записи? почему внахлёст?
        # нельзя как-то в стороне держать?». Знак стоял на 850 px
        # кеглем 25 — ровно там, где кончаются блоки и строки
        # приёмов, и сливался с ними. Опускаем к самой границе
        # субтитров и уменьшаем: своя полоса, чужого в ней нет.
        # ЗНАК УШЁЛ В ПРАВЫЙ ВЕРХНИЙ УГОЛ (14.11, он повторил дважды:
        # «она залазит на карточку… почему её нельзя сделать в
        # стороне?»). Внизу слева знак соседствовал с блоками,
        # строками и плитами приёмов — опускание и уменьшение
        # помогли мало. Правый верх у наших видов свободен: заголовок
        # идёт слева или по центру, содержимое начинается ниже.
        (W - ПОЛЕ_X - 150, ПОЛЕ_Y + 6), str(watermark), font=zc.font(FONT_S, 19),
        fill=(96, 98, 102, 255))


def _подпись_источника(img, text):
    """Строка источника внизу кадра (у образца — `source_line`).

    СПРАВА, а не слева, как в образце: слева внизу у этих приёмов стоят свои
    элементы (слово на полу у G44, знак канала у всех), и образцовое место
    (54, H−62) и клало строку прямо на них. Выше полосы субтитров (18 %).
    """
    if not text:
        return
    d = ImageDraw.Draw(img, "RGBA")
    f = zc.font(FONT_S, 25)
    tw = d.textlength(str(text), font=f)
    d.text((W - ПОЛЕ_X - tw, SUB_Y - 76), str(text), font=f, fill=(96, 98, 102, 255))


def _готово(img, out, watermark=""):
    _знак(img, watermark)
    im = img.convert("RGB")
    if out:
        im.save(out, quality=92)
        return out
    return im


# ---------------------------------------------------------------------------
# ОБЩИЕ ПОМОЩНИКИ ПРИЁМОВ (перенесены из шардов песочницы)
# ---------------------------------------------------------------------------
def smooth(u):
    u = clamp01(u)
    return u * u * (3 - 2 * u)


def lerp3(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def pop(t0, t, dur=0.10, k0=1.22):
    """Вход слова как на плёнке: первый кадр крупнее и прозрачнее, за три
    кадра садится. Возвращает (масштаб, непрозрачность) или None."""
    if t < t0 - 1e-6:
        return None
    u = seg(t, t0, t0 + dur)
    return k0 + (1.0 - k0) * out_cubic(u), 0.55 + 0.45 * clamp01(u * 2.2)


def visible(cam, corners, margin=0.35):
    return min(c[2] for c in corners) - cam.z > margin


def line_frame(center, yaw):
    """Оси строки: направление вдоль строки и нормаль от камеры."""
    return (math.cos(yaw), 0.0, math.sin(yaw)), (-math.sin(yaw), 0.0, math.cos(yaw))


def word_quad(center, ux, u, v, w, h):
    """Углы прямоугольника слова: центр строки + u вдоль строки, v вверх."""
    cx = center[0] + ux[0] * u
    cy = center[1] + v
    cz = center[2] + ux[2] * u
    hw, hh = w / 2, h / 2
    return [(cx - ux[0] * hw, cy + hh, cz - ux[2] * hw),
            (cx + ux[0] * hw, cy + hh, cz + ux[2] * hw),
            (cx + ux[0] * hw, cy - hh, cz + ux[2] * hw),
            (cx - ux[0] * hw, cy - hh, cz - ux[2] * hw)]


def extrude_dir(canvas, cam, corners, tex, depth, nz, steps=8, side=(96, 97, 100),
                floor_clip=False, opacity=1.0):
    """Объём вдоль произвольной нормали; `floor_clip` режет каждую копию по
    линии пола на её дальности (слово растёт из пола, а не всплывает)."""
    lay = canvas if not floor_clip else Image.new("RGBA", (W, H), (0, 0, 0, 0))
    alpha = tex.split()[3]
    p0 = cam.proj(corners[2])
    p1 = cam.proj((corners[2][0] + nz[0] * depth, corners[2][1],
                   corners[2][2] + nz[2] * depth))
    shift = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    steps = int(max(steps, min(48, shift / 2.5)))
    for i in range(steps, -1, -1):
        k = i / steps
        cs = [(c[0] + nz[0] * depth * k, c[1], c[2] + nz[2] * depth * k) for c in corners]
        if not visible(cam, cs):
            continue
        pts = [cam.proj(p) for p in cs]
        if i == 0:
            t = tex
        else:
            v = [int(side[j] * (0.78 + 0.22 * (1 - k))) for j in range(3)]
            t = Image.new("RGBA", tex.size, (v[0], v[1], v[2], 255))
            t.putalpha(alpha)
        if floor_clip:
            sub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            paste_quad(sub, t, pts, opacity)
            zcn = sum(c[2] for c in cs) / 4.0
            yf = H / 2 + cam.y * F / max(0.3, zcn - cam.z)
            yf = int(max(0, min(H, yf)))
            if yf < H:
                ImageDraw.Draw(sub).rectangle([0, yf, W, H], fill=(0, 0, 0, 0))
            lay.alpha_composite(sub)
        else:
            paste_quad(lay, t, pts, opacity)
    if floor_clip:
        canvas.alpha_composite(lay)


def text_shadow(canvas, cam, corners, tex, ux, off=(0.9, 0.0, 1.4), blur=14,
                strength=0.30):
    """Тень надписи на полу: верх букв уезжает по вектору `off`."""
    bl, br = corners[3], corners[2]
    k = corners[0][1] - corners[3][1]
    sh = [(bl[0] + off[0] * k, 0.012, bl[2] + off[2] * k),
          (br[0] + off[0] * k, 0.012, br[2] + off[2] * k),
          (br[0], 0.012, br[2]), (bl[0], 0.012, bl[2])]
    if not visible(cam, sh):
        return
    a = tex.split()[3].point(lambda v: int(v * strength))
    dark = Image.new("RGBA", tex.size, (38, 36, 34, 255))
    dark.putalpha(a)
    paste_quad(canvas, dark.filter(ImageFilter.GaussianBlur(blur)),
               [cam.proj(p) for p in sh])


def tiles_crop(lines, fsize, hl=None, color=DARK, vertical=False, fname=FONT_A,
               cond=0.80, hl_color=(255, 212, 0, 255)):
    """Плитки слов, обрезанные по контуру; (ширина, высота, [(плитка, cx, cy,
    базовая)]). `cond` — сжатие по ширине, не ниже `COND_MIN` (кириллица).
    `hl_color` — МАРКЕР ГАММЫ КАНАЛА: жёлтый образца остаётся только там, где
    канала в палитре нет."""
    cond = max(COND_MIN, float(cond)) if cond < 1.0 else float(cond)
    tw, th, tiles = word_tiles(lines, fsize=fsize, fname=fname, hl=hl, color=color,
                               hl_color=hl_color)
    out = []
    tw = tw * cond
    for tile, cx, cy in tiles:
        if cond != 1.0:
            tile = tile.resize((max(4, int(tile.size[0] * cond)), tile.size[1]),
                               Image.LANCZOS)
            cx = cx * cond
        bb = tile.getbbox()
        if bb is None:
            continue
        if vertical:
            cr = tile.crop(bb)
            out.append((cr, cx - tile.size[0] / 2 + (bb[0] + bb[2]) / 2,
                        cy - tile.size[1] / 2 + (bb[1] + bb[3]) / 2,
                        bb[3] + cy - tile.size[1] / 2))
        else:
            cr = tile.crop((bb[0], 0, bb[2], tile.size[1]))
            out.append((cr, cx - tile.size[0] / 2 + (bb[0] + bb[2]) / 2, cy, None))
    return tw, th, out


def place_words(img, cam, t, words, center, yaw, scale_m, starts, depth, side,
                hang=False, floor=False, shadow=False, floor_clip=False, rise=None,
                wire_per_word=1, extra_op=1.0, k0=1.22):
    """`words` — плитки `tiles_crop`; `scale_m` — метров на пиксель плитки;
    `starts` — время входа каждого слова."""
    tw, th, tiles = words
    ux, nz = line_frame(center, yaw)
    starts = _старты(starts, len(tiles))
    for i, (tile, cx, cy, _base) in enumerate(tiles):
        p = pop(starts[i], t, k0=k0)
        if p is None:
            continue
        s, op = p
        op *= extra_op
        w = tile.size[0] * scale_m * s
        h = tile.size[1] * scale_m * s
        u = (cx - tw / 2) * scale_m
        v = h / 2 if floor else (th / 2 - cy) * scale_m
        dy = 0.0
        if rise is not None:
            r0, rd = rise
            ur = seg(t, r0, r0 + rd)
            k = 1.0 - (1.0 - ur) ** 1.6
            k += 0.03 * math.sin(math.pi * seg(t, r0 + rd, r0 + rd + 0.1))
            dy = -(1.0 - k) * (tile.size[1] * scale_m) * 1.02
        c = word_quad((center[0], center[1] + dy, center[2]), ux, u, v, w, h)
        if not visible(cam, c):
            continue
        if shadow and dy > -0.02:
            text_shadow(img, cam, c, tile, ux)
        if hang:
            n = wire_per_word if tile.size[0] * scale_m > 0.45 else 1
            for j in range(n):
                f = (j + 0.5) / n
                top = (c[0][0] + (c[1][0] - c[0][0]) * f, c[0][1],
                       c[0][2] + (c[1][2] - c[0][2]) * f)
                wire(img, cam, top, color=(96, 98, 102, 230), width=2)
        if s > 1.08:                      # первый кадр входа — смазан по горизонтали
            for sh in (-0.05, 0.05):
                cc = word_quad((center[0] + sh * w * ux[0], center[1] + dy,
                                center[2] + sh * w * ux[2]), ux, u, v, w, h)
                paste_quad(img, tile, [cam.proj(q) for q in cc], 0.22)
        extrude_dir(img, cam, c, tile, depth, nz, steps=8, side=side,
                    floor_clip=floor_clip or rise is not None, opacity=op)


_CAPR = {}


def cap_ratio(fname):
    """Высота капители в долях кегля — мерим шрифтом, а не прикидываем."""
    if fname not in _CAPR:
        d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        b = d.textbbox((0, 0), "H", font=zc.font(fname, 200))
        _CAPR[fname] = (b[3] - b[1]) / 200.0
    return _CAPR[fname]


def words_block(lines, cap_m, fname=FONT_B, cond=1.0, hl=None, color=DARK,
                fsize=200, hl_color=(255, 212, 0, 255)):
    """Плитки строк + метров на пиксель, чтобы капитель была `cap_m`."""
    tiles = tiles_crop(lines, fsize, hl=hl, color=color, fname=fname, cond=cond,
                       hl_color=hl_color)
    return tiles, cap_m / (cap_ratio(fname) * fsize)


def _ужать(блок, предел_м):
    """Строка шире зала — ужимаем КАПИТЕЛЬ, а не рвём слова. Коротким строкам
    ничего не меняет: раскладка остаётся образцовой."""
    tiles, sc = блок
    ширина = tiles[0] * sc
    if ширина > предел_м > 0:
        sc = sc * предел_м / ширина
    return tiles, sc


def put_plate(img, cam, tex, center, w, h, yaw=0.0, roll=0.0, depth=0.08,
              side=(40, 40, 42), wires=None, opacity=1.0):
    """Плоская табличка в пространстве с объёмом вдоль нормали."""
    c = quad(center, w, h, yaw, roll)
    if not visible(cam, c, 0.25):
        return
    _ux, nz = line_frame(center, yaw)
    if wires:
        for f in wires:
            top = (c[0][0] + (c[1][0] - c[0][0]) * f,
                   c[0][1] + (c[1][1] - c[0][1]) * f,
                   c[0][2] + (c[1][2] - c[0][2]) * f)
            wire(img, cam, top, color=(96, 98, 102, 230), width=2)
    extrude_dir(img, cam, c, tex, depth, nz, steps=6, side=side, opacity=opacity)


def rope(img, cam, top, bottom, color=(96, 98, 102, 235), width=2):
    a = cam.proj(top)
    b = cam.proj(bottom)
    if a[2] < 0.3 or b[2] < 0.3:
        return
    ImageDraw.Draw(img, "RGBA").line([(a[0], a[1]), (b[0], b[1])], fill=color,
                                     width=width)


_SPR_CACHE = {}


def _spr(size):
    if size not in _SPR_CACHE:
        rgb, al = zc._sprite()
        s = np.array(Image.fromarray(rgb.astype(np.uint8)).resize((size, size),
                                                                  Image.BILINEAR), np.float32)
        a = np.array(Image.fromarray((al * 255).astype(np.uint8)).resize((size, size),
                                                                         Image.BILINEAR), np.float32) / 255.0
        _SPR_CACHE[size] = (s, a)
    return _SPR_CACHE[size]


def glow_spot(img, cam, pos, radius_m, strength=1.0, color=(255, 150, 48), core=0.22):
    """Пятно свечения: оранжевый ореол с квадратичным спадом и белое ядро."""
    px, py, dz = cam.proj(pos)
    if dz < 0.3:
        return img
    R = int(radius_m * F / dz)
    if R < 4:
        return img
    x0, y0 = int(px - R), int(py - R)
    X0, Y0 = max(0, x0), max(0, y0)
    X1, Y1 = min(W, x0 + 2 * R), min(H, y0 + 2 * R)
    if X1 <= X0 or Y1 <= Y0:
        return img
    yy, xx = np.mgrid[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    r = np.sqrt((xx - R) ** 2 + (yy - R) ** 2) / R
    fall = np.clip(1 - r, 0, 1) ** 2.2
    wht = np.clip(1 - r / core, 0, 1) ** 1.2
    arr = np.asarray(img.convert("RGB"), np.float32)
    sub = arr[Y0:Y1, X0:X1]
    col = np.array(color, np.float32)
    f = (fall * strength)[..., None]
    sub = sub * (1 - f) + col * f
    sub = sub * (1 - wht[..., None]) + np.array([255, 236, 200], np.float32) * wht[..., None]
    arr[Y0:Y1, X0:X1] = sub
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")


# ===========================================================================
# G01 · zal_g01 — ЧЕТЫРЕ ПЛАНА: ТАБЛО, ПРОЛЁТ СКВОЗЬ ЛИСТЫ, ПАДЕНИЕ, ПУСТОЙ ЗАЛ
# ===========================================================================
# Кусок 17.0-22.0 плёнки образца, две склейки (17.75→18.0 и 21.27→21.33):
#   A 0.00-1.00  табло на тросах, камера задрана (горизонт 78 %), повёрнута
#                влево ~8°, зал узкий: левая стена 2,6 м, правая 7,8 м.
#   B 1.00-3.20  пролёт сквозь облако висящих листов, две объёмные строки
#                входят на 1.30 и 1.80, растут 0,41 → 0,60 ширины кадра.
#   C 3.20-4.333 камера клюёт вниз (горизонт 17 %), листы падают и ЛЕЖАТ на
#                полу, плоская надпись над большим листом с 3.20.
#   D 4.333-5.00 пустой зал: тёмные слова ВИСЯТ (21.333 / 21.467 / 21.667),
#                ударные ПАДАЮТ на пол (21.62→21.73 и 21.85→21.94).
#   Свет — из окон левой стены, низко (наклон 1:4) и чуть вперёд.
G01_ПОЛНОЕ = 5.0
G01_HERO = 4.95

OK_W, OK_Y0, OK_Y1, OK_STEP, OK_COLS, OK_ROWS = 3.3, 1.5, 4.0, 4.7, 5, 5
SUN = (4.5, -1.0, 0.8)        # куда идёт луч из окна: вправо, вниз, вперёд
SHADOW = (5.0, -1.0, -0.9)    # тень слов на полу: вправо и чуть к камере


class CamP(Cam):
    """Та же камера, плюс наклон pitch (радианы, >0 — смотрит вверх)."""

    def __init__(s, x=0.0, y=1.55, z=0.0, yaw=0.0, pitch=0.0):
        Cam.__init__(s, x, y, z, yaw)
        s.pitch = pitch

    def proj(s, p):
        dx, dy, dz = p[0] - s.x, p[1] - s.y, p[2] - s.z
        if s.yaw:
            c, si = math.cos(-s.yaw), math.sin(-s.yaw)
            dx, dz = dx * c - dz * si, dx * si + dz * c
        if s.pitch:
            c, si = math.cos(s.pitch), math.sin(s.pitch)
            dy, dz = dy * c - dz * si, dy * si + dz * c
        if dz < 0.08:
            dz = 0.08
        k = F / dz
        return (W / 2 + dx * k, H / 2 - dy * k, dz)


class Hall:
    def __init__(s, xl, xr, zfar, ceil=5.2, okz0=3.0, okz0_r=5.5, slot_x=0.0,
                 corner_win=True, vid_l=25.0, vid_r=(0.0, 25.0)):
        s.xl, s.xr, s.zfar, s.ceil = xl, xr, zfar, ceil
        s.okz0, s.okz0_r, s.slot_x, s.corner_win = okz0, okz0_r, slot_x, corner_win
        s.vid_l, s.vid_r = vid_l, vid_r


HALL_A = Hall(-3.8, 5.5, 39.0, okz0=4.2, okz0_r=17.0, slot_x=4.1,
              corner_win=False, vid_l=25.0, vid_r=(0.0, 25.0))
HALL_D = Hall(-6.4, 18.0, 55.0, okz0=10.7, okz0_r=5.5, slot_x=0.0,
              corner_win=True, vid_l=25.0, vid_r=(35.0, 999.0))

_WALLTEX = {}


def wall_tex(bands):
    """Стена зала: свет из окон ложится мягкими косыми полосами."""
    if bands in _WALLTEX:
        return _WALLTEX[bands]
    w, h = 1240, 500
    img = Image.new("RGBA", (w, h), (225, 227, 230, 255))
    if bands:
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.polygon([(w * 0.45, 0), (w, 0), (w, h), (w * 0.70, h)],
                  fill=(246, 247, 248, 255))
        for i in range(5):
            x0 = w * 0.50 + i * 150
            d.polygon([(x0, 0), (x0 + 26, 0), (x0 + 26 - 150, h), (x0 - 150, h)],
                      fill=(212, 213, 215, 255))
        img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(22)))
        d = ImageDraw.Draw(img)
        rng = np.random.default_rng(11)
        for i in range(6):
            x = float(rng.uniform(w * 0.3, w))
            d.line([(x, 0), (x - 50, h)], fill=(216, 217, 219, 255), width=1)
    _WALLTEX[bands] = img
    return img


def far_wall(img, cam, z, dark=0.0, bands=False, slot=True, slot_color=None):
    """Дальняя стена зала во всю ширину; `slot` — полоса-проём в точке схода."""
    tex = wall_tex(bands)
    if dark > 0:
        k = clamp01(dark)
        arr = np.asarray(tex, np.float32)
        arr[..., :3] = arr[..., :3] * (1 - 0.80 * k) + np.array([10, 9, 8], np.float32) * (0.80 * k)
        tex = Image.fromarray(arr.astype(np.uint8))
    c = [(-WALL, CEIL, z), (WALL, CEIL, z), (WALL, 0.0, z), (-WALL, 0.0, z)]
    paste_quad(img, tex, [cam.proj(p) for p in c])
    if slot:
        акцент = slot_color or (236, 190, 48, 255)
        st = Image.new("RGBA", (40, 120),
                       lerp3(акцент, (120, 92, 20), clamp01(dark)) + (255,))
        c = [(-0.42, 2.4, z - 0.01), (0.42, 2.4, z - 0.01),
             (0.42, 0.0, z - 0.01), (-0.42, 0.0, z - 0.01)]
        paste_quad(img, st, [cam.proj(p) for p in c])
        zc.reflection(img, cam, c, st, strength=0.45)


def beams(img, cam, z0, z1, step=2.6):
    """Потолочные балки: светлые полосы поперёк зала."""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    z = math.floor(z0 / step) * step
    while z < z1:
        if z - cam.z > 1.2:
            p = [cam.proj((-WALL, CEIL, z)), cam.proj((WALL, CEIL, z)),
                 cam.proj((WALL, CEIL, z + 0.5)), cam.proj((-WALL, CEIL, z + 0.5))]
            d.polygon([(q[0], q[1]) for q in p], fill=(243, 244, 246, 255))
            a = cam.proj((-WALL, CEIL, z + 0.5))
            b = cam.proj((WALL, CEIL, z + 0.5))
            d.line([(a[0], a[1]), (b[0], b[1])], fill=(224, 226, 230, 255), width=1)
        z += step
    img.alpha_composite(lay)


def floor_mirror(img, cam, zmax, strength=0.28):
    """Пол как мягкое зеркало: окна отражаются вниз размытыми пятнами."""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    z0 = math.floor((cam.z + 3) / 7.0) * 7.0
    for i in range(10):
        zz = z0 + i * 7.0
        if zz > zmax - 3.1:
            break
        for sx in (-1, 1):
            p = [cam.proj((sx * WALL, -1.15, zz)), cam.proj((sx * WALL, -1.15, zz + 3.1)),
                 cam.proj((sx * WALL, -2.7, zz + 3.1)), cam.proj((sx * WALL, -2.7, zz))]
            d.polygon([(q[0], q[1]) for q in p], fill=(255, 255, 255, int(255 * strength)))
    img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(26)))


def extra_ropes(img, cam, n=40, seed=3, zspan=60.0, zmax=None):
    """Десятки тонких тросов на разной высоте — без них кадр пустой."""
    rng = np.random.default_rng(seed)
    d = ImageDraw.Draw(img, "RGBA")
    base = math.floor(cam.z / 3.0) * 3.0
    for i in range(n):
        zz = base + float(rng.uniform(1.5, zspan))
        if zmax is not None and zz > zmax - 0.5:
            continue
        xx = float(rng.uniform(-5.4, 5.4))
        yy = float(rng.uniform(0.6, 3.2))
        if zz - cam.z < 1.2:
            continue
        a = cam.proj((xx, CEIL, zz))
        b = cam.proj((xx, yy, zz))
        far = clamp01((zz - cam.z) / 40.0)
        col = lerp3((132, 134, 138), (190, 192, 196), far)
        d.line([(a[0], a[1]), (b[0], b[1])], fill=col + (235,),
               width=1 if far > 0.3 else 2)


def room_p(cam, windows=True, dark=0.0, shafts=True, ropes=True):
    """Тот же зал, что `zal_core.room`, с ОДНОЙ правкой: линия горизонта
    берётся из проекции, а не прибита к центру кадра (у `CamP` есть pitch,
    горизонт уезжает — иначе пол рисуется поверх стен и потолка)."""
    g = Image.new("L", (1, H))
    for y in range(H):
        t = y / H
        g.putpixel((0, y), int(234 - 24 * abs(t - 0.5) * 2))
    base = g.resize((W, H))
    img = Image.merge("RGBA", (base, base, base.point(lambda v: min(255, v + 3)),
                               Image.new("L", (W, H), 255)))
    d = ImageDraw.Draw(img, "RGBA")
    hor = cam.proj((0.0, cam.y, cam.z + 1e5))[1]
    d.rectangle([0, hor, W, H], fill=(211, 214, 218, 255))
    d.rectangle([0, 0, W, hor], fill=(230, 232, 235, 255))
    for sx in (-1, 1):
        p = [cam.proj((sx * WALL, CEIL, cam.z + 2.0)),
             cam.proj((sx * WALL, CEIL, cam.z + FAR)),
             cam.proj((sx * WALL, 0.0, cam.z + FAR)),
             cam.proj((sx * WALL, 0.0, cam.z + 2.0))]
        zc._poly(d, p, (222, 225, 229, 255))
    if windows:
        z0 = math.floor((cam.z + 3) / 7.0) * 7.0
        for i in range(10):
            zz = z0 + i * 7.0
            for sx in (-1, 1):
                p = [cam.proj((sx * WALL, 3.75, zz)), cam.proj((sx * WALL, 3.75, zz + 3.1)),
                     cam.proj((sx * WALL, 1.15, zz + 3.1)), cam.proj((sx * WALL, 1.15, zz))]
                zc._poly(d, p, (251, 252, 253, 255))
                for k in range(1, 4):
                    yy = 1.15 + 2.6 * k / 4
                    a = cam.proj((sx * WALL, yy, zz))
                    b = cam.proj((sx * WALL, yy, zz + 3.1))
                    d.line([(a[0], a[1]), (b[0], b[1])], fill=(226, 229, 233, 255), width=2)
    if shafts:
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dl = ImageDraw.Draw(lay, "RGBA")
        z0 = math.floor((cam.z + 3) / 7.0) * 7.0
        for i in range(9):
            zz = z0 + i * 7.0
            for sx in (-1, 1):
                p = [cam.proj((sx * (WALL - 0.2), 0.0, zz + 0.6)),
                     cam.proj((sx * (WALL - 0.2), 0.0, zz + 3.5)),
                     cam.proj((sx * (WALL - 3.4), 0.0, zz + 5.2)),
                     cam.proj((sx * (WALL - 3.4), 0.0, zz + 2.3))]
                dl.polygon([(q[0], q[1]) for q in p], fill=(255, 255, 255, 120))
        img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(9)))
    if ropes:
        rng = np.random.default_rng(5)
        dr = ImageDraw.Draw(img, "RGBA")
        z0 = math.floor((cam.z + 4) / 3.0) * 3.0
        for i in range(26):
            zz = z0 + (i % 13) * 3.0 + float(rng.uniform(-1.0, 1.0))
            xx = float(rng.uniform(-4.6, 4.6))
            yy = float(rng.uniform(0.9, 2.4))
            if zz - cam.z < 1.5:
                continue
            a = cam.proj((xx, CEIL, zz))
            b = cam.proj((xx, yy, zz))
            dr.line([(a[0], a[1]), (b[0], b[1])], fill=(150, 152, 156, 255), width=1)
    if dark > 0:
        img.alpha_composite(Image.new("RGBA", (W, H), (8, 7, 6, int(235 * clamp01(dark)))))
    return img


def _okna(hall, side):
    """Список окон стены: (z0, z1); левая стена может иметь окно у угла."""
    z0 = hall.okz0 if side < 0 else hall.okz0_r
    out = []
    zz = z0
    while zz < hall.zfar - 0.3:
        z1 = min(zz + OK_W, hall.zfar - 0.1)
        if z1 - zz > 1.0:
            out.append((zz, z1))
        zz += OK_STEP
    if side < 0 and hall.corner_win:
        zk = hall.zfar - 2.2
        if not out or out[-1][1] < zk - 0.5:
            out.append((zk, hall.zfar - 0.1))
    return out


def _sun_hit(hall, p):
    """Точка на окне левой стены → куда ложится луч: пол, дальняя или правая
    стена. Возвращает (поверхность, точка)."""
    x, y, z = p
    sx, sy, sz = SUN
    best = None
    for surf, tt in (("floor", y / -sy if sy < 0 else None),
                     ("far", (hall.zfar - z) / sz if sz > 0 else None),
                     ("right", (hall.xr - x) / sx if sx > 0 else None)):
        if tt is None or tt < 0:
            continue
        if best is None or tt < best[1]:
            best = (surf, tt)
    surf, tt = best
    return surf, (x + sx * tt, y + sy * tt, z + sz * tt)


def zal2(cam, hall=HALL_D, ropes=8, акцент=(236, 190, 48, 255)):
    """Зал по кадрам плёнки: стены на `hall.xl`/`hall.xr`, дальняя стена, окна
    с переплётом 5×5 в нишах, бетонный пол, потолок с глубокими балками, косые
    пятна солнца от окон левой стены, проём 1,0×2,75 м на дальней стене
    (гамма — канальная). Горизонт берётся ИЗ ПРОЕКЦИИ."""
    img = Image.new("RGBA", (W, H), (226, 226, 226, 255))
    d = ImageDraw.Draw(img, "RGBA")
    hor = cam.proj((cam.x, cam.y, cam.z + 1e5))[1]
    xl, xr, zf, ce = hall.xl, hall.xr, hall.zfar, hall.ceil
    zn = cam.z + 0.3

    y0 = int(max(0, min(H, hor)))
    if y0 < H:
        g = Image.new("RGBA", (1, H - y0))
        for y in range(H - y0):
            k = (y / max(1, H - y0)) ** 0.55
            g.putpixel((0, y), lerp3((186, 182, 176), (128, 123, 117), k) + (255,))
        img.alpha_composite(g.resize((W, H - y0)), (0, y0))
    for i in range(40):
        zz = math.floor(cam.z / 3.0) * 3.0 + i * 3.0
        if zz < zn or zz > zf:
            continue
        a = cam.proj((xl, 0.0, zz))
        b = cam.proj((xr, 0.0, zz))
        far = clamp01((zz - cam.z) / 30.0)
        d.line([(a[0], a[1]), (b[0], b[1])], fill=(112, 108, 103, int(110 * (1 - far))),
               width=1)
    xx = math.floor(xl / 3.0) * 3.0
    while xx < xr:
        if xx > xl + 0.2:
            a = cam.proj((xx, 0.0, zn + 0.3))
            b = cam.proj((xx, 0.0, zf))
            d.line([(a[0], a[1]), (b[0], b[1])], fill=(112, 108, 103, 70), width=1)
        xx += 3.0

    zc._poly(d, [cam.proj((xl, ce, zn)), cam.proj((xr, ce, zn)),
                 cam.proj((xr, ce, zf)), cam.proj((xl, ce, zf))], (176, 176, 177, 255))
    zz = math.floor(cam.z / 1.5) * 1.5
    balki = []
    while zz < zf:
        if zz > zn:
            balki.append(zz)
        zz += 1.5
    for zz in reversed(balki):
        far = clamp01((zz - cam.z) / 40.0)
        front = lerp3((222, 222, 223), (210, 210, 211), far) + (255,)
        low = lerp3((246, 246, 246), (232, 232, 232), far) + (255,)
        zc._poly(d, [cam.proj((xl, ce, zz)), cam.proj((xr, ce, zz)),
                     cam.proj((xr, ce - 0.35, zz)), cam.proj((xl, ce - 0.35, zz))], front)
        zc._poly(d, [cam.proj((xl, ce - 0.35, zz)), cam.proj((xr, ce - 0.35, zz)),
                     cam.proj((xr, ce - 0.35, zz + 0.3)),
                     cam.proj((xl, ce - 0.35, zz + 0.3))], low)

    for xw, col in ((xl, (229, 229, 228)), (xr, (222, 222, 221))):
        zc._poly(d, [cam.proj((xw, ce, zn)), cam.proj((xw, ce, zf)),
                     cam.proj((xw, 0.0, zf)), cam.proj((xw, 0.0, zn))], col + (255,))
    zc._poly(d, [cam.proj((xl, ce, zf)), cam.proj((xr, ce, zf)),
                 cam.proj((xr, 0.0, zf)), cam.proj((xl, 0.0, zf))], (212, 211, 209, 255))

    for side, xw in ((-1, xl), (1, xr)):
        for (z0, z1) in _okna(hall, side):
            if z1 < zn + 0.5:
                continue
            if side < 0 and z0 > cam.z + hall.vid_l:
                continue
            if side > 0 and not (hall.vid_r[0] <= z0 - cam.z <= hall.vid_r[1]):
                continue
            zq0, zq1 = max(z0, zn), z1
            n = [cam.proj((xw, OK_Y1 + 0.15, zq0 - 0.15)),
                 cam.proj((xw, OK_Y1 + 0.15, zq1 + 0.15)),
                 cam.proj((xw, OK_Y0 - 0.15, zq1 + 0.15)),
                 cam.proj((xw, OK_Y0 - 0.15, zq0 - 0.15))]
            zc._poly(d, n, (168, 168, 170, 255))
            p = [cam.proj((xw, OK_Y1, zq0)), cam.proj((xw, OK_Y1, zq1)),
                 cam.proj((xw, OK_Y0, zq1)), cam.proj((xw, OK_Y0, zq0))]
            zc._poly(d, p, (253, 253, 251, 255))
            px = abs(p[2][1] - p[1][1]) / (OK_Y1 - OK_Y0)
            wl = max(1, int(px * 0.03))
            d.line([(q[0], q[1]) for q in p] + [(p[0][0], p[0][1])],
                   fill=(84, 84, 86, 255), width=wl)
            for k in range(1, OK_ROWS):
                yy = OK_Y0 + (OK_Y1 - OK_Y0) * k / OK_ROWS
                a = cam.proj((xw, yy, zq0))
                b = cam.proj((xw, yy, zq1))
                d.line([(a[0], a[1]), (b[0], b[1])], fill=(84, 84, 86, 255), width=wl)
            for k in range(1, OK_COLS):
                zk = z0 + (z1 - z0) * k / OK_COLS
                if zk < zq0:
                    continue
                a = cam.proj((xw, OK_Y1, zk))
                b = cam.proj((xw, OK_Y0, zk))
                d.line([(a[0], a[1]), (b[0], b[1])], fill=(84, 84, 86, 255), width=wl)

    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl = ImageDraw.Draw(lay, "RGBA")
    for (z0, z1) in _okna(hall, -1):
        if z0 < cam.z + 14.0:
            continue
        a_fl = int(30 + 120 * clamp01((z0 - cam.z - 20.0) / 20.0))
        whole = [_sun_hit(hall, (xl, OK_Y1, z0)), _sun_hit(hall, (xl, OK_Y1, z1)),
                 _sun_hit(hall, (xl, OK_Y0, z1)), _sun_hit(hall, (xl, OK_Y0, z0))]
        if all(h[0] == "floor" for h in whole):
            pts = [h[1] for h in whole]
            if min(p[2] for p in pts) > zn + 0.2:
                dl.polygon([(q[0], q[1]) for q in (cam.proj(p) for p in pts)],
                           fill=(255, 254, 246, a_fl))
            continue
        for i in range(OK_COLS):
            for j in range(OK_ROWS):
                za, zb = z0 + (z1 - z0) * i / OK_COLS, z0 + (z1 - z0) * (i + 1) / OK_COLS
                ya, yb = (OK_Y0 + (OK_Y1 - OK_Y0) * j / OK_ROWS,
                          OK_Y0 + (OK_Y1 - OK_Y0) * (j + 1) / OK_ROWS)
                sh = 0.06
                hits = [_sun_hit(hall, (xl, yb - sh, za + sh)),
                        _sun_hit(hall, (xl, yb - sh, zb - sh)),
                        _sun_hit(hall, (xl, ya + sh, zb - sh)),
                        _sun_hit(hall, (xl, ya + sh, za + sh))]
                if len(set(h[0] for h in hits)) != 1:
                    continue
                pts = [h[1] for h in hits]
                if min(p[2] for p in pts) < zn + 0.2:
                    continue
                pr = [cam.proj(p) for p in pts]
                alpha = 150 if hits[0][0] == "floor" else 200
                dl.polygon([(q[0], q[1]) for q in pr], fill=(255, 254, 246, alpha))
    img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(2)))

    sx = hall.slot_x
    zc._poly(d, [cam.proj((sx - 0.5, 2.75, zf - 0.05)),
                 cam.proj((sx + 0.5, 2.75, zf - 0.05)),
                 cam.proj((sx + 0.5, 0.0, zf - 0.05)),
                 cam.proj((sx - 0.5, 0.0, zf - 0.05))], tuple(акцент))

    if ropes:
        rng = np.random.default_rng(3)
        for i in range(ropes):
            zz = float(rng.uniform(4.0, 34.0)) + math.floor(cam.z / 4.0) * 4.0
            xx = float(rng.uniform(xl + 0.5, min(xr - 0.5, xl + 12.0)))
            yy = float(rng.uniform(1.0, 3.4))
            if zz - cam.z < 1.2 or zz > zf - 1:
                continue
            a = cam.proj((xx, ce, zz))
            b = cam.proj((xx, yy, zz))
            far = clamp01((zz - cam.z) / 40.0)
            d.line([(a[0], a[1]), (b[0], b[1])],
                   fill=lerp3((70, 70, 72), (160, 160, 162), far) + (235,), width=1)
    return img


_TEXT_TEX = {}


def slovo_tex(slovo, cvet, kegl=320, stretch=1.0):
    """Текстура лицевой грани слова (прозрачный фон)."""
    key = (slovo, tuple(cvet), kegl, round(stretch, 3))
    if key in _TEXT_TEX:
        return _TEXT_TEX[key]
    if len(_TEXT_TEX) > 48:
        _TEXT_TEX.clear()
    fnt = zc.font(FONT_B, kegl)
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    bb = tmp.textbbox((0, 0), slovo, font=fnt)
    tw, th = max(1, bb[2] - bb[0]), max(1, bb[3] - bb[1])
    im = Image.new("RGBA", (tw + 8, th + 8), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((4 - bb[0], 4 - bb[1]), slovo, font=fnt,
                            fill=tuple(cvet[:3]) + (255,))
    if stretch != 1.0:
        im = im.resize((max(4, int(im.width * stretch)), im.height), Image.LANCZOS)
    _TEXT_TEX[key] = im
    return im


def obyom(canvas, cam, corners, tex, depth, side, steps=10, skos=(0.05, -0.30)):
    """Объёмное слово: лицевая грань на corners, бока уходят в глубину +z и
    вниз-вправо (на плёнке у каждой буквы тёмный низ)."""
    cap = abs(corners[0][1] - corners[3][1])
    for i in range(steps, 0, -1):
        k = i / steps
        cs = [(c[0] + skos[0] * cap * k, c[1] + skos[1] * cap * k, c[2] + depth * k)
              for c in corners]
        solid = Image.new("RGBA", tex.size, tuple(side[:3]) + (255,))
        solid.putalpha(tex.split()[3])
        paste_quad(canvas, solid, [cam.proj(p) for p in cs])
    paste_quad(canvas, tex, [cam.proj(p) for p in corners])


def _ширина_слова(slovo, cap, stretch=1.0):
    tex = slovo_tex(slovo, (0, 0, 0), stretch=stretch)
    return cap * tex.width / tex.height


def _cap_fit(slovo, cap, предел_м, stretch=1.0):
    """Капитель, при которой слово не шире `предел_м`. Коротким словам
    образца ничего не меняет."""
    w = _ширина_слова(slovo, cap, stretch)
    return cap * предел_м / w if w > предел_м > 0 else cap


def slovo_visit(canvas, cam, slovo, x, y, z, cap, cvet, side, k=1.0, depth=0.22,
                tros=True, stretch=1.0):
    """Слово ВИСИТ на тросе, центр (x, y, z); k — выскок (out_back)."""
    if k <= 0.001 or not slovo:
        return
    tex = slovo_tex(slovo, cvet, stretch=stretch)
    w = cap * tex.width / tex.height
    s = out_back(k)
    hw, hh = w * s / 2, cap * s / 2
    c = [(x - hw, y + hh, z), (x + hw, y + hh, z), (x + hw, y - hh, z), (x - hw, y - hh, z)]
    if tros:
        d = ImageDraw.Draw(canvas, "RGBA")
        a = cam.proj((x, cam.y + 20.0, z))
        b = cam.proj((x, y + hh, z))
        d.line([(a[0], a[1]), (b[0], b[1])], fill=(64, 64, 66, 235), width=2)
    obyom(canvas, cam, c, tex, depth, side)


def slovo_iz_pola(canvas, cam, slovo, x, z, cap, cvet, side, k, depth=0.30,
                  stretch=1.0):
    """Слово ПАДАЕТ на пол и встаёт на него: k=0 — ещё в 1,2 м над полом,
    k=1 — стоит. Ход — квадрат (как при падении), тень по лучу SHADOW."""
    if k <= 0.001 or not slovo:
        return
    tex = slovo_tex(slovo, cvet, stretch=stretch)
    w = cap * tex.width / tex.height
    u = clamp01(k)
    lift = 1.2 * (1.0 - u) ** 2
    c = [(x - w / 2, lift + cap, z), (x + w / 2, lift + cap, z),
         (x + w / 2, lift, z), (x - w / 2, lift, z)]
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if u > 0.05:
        hgt = cap
        sx, sy, sz = SHADOW
        sh = [(x - w / 2 + sx * hgt, 0.01, z + sz * hgt),
              (x + w / 2 + sx * hgt, 0.01, z + sz * hgt),
              (x + w / 2, 0.01, z), (x - w / 2, 0.01, z)]
        a = tex.split()[3].point(lambda v: int(v * 0.72 * u))
        dark = Image.new("RGBA", tex.size, (48, 44, 38, 255))
        dark.putalpha(a)
        paste_quad(canvas, dark.filter(ImageFilter.GaussianBlur(4)),
                   [cam.proj(p) for p in sh])
    obyom(lay, cam, c, tex, depth, side)
    fl = cam.proj((x - w / 2, -0.12 * cap, z))
    fr_ = cam.proj((x + w / 2, -0.12 * cap, z))
    xs0, xs1 = min(fl[0], fr_[0]) - 50, max(fl[0], fr_[0]) + 50
    ImageDraw.Draw(lay).polygon([(xs0, fl[1]), (xs1, fr_[1]), (xs1, H + 10),
                                 (xs0, H + 10)], fill=(0, 0, 0, 0))
    canvas.alpha_composite(lay)


def _ряд_слов(слова, caps, x0, зазор, предел_м, stretch=1.0):
    """Слова в ряд ПО ИЗМЕРЕННОЙ ширине: у образца они стояли по фиксированным
    координатам, и русские слова налезали бы друг на друга. Левый край
    первого слова и зазор — образцовые, капитель ужимается, если ряд не
    влезает в `предел_м`. Возвращает [(слово, x центра, cap)]."""
    if not слова:
        return []
    caps = list(caps) + [caps[-1]] * (len(слова) - len(caps))
    ширины = [_ширина_слова(w, caps[i], stretch) for i, w in enumerate(слова)]
    всего = sum(ширины) + зазор * (len(слова) - 1)
    k = предел_м / всего if всего > предел_м > 0 else 1.0
    out = []
    x = x0
    for i, w in enumerate(слова):
        ww = ширины[i] * k
        out.append((w, x + ww / 2.0, caps[i] * k))
        x += ww + зазор * k
    return out


_LIST_TEX = {}


def post_tex(ключ, строки, подпись, мелко, w_px=640, h_px=420, bold=42):
    """Лист: жирный заголовок, строка-подпись, мелкий серый текст. Содержание
    приходит из `sheets`/`say`, а не из постов образца."""
    key = (ключ, w_px, h_px, bold, bool(мелко))
    if key in _LIST_TEX:
        return _LIST_TEX[key]
    if len(_LIST_TEX) > 64:
        _LIST_TEX.clear()
    im = Image.new("RGBA", (w_px, h_px), (250, 250, 248, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w_px - 1, h_px - 1], outline=(222, 222, 220, 255), width=2)
    fb = zc.font(FONT_B, bold)
    fs = zc.font(FONT_S, max(10, int(bold * 0.32)))
    ft = zc.font(FONT_S, max(9, int(bold * 0.30)))
    x0 = int(bold * 0.6)
    y = int(bold * 0.6)
    for ln in строки:
        слова, тек = str(ln).split(), ""
        for wd in слова:
            проба = (тек + " " + wd).strip()
            if d.textlength(проба, font=fb) > w_px - 2 * x0 and тек:
                d.text((x0, y), тек, font=fb, fill=(24, 24, 26, 255))
                y += int(bold * 1.05)
                тек = wd
            else:
                тек = проба
        if тек:
            d.text((x0, y), тек, font=fb, fill=(24, 24, 26, 255))
            y += int(bold * 1.05)
    y += int(bold * 0.2)
    if подпись:
        d.text((x0, y), str(подпись), font=fs, fill=(120, 120, 124, 255))
        y += int(bold * 0.7)
    if мелко:
        слова = str(мелко).split()
        ln = ""
        while y < h_px - bold and слова:
            wd = слова.pop(0)
            if d.textlength(ln + " " + wd, font=ft) > w_px - 2 * x0 and ln:
                d.text((x0, y), ln, font=ft, fill=(96, 96, 100, 255))
                y += int(bold * 0.42)
                ln = wd
            else:
                ln = (ln + " " + wd).strip()
        if ln and y < h_px - bold:
            d.text((x0, y), ln, font=ft, fill=(96, 96, 100, 255))
    _LIST_TEX[key] = im
    return im


# (x, z) — где лист ЛЯЖЕТ на пол; y_h — высота центра, пока висит
LISTY = [
    dict(x=-2.2, z=10.7, y_h=2.4, w=6.2, h=4.4, i=2, body=True, big=True),
    dict(x=-2.4, z=4.9, y_h=1.3, w=1.0, h=1.3, i=3),
    dict(x=-2.0, z=6.4, y_h=2.9, w=0.85, h=1.2, i=0),
    dict(x=0.5, z=6.1, y_h=1.9, w=1.0, h=2.3, i=5),
    dict(x=0.1, z=8.5, y_h=3.1, w=0.8, h=1.6, i=4),
    dict(x=-1.0, z=9.1, y_h=1.6, w=0.6, h=1.0, i=1),
    dict(x=-3.9, z=0.2, y_h=3.1, w=1.5, h=1.0, i=0),
    dict(x=-0.2, z=0.6, y_h=3.3, w=1.4, h=0.9, i=1),
    dict(x=1.2, z=1.0, y_h=2.9, w=1.6, h=1.1, i=2, body=True),
    dict(x=-4.3, z=1.3, y_h=1.2, w=1.6, h=1.1, i=4, body=True),
    dict(x=-2.3, z=2.5, y_h=2.4, w=1.9, h=1.3, i=2, body=True),
    dict(x=0.9, z=1.9, y_h=1.1, w=1.4, h=0.9, i=5),
    dict(x=-3.0, z=2.2, y_h=0.9, w=1.3, h=0.9, i=3),
    dict(x=-0.9, z=2.4, y_h=1.4, w=1.2, h=0.8, i=4),
    dict(x=-4.8, z=2.5, y_h=2.5, w=1.2, h=0.8, i=6),
    dict(x=1.6, z=0.5, y_h=1.8, w=1.0, h=0.7, i=7),
    dict(x=-2.4, z=-1.0, y_h=2.6, w=1.6, h=1.1, i=8, body=True),
    dict(x=0.2, z=-1.6, y_h=1.5, w=1.3, h=0.9, i=9),
    dict(x=-3.6, z=-2.4, y_h=2.0, w=1.4, h=0.9, i=1),
    dict(x=1.1, z=-2.9, y_h=3.0, w=1.2, h=0.8, i=3),
]


def listy_g01(img, cam, t, tf, sheets, подпись, мелко):
    """`tf` — ход падения 0..1 (0 висят, 1 лежат); от дальних к ближним."""
    листы = [s for s in (sheets or ()) if str(s).strip()]
    order = sorted(range(len(LISTY)), key=lambda i: -LISTY[i]["z"])
    for i in order:
        L = LISTY[i]
        x, z, w, h = L["x"], L["z"], L["w"], L["h"]
        hang = [(x - w / 2, L["y_h"] + h / 2, z), (x + w / 2, L["y_h"] + h / 2, z),
                (x + w / 2, L["y_h"] - h / 2, z), (x - w / 2, L["y_h"] - h / 2, z)]
        lie = [(x - w / 2, 0.02, z + h / 2), (x + w / 2, 0.02, z + h / 2),
               (x + w / 2, 0.02, z - h / 2), (x - w / 2, 0.02, z - h / 2)]
        u = out_cubic(tf)
        c = [tuple(hang[k][j] + (lie[k][j] - hang[k][j]) * u for j in range(3))
             for k in range(4)]
        zcn = sum(p[2] for p in c) / 4
        if zcn - cam.z < 0.6:
            continue
        pr = [cam.proj(p) for p in c]
        xs = [p[0] for p in pr]
        ys = [p[1] for p in pr]
        if max(xs) < -50 or min(xs) > W + 50 or max(ys) < -50 or min(ys) > H + 50:
            continue
        if max(xs) - min(xs) < 6:
            continue
        # ТЕКСТ — ТОЛЬКО НА ЛИСТАХ, ЦЕЛИКОМ ВЛЕЗШИХ В БЕЗОПАСНУЮ РАМКУ
        # (13.11, пункт 0-В). Облако листов — сам приём, его геометрию не
        # трогаем; у листа, который режется кромкой кадра или садится в
        # полосу субтитров, снимаем НАДПИСЬ, а белый лист остаётся на месте.
        в_рамке = (min(xs) >= РАМКА[0] and max(xs) <= РАМКА[2]
                   and min(ys) >= РАМКА[1] and max(ys) <= РАМКА[3])
        if tf < 0.999:
            d = ImageDraw.Draw(img, "RGBA")
            a = cam.proj((x, cam.y + 20.0, z))
            b = cam.proj(((c[0][0] + c[1][0]) / 2, c[0][1], z))
            d.line([(a[0], a[1]), (b[0], b[1])], fill=(70, 70, 72, 220), width=1)
        строки = ([листы[L["i"] % len(листы)]] if (листы and в_рамке) else [])
        tex = post_tex((L["i"], в_рамке), строки, подпись if строки else "",
                       мелко if (L.get("body") and в_рамке) else "",
                       w_px=min(2400, int(420 * w)), h_px=min(2400, int(420 * h)),
                       bold=40)
        paste_quad(img, tex, pr)


_TABLO = {}


def tablo_tex(t, метка, знаки, низ, акцент):
    """Чёрное табло 2,2×2,2 м: метка, перекидные знаки значения, нижняя
    строка. Докидывание прежнего значения в новое — за 0,22 с, как на плёнке."""
    key = (round(t, 3), метка, знаки, низ, tuple(акцент))
    if key in _TABLO:
        return _TABLO[key]
    _TABLO.clear()
    S = 900
    im = Image.new("RGBA", (S, S), (16, 16, 17, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, S - 1, S - 1], outline=(70, 70, 72, 255), width=6)
    if метка:
        d.text((70, 60), метка, font=zc.font(FONT_B, 92), fill=(236, 236, 234, 255))
    u = seg(t, 0.0, 0.22)
    new = знаки or "0"
    старое = _прежнее(new)
    n = len(new)
    fd = zc.font(FONT_A, 330 if n <= 3 else int(330 * 3.0 / n))
    gap = 24
    tw = min(250, int((S - 52 - (n - 1) * gap) / max(1, n)))
    x0 = (S - n * tw - (n - 1) * gap) // 2
    ty0, th = 250, 400
    for i in range(n):
        x = x0 + i * (tw + gap)
        d.rectangle([x, ty0, x + tw, ty0 + th], fill=(28, 28, 30, 255))
        tile_new = Image.new("RGBA", (tw, th), (28, 28, 30, 255))
        tile_old = Image.new("RGBA", (tw, th), (28, 28, 30, 255))
        for tile, ch, col in ((tile_new, new[i], tuple(акцент[:3]) + (255,)),
                              (tile_old, старое[i], (240, 240, 238, 255))):
            dd = ImageDraw.Draw(tile)
            bb = dd.textbbox((0, 0), ch, font=fd)
            dd.text(((tw - (bb[2] - bb[0])) // 2 - bb[0],
                     (th - (bb[3] - bb[1])) // 2 - bb[1]), ch, font=fd, fill=col)
        top_new = tile_new.crop((0, 0, tw, th // 2))
        bot_new = tile_new.crop((0, th // 2, tw, th))
        top_old = tile_old.crop((0, 0, tw, th // 2))
        bot_old = tile_old.crop((0, th // 2, tw, th))
        ui = clamp01(u * 1.0 - i * 0.12 * (1 - u))
        if ui >= 1.0:
            im.alpha_composite(top_new, (x, ty0))
            im.alpha_composite(bot_new, (x, ty0 + th // 2))
        else:
            im.alpha_composite(top_new, (x, ty0))
            im.alpha_composite(bot_old, (x, ty0 + th // 2))
            if ui < 0.5:
                hh = max(1, int(th // 2 * (1 - 2 * ui)))
                im.alpha_composite(top_old.resize((tw, hh)), (x, ty0 + th // 2 - hh))
            else:
                hh = max(1, int(th // 2 * (2 * ui - 1)))
                im.alpha_composite(bot_new.resize((tw, hh)), (x, ty0 + th // 2))
        d.line([(x, ty0 + th // 2), (x + tw, ty0 + th // 2)], fill=(10, 10, 10, 255),
               width=5)
    if низ:
        fdate = zc.font(FONT_A, 74)
        bb = d.textbbox((0, 0), низ, font=fdate)
        while bb[2] - bb[0] > S - 80 and fdate.size > 24:
            fdate = zc.font(FONT_A, fdate.size - 6)
            bb = d.textbbox((0, 0), низ, font=fdate)
        d.text(((S - (bb[2] - bb[0])) // 2 - bb[0], 718), низ, font=fdate,
               fill=(236, 236, 234, 255))
    _TABLO[key] = im
    return im


def _прежнее(знаки):
    """Прежнее показание табло той же длины: счётчик только что щёлкнул."""
    цифры = re.sub(r"\D", "", знаки)
    if цифры:
        n = int(цифры)
        p = max(0, n - max(1, n // 12))
        s = str(p).rjust(len(цифры), "0")
        out, j = [], 0
        for ch in знаки:
            if ch.isdigit():
                out.append(s[j] if j < len(s) else ch)
                j += 1
            else:
                out.append(ch)
        return "".join(out)
    return знаки


def tablo(img, cam, t, center, метка, знаки, низ, акцент, size=2.2):
    cx, cy, cz_ = center
    yaw = cam.yaw
    c = quad((cx, cy, cz_), size, size, yaw=yaw)
    d = ImageDraw.Draw(img, "RGBA")
    for k in (-0.6, 0.6):
        tx = cx + k * size / 2 * math.cos(yaw)
        tz = cz_ + k * size / 2 * math.sin(yaw)
        a = cam.proj((tx, cam.y + 20.0, tz))
        b = cam.proj((tx, cy + size / 2, tz))
        d.line([(a[0], a[1]), (b[0], b[1])], fill=(60, 60, 62, 240), width=2)
    tex = tablo_tex(t, метка, знаки, низ, акцент)
    for i in (3, 2, 1):
        cs = [(p[0] - 0.012 * i * math.sin(yaw), p[1], p[2] + 0.012 * i * math.cos(yaw))
              for p in c]
        side = Image.new("RGBA", tex.size, (40, 40, 42, 255))
        paste_quad(img, side, [cam.proj(p) for p in cs])
    paste_quad(img, tex, [cam.proj(p) for p in c])


def g01_cam(t):
    """Четыре плана; t 0..5 ↔ 17.0..22.0 плёнки."""
    if t < 1.0:
        yaw = math.radians(8.0 + 1.1 * t)
        return HALL_A, CamP(0.0, 1.55, 0.3 * t, yaw, math.radians(7.5))
    if t < 4.333:
        if t < 3.0:
            z = -5.0 + 2.2 * (t - 1.0)
        else:
            z = -0.6 + 0.6 * (t - 3.0)
        pitch = math.radians(8.0) + math.radians(-18.3) * smooth(seg(t, 2.70, 3.20))
        return HALL_D, CamP(-1.0, 1.55, z, math.radians(6.0), pitch)
    tt = t - 4.333
    return HALL_D, CamP(0.0, 1.55, 1.5 * tt, 0.0, math.radians(-0.8))


def zal_g01(out=None, t=None, text="", na_polu="", accent="", words=(),
            sheets=(), kick="", say="", author="", value="", value_sub="",
            channel="", watermark="", dur=0.0, sfx=None, **_):
    """G01. Четыре плана и две склейки: табло со счётом на тросах → пролёт
    сквозь облако висящих листов под объёмной фразой → камера клюёт вниз,
    листы падают и ложатся на пол → пустой зал, где тёмные слова висят, а
    ударные встают из пола цветом канала.

    `text` — фраза сцены (планы B и C), `accent` — надпись на полу плана C,
    `kick` — тёмные висящие слова плана D, `na_polu` — ударные слова, встающие
    из пола, `value`/`value_sub` — табло плана A, `sheets` — строки листов,
    `say` — мелкий текст на больших листах.

    Возвращает RGB-кадр 1920×1080 (этого ждёт `style_cards.render_anim`).
    """
    tt = G01_HERO if t is None else _время(t, dur, G01_ПОЛНОЕ)
    bg, _fg = цвета(channel)
    акц = tuple(bg[:3]) + (255,)
    акц_бок = _тень_цвета(bg)

    верх = _строки(text, строк=2, знаков=14)
    # ЛИСТЫ БЕЗ СОДЕРЖАНИЯ — ЭТО СТЕНА ПУСТОЙ БУМАГИ (проверено кадром на
    # пустых аргументах), поэтому запасной вариант — строки самой фразы.
    листы_текст = ([str(x) for x in (sheets or ()) if str(x).strip()]
                   or _строки(text, строк=3, знаков=20))
    строка_пола = _первый(accent, верх[-1] if верх else "", text).upper()
    тёмные = _слова(_первый(kick, " ".join(верх[:1]) if верх else text), 3)
    ударные = _слова(_первый(na_polu, accent, " ".join(_слова(text)[-2:])), 2)
    знаки = _цифры(_первый(value, _число_из(text)))
    подпись_табло = _слова(value_sub)
    метка = подпись_табло[0] if подпись_табло else ("СЧЁТ" if знаки else "")
    низ_табло = " ".join(подпись_табло[1:])

    hall, cam = g01_cam(tt)

    # --- A: табло на тросах; без значения на тросах висит первая строка фразы
    if tt < 1.0:
        img = zal2(cam, hall, ropes=5, акцент=акц)
        yaw = cam.yaw
        центр = (-5.8 * math.sin(yaw), 2.55, 5.8 * math.cos(yaw))
        if знаки:
            tablo(img, cam, tt, центр, метка, знаки, низ_табло, акц, size=2.3)
            _ev(sfx, 0.0, "label")
        elif верх:
            слово = верх[0]
            cap = _cap_fit(слово, 0.70, 4.6)
            slovo_visit(img, cam, слово, центр[0], центр[1], центр[2], cap, INK,
                        INK_SIDE, k=1.0, depth=0.25)
        return _готово(img, out, watermark)

    # --- B/C: пролёт сквозь листы, падение листов, надпись на полу
    if tt < 4.333:
        img = zal2(cam, hall, ropes=14, акцент=акц)
        tf = seg(tt, 2.90, 3.13)
        listy_g01(img, cam, tt, tf, листы_текст, author, say)
        zl = 4.85
        xl_ = -1.0 - (zl + 1.15) * math.sin(math.radians(6.0))
        up = 3.5 * seg(tt, 2.95, 3.10) ** 2
        # СТРОКИ ВПИСЫВАЮТСЯ В БЕЗОПАСНУЮ РАМКУ КАЖДЫЙ КАДР, а не только по
        # образцовому пределу ширины: длительность сцены растягивает таймлайн,
        # и на 6 с и 14 с строки подъезжают к камере ближе, чем в пробе на
        # 5 с, — на облачной пробе 13.11 верхнюю строку срезало кромкой.
        # Ужимается КАПИТЕЛЬ и место, ход и времена входа прежние.
        for i, (строка, y0_, cap0, st_, t0_) in enumerate((
                (верх[0] if верх else "", 3.30, 0.70, 1.25, 1.30),
                (верх[1] if len(верх) > 1 else "", 2.25, 0.80, 1.00, 1.80))):
            if not строка:
                continue
            cap = _cap_fit(строка, cap0, 5.40, stretch=st_)   # предел образца
            ш = _ширина_слова(строка, cap, st_)
            цс, ш, cap = _вписать_в_рамку(cam, (xl_, y0_, zl), ш, cap)
            цс = _внутри_или_вон(cam, (цс[0], цс[1] + up, цс[2]), ш, cap)
            slovo_visit(img, cam, строка, цс[0], цс[1], цс[2], cap, INK, INK_SIDE,
                        k=seg(tt, t0_, t0_ + 0.15), depth=0.25, stretch=st_)
            _ev(sfx, t0_, "label")
        if tt >= 3.20 and строка_пола:
            слова = строка_пола.split()
            кусок = слова[0] if (tt < 3.267 and len(слова) > 1) else строка_пола
            full = slovo_tex(строка_пола, INK)
            cap = _cap_fit(строка_пола, 0.62, 3.81)   # ширина «IF ANYTHING...» образца
            tex = slovo_tex(кусок, INK)
            wfull = cap * full.width / full.height
            w = cap * tex.width / tex.height
            xc = -1.0 - 11.0 * math.sin(math.radians(6.0)) - 0.37
            x0 = xc - wfull / 2
            c = [(x0, 0.53 + cap / 2, 10.7), (x0 + w, 0.53 + cap / 2, 10.7),
                 (x0 + w, 0.53 - cap / 2, 10.7), (x0, 0.53 - cap / 2, 10.7)]
            paste_quad(img, tex, [cam.proj(p) for p in c])
            _ev(sfx, 3.20, "accent")
        return _готово(img, out, watermark)

    # --- D: пустой зал, тёмные висят, ударные встают из пола
    img = zal2(cam, hall, ropes=6, акцент=акц)
    tt2 = tt - 4.333
    zb = 9.9
    старты = _старты([0.0, 0.07, 0.27], len(тёмные))
    # левый край и зазор сняты с образца (слова там стояли по абсолютным x:
    # −1.95 · −0.40 · 1.70 при капители 0.66), капитель — та же
    ряд = _ряд_слов(тёмные, [0.66], -2.05, 0.42, 3.96)
    for i, (слово, xx, cap) in enumerate(ряд):
        k = 1.0 if i == 0 else seg(tt2, старты[i], старты[i] + 0.06)
        if i == 0:                        # первое слово качнулось на тросе
            xx += -0.30 * (1 - smooth(seg(tt2, 0.0, 0.07)))
        slovo_visit(img, cam, слово, xx, 2.40, zb, cap, INK, INK_SIDE, k=k, depth=0.22)
        _ev(sfx, 4.333 + старты[i], "label")
    старты_у = _старты([0.29, 0.52], len(ударные))
    длит = [0.11, 0.09]
    # УДАРНЫЕ СЛОВА НЕ РЯД: у образца они разнесены ПО ГЛУБИНЕ (9,75 и 11,0 м)
    # и по x налезают друг на друга намеренно. Поэтому места, капители,
    # растяжки и глубины берём образцовые, а ужимаем только ширину — по той,
    # что была у самого образца (1,67 м и 5,38 м).
    места = [(-2.05, 9.75, 0.88, 1.15, 0.30, 1.67),
             (1.35, 11.0, 1.00, 1.38, 0.34, 5.38)]
    for i, слово in enumerate(ударные):
        xx, zz, cap0, st, dp, пред = места[i] if i < len(места) else места[-1]
        d_ = длит[i] if i < len(длит) else 0.09
        cap = _cap_fit(слово, cap0, пред, stretch=st)
        k = seg(tt2, старты_у[i], старты_у[i] + d_)
        slovo_iz_pola(img, cam, слово, xx, zz, cap, акц, акц_бок, k,
                      depth=dp, stretch=st)
        _ev(sfx, 4.333 + старты_у[i], "accent")
    return _готово(img, out, watermark)


# ===========================================================================
# G48 · zal_g48 — ЗАЛ ОКАЗЫВАЕТСЯ КАРТИНОЙ В РАМЕ ВНУТРИ ТОГО ЖЕ ЗАЛА
# ===========================================================================
# Ширина картины на экране: 100 % → 42 % за 600 мс (S-образно), дальше → 36 %
# к концу; центр картины 50 % → 47 % → 40 %. Строка над рамой улетает вверх
# на 2.2 с, строка на полу входит словами 2.53 / 2.87 / 3.10 / 3.43 / 3.67.
G48_ПОЛНОЕ = 4.0
G48_HERO = 3.80
ZP48, WP48, HP48, YC48 = 12.0, 3.12, 1.755, 1.99


def box(img, cam, x, z, w, h, d, col, op=1.0):
    """Параллелепипед на полу: грани верх, бок к центру, фронт."""
    x0, x1 = x - w / 2, x + w / 2
    z0, z1 = z, z + d
    front = [(x0, h, z0), (x1, h, z0), (x1, 0, z0), (x0, 0, z0)]
    top = [(x0, h, z1), (x1, h, z1), (x1, h, z0), (x0, h, z0)]
    side = ([(x0, h, z1), (x0, h, z0), (x0, 0, z0), (x0, 0, z1)] if x > 0 else
            [(x1, h, z0), (x1, h, z1), (x1, 0, z1), (x1, 0, z0)])
    if not visible(cam, front):
        return
    r, g, b = col[:3]

    def solid(k):
        return Image.new("RGBA", (32, 32), (int(r * k), int(g * k), int(b * k), 255))

    sh = [(x0 + 0.4, 0.01, z0 + 0.5), (x1 + 0.4, 0.01, z1 + 0.5),
          (x1, 0.01, z1), (x0, 0.01, z0)]
    paste_quad(img, Image.new("RGBA", (32, 32), (40, 38, 36, int(60 * op))),
               [cam.proj(q) for q in sh])
    paste_quad(img, solid(1.0), [cam.proj(q) for q in top], op)
    paste_quad(img, solid(0.80), [cam.proj(q) for q in side], op)
    paste_quad(img, solid(0.92), [cam.proj(q) for q in front], op)


def stack(img, cam, x, z, w, h, d, col, n=5):
    """Стопка блоков с тонкими швами."""
    for i in range(n):
        hh = h / n
        x0, x1 = x - w / 2, x + w / 2
        y0, y1 = i * hh, (i + 1) * hh - 0.02
        front = [(x0, y1, z), (x1, y1, z), (x1, y0, z), (x0, y0, z)]
        top = [(x0, y1, z + d), (x1, y1, z + d), (x1, y1, z), (x0, y1, z)]
        side = ([(x0, y1, z + d), (x0, y1, z), (x0, y0, z), (x0, y0, z + d)] if x > 0 else
                [(x1, y1, z), (x1, y1, z + d), (x1, y0, z + d), (x1, y0, z)])
        if not visible(cam, front):
            return
        r, g, b = col[:3]

        def solid(k):
            return Image.new("RGBA", (16, 16), (int(r * k), int(g * k), int(b * k), 255))

        paste_quad(img, solid(1.0), [cam.proj(q) for q in top])
        paste_quad(img, solid(0.80), [cam.proj(q) for q in side])
        paste_quad(img, solid(0.92), [cam.proj(q) for q in front])


def globe_tex(t, цвет, px=360):
    """Глобус гаммы канала с тёмными материками, крутится по долготе."""
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, px - 3, px - 3], fill=tuple(цвет[:3]) + (255,))
    R = px / 2 - 3
    lay = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    rng = np.random.default_rng(3)
    for i in range(14):
        lon = rng.uniform(0, 2 * math.pi)
        lat = rng.uniform(-1.0, 1.0)
        rw = rng.uniform(0.10, 0.24)
        rh = rng.uniform(0.10, 0.22)
        a = lon + t * 0.5
        czz = math.cos(a)
        if czz <= 0.05:
            continue
        cx = px / 2 + R * math.sin(a) * math.cos(lat)
        cy = px / 2 - R * math.sin(lat) * 0.95
        ww = R * rw * czz
        hh = R * rh
        ld.ellipse([cx - ww, cy - hh, cx + ww, cy + hh], fill=(44, 40, 38, 255))
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).ellipse([4, 4, px - 5, px - 5], fill=255)
    lay.putalpha(Image.fromarray(np.minimum(np.asarray(lay.split()[3]),
                                            np.asarray(mask))))
    img.alpha_composite(lay)
    sh = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([px * 0.25, px * 0.1, px * 1.15, px * 1.05],
                               fill=(60, 40, 10, 70))
    sh.putalpha(Image.fromarray(np.minimum(np.asarray(sh.split()[3]),
                                           np.asarray(mask))))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    return img


def wire_cube(img, cam, x, z, size, col=(60, 60, 64, 255), wd=4):
    s = size / 2
    v = [(x - s, 0, z), (x + s, 0, z), (x + s, 0, z + size), (x - s, 0, z + size),
         (x - s, size, z), (x + s, size, z), (x + s, size, z + size),
         (x - s, size, z + size)]
    p = [cam.proj(q) for q in v]
    d = ImageDraw.Draw(img, "RGBA")
    for e0, e1 in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                   (0, 4), (1, 5), (2, 6), (3, 7)):
        d.line([(p[e0][0], p[e0][1]), (p[e1][0], p[e1][1])], fill=col, width=wd)


def row_tiles(line, fsize=200, hl=None, color=DARK, fname=FONT_A, cond=0.80,
              hl_color=(255, 212, 0, 255)):
    """Плитки слов одной строки: (плитка, смещение центра от левого края)."""
    cond = max(COND_MIN, float(cond)) if cond < 1.0 else float(cond)
    _tw, _th, tiles = word_tiles([line], fsize=fsize, fname=fname, hl=hl, color=color,
                                 hl_color=hl_color)
    out = []
    x = 0.0
    gap = fsize * 0.50 * cond
    for tile, _cx, _cy in tiles:
        if cond != 1.0:
            tile = tile.resize((max(4, int(tile.size[0] * cond)), tile.size[1]),
                               Image.LANCZOS)
        bb = tile.getbbox()
        if bb is None:
            continue
        cr = tile.crop((bb[0], 0, bb[2], tile.size[1]))
        out.append((cr, x + cr.size[0] / 2))
        x += cr.size[0] + gap
    return out


def row_cap(tiles, width_m, fsize=200):
    """Капитель, при которой строка плиток занимает `width_m` метров."""
    if not tiles:
        return 0.3
    tile, off = tiles[-1]
    px = off + tile.size[0] / 2
    return width_m / max(1.0, px) * (CAP * fsize)


def vol(img, cam, corners, tex, depth=0.1, steps=4, side=DARK_SIDE, op=1.0):
    """Объём копиями в глубину (+z) с прозрачностью."""
    alpha = tex.split()[3]
    for i in range(steps, -1, -1):
        k = i / steps
        cs = [(c[0], c[1], c[2] + depth * k) for c in corners]
        if not visible(cam, cs):
            continue
        pts = [cam.proj(p) for p in cs]
        if i == 0:
            t = tex
        else:
            v = [int(side[j] * (0.80 + 0.20 * (1 - k))) for j in range(3)]
            t = Image.new("RGBA", tex.size, (v[0], v[1], v[2], 255))
            t.putalpha(alpha)
        paste_quad(img, t, pts, op)


def word_row(img, cam, t, tiles, starts, left, y, z, cap, depth=0.1, side=DARK_SIDE,
             floor=False, shadow=False, dy=0.0, k0=1.20, wires=0):
    """Строка слов в плоскости z=const лицом к камере; `left` — x левого края
    первого слова, `y` — центр строки (или пол, если `floor`)."""
    sc = cap / (CAP * 200)
    starts = _старты(starts, len(tiles))
    for (tile, off), t0 in zip(tiles, starts):
        p = pop(t0, t, k0=k0)
        if p is None:
            continue
        s, op = p
        w = tile.size[0] * sc * s
        h = tile.size[1] * sc * s
        cx = left + off * sc
        cy = (h / 2 if floor else y) + dy
        c = quad((cx, cy, z), w, h)
        if not visible(cam, c):
            continue
        if shadow and dy > -0.02:
            bl, br = c[3], c[2]
            sh = [(bl[0] + 0.5 * h, 0.012, bl[2] + 1.1 * h),
                  (br[0] + 0.5 * h, 0.012, br[2] + 1.1 * h),
                  (br[0], 0.012, br[2]), (bl[0], 0.012, bl[2])]
            a = tile.split()[3].point(lambda v: int(v * 0.28))
            dark = Image.new("RGBA", tile.size, (38, 36, 34, 255))
            dark.putalpha(a)
            paste_quad(img, dark.filter(ImageFilter.GaussianBlur(12)),
                       [cam.proj(p) for p in sh])
        if wires:
            for j in range(wires):
                f = (j + 0.5) / wires
                top = (c[0][0] + (c[1][0] - c[0][0]) * f, c[0][1], c[0][2])
                wire(img, cam, top, color=(96, 98, 102, 230), width=2)
        if s > 1.08:
            for shx in (-0.05, 0.05):
                cc = quad((cx + shx * w, cy, z), w, h)
                paste_quad(img, tile, [cam.proj(q) for q in cc], 0.22)
        vol(img, cam, c, tile, depth=depth, steps=4, side=side, op=op)


_G48 = {}


def _g48_tex(внутри, карточка, над, пол, маркер, акц, fg):
    """Плитки строк приёма. Кэш КЛЮЧУЕТСЯ СОДЕРЖАНИЕМ: иначе фраза первой
    сцены застряла бы на весь прогон (кадры одного клипа считает один
    процесс)."""
    key = (внутри, карточка, над, пол, tuple(sorted(маркер or ())),
           tuple(акц), tuple(fg))
    if key not in _G48:
        if len(_G48) > 8:
            _G48.clear()
        _G48[key] = {
            "here": row_tiles(внутри, 200, color=(36, 33, 32, 255), cond=0.78),
            "day": text_tex([карточка], fsize=120, fname=FONT_A,
                            hl=маркер, color=(36, 33, 32, 255), pad=14,
                            hl_color=tuple(акц), hl_ink=tuple(fg)),
            "one": row_tiles(над, 200, color=DARK, cond=0.74),
            "did": row_tiles(пол, 200, color=(40, 37, 36, 255), cond=0.78),
        }
    return _G48[key]


def plate_frame(метка, num, акцент, px=1300):
    """Плашка-счётчик под рамой: метка слева, знаки значения справа."""
    h = int(px * 0.153)
    img = Image.new("RGBA", (px, h), (22, 21, 20, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, px - 1, h - 1], outline=(70, 70, 72, 255), width=4)
    f = zc.font(FONT_B, int(h * 0.66))
    d.text((px * 0.06, h * 0.12), метка, font=f, fill=(242, 242, 242, 255))
    x = px * 0.50
    for ch in num:
        cw = px * (0.03 if ch in ",." else 0.085)
        b = d.textbbox((0, 0), ch, font=f)
        d.text((x + (cw - (b[2] - b[0])) / 2 - b[0], h * 0.12), ch, font=f,
               fill=tuple(акцент[:3]) + (255,))
        if ch not in ",.":
            d.line([(x + cw * 0.1, h * 0.52), (x + cw * 0.9, h * 0.52)],
                   fill=(22, 21, 20, 255), width=4)
        x += cw
    return img


def _g48_inner(t, tx, акц):
    """Сцена ВНУТРИ картины: тот же зал, крупная строка на тросах, предметы на
    полу, уголь-солнце справа. Живёт: камера едет, уголь дышит, глобус крутится."""
    cam = Cam(0.0, 1.55, 0.12 * t, 0.0)
    img = room(cam)
    word_row(img, cam, t, tx["here"], [-1, -1], -3.1, 2.91, 9.0,
             row_cap(tx["here"], 6.4), depth=0.28, side=(22, 20, 19), wires=2)
    Zo = 11.3
    stack(img, cam, -3.2, Zo, 0.75, 1.55, 0.6, (236, 237, 239), n=6)
    stack(img, cam, -2.0, Zo, 0.45, 1.7, 0.45, акц, n=7)
    box(img, cam, 3.35, Zo + 1.5, 0.45, 2.4, 0.45, (92, 64, 44))
    bank = maket_tex("bank", 400)
    cb = quad((3.0, 0.42, Zo), 1.5, 0.84)
    paste_quad(img, bank, [cam.proj(p) for p in cb])
    wire_cube(img, cam, 1.1, Zo, 1.15)
    gl = globe_tex(t, акц)
    cg = quad((-0.9, 0.56, Zo), 1.1, 1.1)
    sh = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([8, 8, 56, 56], fill=(40, 38, 36, 80))
    sq = [(-1.5, 0.01, Zo + 0.3), (-0.3, 0.01, Zo + 0.3),
          (-0.2, 0.01, Zo - 0.4), (-1.6, 0.01, Zo - 0.4)]
    paste_quad(img, sh.filter(ImageFilter.GaussianBlur(5)), [cam.proj(p) for p in sq])
    paste_quad(img, gl, [cam.proj(p) for p in cg])
    day = tx["day"]
    hday = 0.42
    wday = hday * day.size[0] / day.size[1]
    # КАРТОЧКА У КРОМКИ ВИСИТ, А НЕ СТОИТ: образцовые 0,26 м над полом на
    # дальности 7,4 м давали нижний край на 919 px — в полосе субтитров
    # (13.11, пункт 0-В). Поднята ровно настолько, чтобы выйти из полосы;
    # размер, глубина и место по ширине образцовые.
    цк, wday, hday = _вписать_в_рамку(cam, (0.0, 0.26, 7.4), wday, hday)
    cd = quad(цк, wday, hday)
    vol(img, cam, cd, day, depth=0.05, steps=2, side=(120, 120, 124))
    img = embers(img, cam, [(3.7, 2.39, 9.0, 1.35)], t, glow=1.2)
    return img


def zal_g48(out=None, t=None, text="", na_polu="", accent="", words=(),
            sheets=(), kick="", say="", author="", value="", value_sub="",
            channel="", watermark="", dur=0.0, sfx=None, **_):
    """G48. Камера отъезжает — и зал оказывается КАРТИНОЙ В РАМЕ внутри того
    же зала; под рамой плашка со счётчиком кадров, внутри рамы кадр
    продолжает жить (камера едет, глобус крутится, уголь дышит).

    `text` — крупная строка внутри рамы, `accent` — строка над рамой (улетает
    вверх), `na_polu`/`kick` — строка, стоящая на полу перед картиной,
    `value`/`value_sub` — карточка у нижней кромки внутреннего кадра.

    Возвращает RGB-кадр 1920×1080.
    """
    tt = G48_HERO if t is None else _время(t, dur, G48_ПОЛНОЕ)
    bg, fg = цвета(channel)
    акц = tuple(bg[:3]) + (255,)

    строки = _строки(text, строк=2, знаков=16)
    внутри = _первый(строки[0] if строки else "", text, na_polu).upper()
    над = _первый(accent, строки[1] if len(строки) > 1 else "", kick).upper()
    пол = _первый(na_polu, kick, " ".join(строки[1:]) or внутри).upper()
    знач = _первый(value, _число_из(text))
    # КАРТОЧКА У КРОМКИ КОРОТКАЯ, как «DAY 243» образца: одно слово подписи
    # плюс значение. Вся подпись целиком («СЧЁТ ЯНВАРЬ — АВГУСТ») растянула
    # бы её на полкадра и залезла на предметы.
    слово_подписи = (_слова(value_sub)[0] if _слова(value_sub) else "")
    карточка = " ".join(x for x in (слово_подписи, знач.upper()) if x)
    if not карточка:
        карточка = внутри.split()[0] if внутри else "·"
    маркер = {len(карточка.split()) - 1} if знач else None
    tx = _g48_tex(внутри, карточка, над, пол, маркер, акц, fg)

    inner = _g48_inner(tt, tx, акц)
    if tt < 0.5:
        return _готово(inner, out, watermark)

    wf = 1.0 - 0.58 * smooth(seg(tt, 0.5, 1.1)) - 0.06 * seg(tt, 1.1, 4.0) ** 0.9
    d = 3.2 / wf
    cy = YC48 + (1.55 - YC48) * smooth(seg(tt, 0.6, 1.15))
    cam = Cam(0.0, cy, ZP48 - d, 0.0)
    img = room(cam)

    c = quad((0.0, YC48, ZP48), WP48, HP48)
    pts = [cam.proj(p) for p in c]
    bw = max(p[0] for p in pts) - min(p[0] for p in pts)
    pic = inner
    ImageDraw.Draw(pic).rectangle([0, 0, W - 1, H - 1], outline=(28, 27, 26, 255),
                                  width=7)
    if bw < W * 0.98:
        k = max(bw / W, 0.05)
        pic = pic.resize((max(8, int(W * k)), max(8, int(H * k))), Image.LANCZOS)
    for f in (0.22, 0.76):
        rope(img, cam, (-WP48 / 2 + WP48 * f, CEIL, ZP48),
             (-WP48 / 2 + WP48 * f, YC48 + HP48 / 2, ZP48), width=2)

    n = int(round((261.0 + tt) * 30))
    # Метка плашки — своя, «КАДР»: это счётчик кадров приёма, а не подпись
    # значения (её уже несёт карточка у кромки внутреннего кадра).
    pt = plate_frame("КАДР", "{:,}".format(n).replace(",", " "), акц)
    pw, ph = 2.03, 0.36
    # ПЛАШКА ВИСИТ В ЗАЗОРЕ МЕЖДУ НИЖНЕЙ КРОМКОЙ КАРТИНЫ И ПОЛОСОЙ СУБТИТРОВ.
    # Её образцовое место (0,89 м) уходило в полосу на 142 px на середине
    # отъезда, когда картина ещё почти во весь кадр и зазора физически нет.
    # Поэтому: место подгоняется под зазор (тросы идут к фактическому верху),
    # а пока зазор мал — плашка не рисуется вовсе и появляется, как только
    # картина отъехала. Поднимать её «внутрь картины» нельзя: там её закрывает
    # сама картина, и элемент приёма пропадает молча.
    низ_картины = _коробка(cam, c)[3]
    рамка_пл = (РАМКА[0], min(низ_картины + 8, РАМКА[3] - 1), РАМКА[2], РАМКА[3])
    цпл, pw2, ph2 = _вписать_в_рамку(cam, (0.0, 0.89, ZP48), pw, ph, рамка=рамка_пл)
    низ_над_словом = низ_картины
    if ph2 > ph * 0.55 and _в_рамке(cam, quad(цпл, pw2, ph2), рамка_пл):
        cpl = quad(цпл, pw2, ph2)
        низ_над_словом = _коробка(cam, cpl)[3]
        for f in (0.2, 0.8):
            rope(img, cam, (-pw2 / 2 + pw2 * f, YC48 - HP48 / 2, ZP48),
                 (-pw2 / 2 + pw2 * f, цпл[1] + ph2 / 2, ZP48), width=2)
        vol(img, cam, cpl, pt, depth=0.05, steps=2, side=(40, 40, 42))
    vol(img, cam, c, pic, depth=0.05, steps=2, side=(60, 60, 62))

    fly = 3.0 * seg(tt, 2.2, 2.3) ** 2
    if tt < 2.3 and над:
        # СТРОКА НАД РАМОЙ ТОЖЕ ВПИСЫВАЕТСЯ В РАМКУ И УХОДИТ ЦЕЛИКОМ. На
        # растянутом таймлайне (6 с и длиннее) русская строка срезалась верхней
        # кромкой — тот же класс, что у висящих строк G01. Ужимается капитель
        # и место; взлёт `fly` и времена входа слов прежние.
        шир_н = 2.4
        cap_н = row_cap(tx["one"], шир_н)
        выс_н = cap_н * 1.45
        цн, шир2, выс2 = _вписать_в_рамку(cam, (0.0, 3.22, ZP48), шир_н, выс_н)
        if выс2 < выс_н * 0.999:
            шир_н *= выс2 / выс_н
            cap_н = row_cap(tx["one"], шир_н)
        цн = _внутри_или_вон(cam, (цн[0], цн[1] + fly, цн[2]), шир2, выс2)
        word_row(img, cam, tt, tx["one"], [1.17, 1.30, 1.63],
                 -1.5 * шир_н / 2.4, цн[1], ZP48, cap_н, depth=0.04,
                 side=DARK_SIDE)
        _ev(sfx, 1.17, "label")
    if пол:
        # СЛОВО СТОИТ НА ПОЛУ, ПОДНЯТЬ ЕГО «В ВОЗДУХ» НЕЛЬЗЯ — ставим ДАЛЬШЕ
        # ПО ГЛУБИНЕ, и основание уходит выше полосы субтитров само
        # (образцовые 1,1 м перед картиной давали базу на 930 px).
        # ЗАПАС 35 px НА ОБЪЁМ И ТЕНЬ: у слова на полу ниже основания живут
        # выдавливание и тень, и OCR считает их частью надписи — на короткой
        # сцене ровная граница давала заход в полосу на 13 px.
        # ЗАПАС 15 px — ЗАМЕРЕН, А НЕ ВЗЯТ С ЗАПАСОМ: ниже линии пола у строки
        # живёт только тень (промер 13.11: нижний чернильный пиксель на 10 px
        # ВЫШЕ линии без тени и на 11 px ниже с тенью). Прежние 35 px уводили
        # слово на метр дальше, чем нужно, и оно читалось мелким и плоским.
        z_пол = max(ZP48 - 1.1,
                    cam.z + _глубина_над_полосой(cam, SUB_Y - ЗАПАС - 15))
        # УХОД ПО ГЛУБИНЕ КОМПЕНСИРУЕТСЯ ШИРИНОЙ: иначе слово выглядит мелким
        # и далёким (его замечание по облачной пробе 13.11). Образцовые 4,3 м
        # умножаем на отношение дальностей — экранный размер остаётся тем же,
        # что у образца, а основание стоит выше полосы. Ширина ограничена
        # безопасной рамкой.
        d_обр = max(0.3, (ZP48 - 1.1) - cam.z)
        d_нов = max(0.3, z_пол - cam.z)
        шир = 4.3 * d_нов / d_обр
        шир = min(шир, (РАМКА[2] - РАМКА[0]) * d_нов / F)
        cap_пол = row_cap(tx["did"], шир)
        # ВЕРХ СЛОВА НЕ ЗАХОДИТ НА ПЛАШКУ-СЧЁТЧИК: компенсация ширины подняла
        # его настолько, что слово легло поверх плашки (поймано кадром после
        # первой правки 13.11). Капитель ограничена зазором под плашкой.
        предел_cap = (cam.y - (низ_над_словом + 8 - H / 2) * d_нов / F) / 1.45
        if 0.05 < предел_cap < cap_пол:
            шир *= предел_cap / cap_пол
            cap_пол = предел_cap
        # ГЛУБИНА ОБЪЁМА ИДЁТ ЗА РАЗМЕРОМ. Образцовые 0,22 м сняты для строки
        # шириной 4,3 м; после компенсации ширины буквы стали крупнее, а объём
        # остался прежним — строка читалась как плоский титр поверх кадра
        # (его замечание по третьей облачной пробе). Соотношение объёма к
        # высоте букв возвращено к образцовому.
        глубина = 0.22 * шир / 4.3
        word_row(img, cam, tt, tx["did"], [2.53, 2.87, 3.10, 3.43, 3.67],
                 -шир / 2.0, 0.0, z_пол, cap_пол, depth=глубина,
                 side=(22, 20, 19), floor=True, shadow=True)
        _ev(sfx, 2.53, "accent")
    return _готово(img, out, watermark)


# ===========================================================================
# G44 · zal_g44 — ВЫНОСКА СО ЗНАЧЕНИЕМ У ТОЧКИ ШКАЛЫ
# ===========================================================================
# Столб-шкала x 25 %, основание y 76 % → d≈10,9 м, X≈−2,65. Плашка 2,0×1,16 м,
# низ на полу вплотную справа от столба. Вход 0.933 → ~1.40 (≈470 мс): перелёт
# ~20 %, крен −8° и затухающая дрожь exp(−e/0,10)·cos(2π·e/0,22).
G44_ПОЛНОЕ = 5.0
G44_HERO = 3.60
G44_PL0 = 0.933


def column_tex(px=160, py=2400):
    """Столб-шкала: тёмный, деления по левому краю."""
    img = Image.new("RGBA", (px, py), (74, 68, 62, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, px * 0.12, py], fill=(96, 90, 82, 255))
    step = py / 100.0
    for i in range(100):
        y = int(i * step)
        ln = px * 0.45 if i % 10 == 0 else (px * 0.32 if i % 5 == 0 else px * 0.2)
        d.line([(px * 0.12, y), (px * 0.12 + ln, y)], fill=(196, 190, 180, 255), width=3)
    return img


def plate_value_tex(значение, акцент, px=1000, py=570):
    """Плашка выноски: коричневый обод, тёмное поле, по ячейке на знак
    значения, знаки — гаммой канала.

    ЗНАЧЕНИЕ ИДЁТ ЦЕЛИКОМ, КАК ПРИШЛО. У образца это «<1%» — три знака, и
    прежний разбор «оставить только цифры и проценты» ломал русские варианты:
    «116 175» обрезалось до пяти знаков, «4,3 млрд» — до «4,3», а на фразе без
    цифр плашка рисовала один прочерк (дефект облачной пробы 13.11: вместо
    «14 %» в плашке одна жёлтая чёрточка). Пробел — узкий зазор без
    перегородки, кегль подбирается по самой широкой ячейке.
    """
    знаки = list(str(значение or "").strip())[:10]
    if not знаки:
        знаки = ["—"]
    вес = [0.45 if c == " " else 1.0 for c in знаки]
    поле = px - 52
    шаг = поле / sum(вес)
    img = Image.new("RGBA", (px, py), (98, 84, 66, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([26, 26, px - 27, py - 27], fill=(18, 16, 15, 255))
    ширина_ячейки = шаг * min(w for w in вес if w > 0.5)
    кегль = int(py * 0.70)
    while кегль > 20:
        f = zc.font(FONT_B, кегль)
        подошло = True
        for c in знаки:
            if c == " ":
                continue
            b = d.textbbox((0, 0), c, font=f)
            if (b[2] - b[0]) > ширина_ячейки * 0.84 or (b[3] - b[1]) > py * 0.62:
                подошло = False
                break
        if подошло:
            break
        кегль -= 6
    f = zc.font(FONT_B, кегль)
    x = 26.0
    for i, c in enumerate(знаки):
        cw = шаг * вес[i]
        if i and c != " " and знаки[i - 1] != " ":
            d.line([(x, 30), (x, py - 30)], fill=(58, 52, 46, 255), width=4)
        if c != " ":
            b = d.textbbox((0, 0), c, font=f)
            d.text((x + (cw - (b[2] - b[0])) / 2 - b[0],
                    (py - (b[3] - b[1])) / 2 - b[1]), c, font=f,
                   fill=tuple(акцент[:3]) + (255,))
        x += cw
    return img


_G44 = {}


def _g44_words(пояснение, вводная, строки, у_пола, маркеры, акц, знач):
    """Плитки приёма. Кэш ключуется содержанием — см. `_g48_tex`."""
    key = (tuple(пояснение), вводная, tuple(строки), у_пола,
           tuple(tuple(sorted(m)) if m else () for m in маркеры), tuple(акц), знач)
    if key not in _G44:
        if len(_G44) > 8:
            _G44.clear()
        _G44[key] = {
            "expl": words_block(list(пояснение), 0.29, cond=1.0),
            "back": words_block([вводная], 0.36, cond=1.05),
            "rows": [words_block([s], 0.36, cond=1.05, hl=маркеры[i] or None,
                                 hl_color=tuple(акц))
                     for i, s in enumerate(строки)],
            "feb": words_block([у_пола], 0.36, cond=1.0) if у_пола else None,
            "col": column_tex(),
            "pl": plate_value_tex(знач, акц),
        }
    return _G44[key]


def zal_g44(out=None, t=None, text="", na_polu="", accent="", words=(),
            sheets=(), kick="", say="", author="", value="", value_sub="",
            channel="", watermark="", dur=0.0, sfx=None, **_):
    """G44. Выноска со значением у точки шкалы: столб-шкала от пола до потолка
    с делениями, уголь у основания, пояснение справа, блок строк сверху — и
    плашка со значением подлетает справа-сверху с перелётом и затухающей
    дрожью, вставая вплотную к низу шкалы.

    `value` — значение на плашке, `value_sub` — слово у основания шкалы,
    `text` — подпись (блок строк сверху), `sheets` — пояснение справа от
    шкалы, `kick`/`accent` — короткая вводная и слово под маркером.

    Возвращает RGB-кадр 1920×1080.
    """
    tt = G44_HERO if t is None else _время(t, dur, G44_ПОЛНОЕ)
    bg, _fg = цвета(channel)
    акц = tuple(bg[:3]) + (255,)

    строки = _строки(text, строк=4, знаков=16)
    пояснение = [str(s).upper() for s in (sheets or ()) if str(s).strip()][:3]
    if not пояснение:
        пояснение = _строки(_первый(value_sub, say, text), строк=3, знаков=18)
    вводная = _первый(kick, строки[0] if строки else text).upper()
    у_пола = (_слова(value_sub)[0] if _слова(value_sub) else "")
    маркеры = []
    for i, s in enumerate(строки):
        m = _маркер(s.split(), accent)
        if m is None and not accent and i == 1:
            m = {0, 1} if len(s.split()) > 1 else {0}
        маркеры.append(m)
    знач = _первый(value, _число_из(text)).upper()
    wd = _g44_words(пояснение, вводная, строки, у_пола, маркеры, акц, знач)

    cam = Cam(0.09 * tt, 1.55, 0.15 * tt, 0.0)
    img = room(cam)
    D = 10.9
    XC = -2.65

    col = quad((XC, CEIL / 2, D), 0.27, CEIL)
    extrude_dir(img, cam, col, wd["col"], 0.27, (0.0, 0.0, 1.0), steps=4,
                side=(36, 33, 30))
    base = [(XC - 0.4, 0.03, D + 0.5), (XC + 0.4, 0.03, D + 0.5),
            (XC + 0.4, 0.03, D - 0.3), (XC - 0.4, 0.03, D - 0.3)]
    paste_quad(img, Image.new("RGBA", (64, 64), (40, 37, 34, 255)),
               [cam.proj(p) for p in base])

    if wd["feb"]:
        блок_f, sc_f = wd["feb"]
        ш_f = блок_f[0] * sc_f
        в_f = блок_f[1] * sc_f
        цf = _увести_по_x(cam, (XC - 0.95, в_f / 2.0, D - 0.2), ш_f, в_f)
        place_words(img, cam, tt, блок_f, (цf[0], 0.0, D - 0.2), 0.0,
                    sc_f, [-1.0], depth=0.10, side=DARK_SIDE, floor=True, k0=1.0)
    if пояснение:
        блок, sc = _ужать(wd["expl"], 4.6)
        tw = блок[0] * sc
        place_words(img, cam, tt, блок, (0.78 + tw / 2, 0.66, D), 0.0, sc,
                    [-1.0] * len(блок[2]), depth=0.06, side=DARK_SIDE, k0=1.0)

    pulse = 1.0 + 0.05 * math.sin(tt * 5.1)
    img = glow_spot(img, cam, (XC, 0.10, D - 0.15), 1.9 * pulse, strength=0.85,
                    core=0.10, color=(255, 140, 40))
    img = glow_spot(img, cam, (XC, 0.14, D - 0.15), 0.75 * pulse, strength=0.9,
                    core=0.32, color=(255, 175, 70))

    XL = -1.06
    if tt < 0.85:
        if вводная:
            блок, sc = _ужать(wd["back"], 4.4)
            tw0 = блок[0] * sc
            place_words(img, cam, tt, блок, (XL + tw0 / 2, 2.55, D), 0.0, sc,
                        [-1.0, -1.0], depth=0.08, side=DARK_SIDE, k0=1.0)
    else:
        starts = [[0.950, 1.217], [1.450, 1.700],
                  [2.100, 2.200, 2.400, 2.700, 2.900], [3.100, 3.400, 3.600]]
        rows_y = [2.69, 2.33, 1.95, 1.58]
        up = 0.20 * seg(tt, 3.10, 3.20)
        for r, блок_r in enumerate(wd["rows"][:4]):
            блок, sc_r = _ужать(блок_r, 4.6)
            twr = блок[0] * sc_r
            place_words(img, cam, tt, блок, (XL + twr / 2, rows_y[r] + up, D), 0.0,
                        sc_r, starts[r], depth=0.08, side=DARK_SIDE)
            _ev(sfx, starts[r][0], "label")

    if tt >= G44_PL0 - 1e-6:
        u = seg(tt, G44_PL0, G44_PL0 + 0.15)
        k = out_back(u, 2.6)
        off = (0.35 * (1 - k), 1.6 * (1 - k), -2.2 * (1 - k))
        e = tt - G44_PL0
        wob = math.exp(-e / 0.10) * math.cos(2 * math.pi * e / 0.22)
        roll = math.radians(-7.0) * wob
        yaw = math.radians(-8.0) * (1 - out_cubic(u)) + math.radians(-2.0) * wob
        center = (-0.40 + off[0], 0.64 + off[1], D + off[2])
        put_plate(img, cam, wd["pl"], center, 2.0, 1.16, yaw, roll, depth=0.12,
                  side=(60, 52, 44))
        _ev(sfx, G44_PL0, "accent")
        if u < 0.4:
            c2 = quad((center[0] + 0.1, center[1] + 0.4, center[2] - 0.4), 2.0, 1.16,
                      yaw, roll)
            paste_quad(img, wd["pl"], [cam.proj(p) for p in c2], 0.3 * (1 - u / 0.4))

    if tt >= 1.35:
        _подпись_источника(img, _.get("source", "") if _ else "")
    return _готово(img, out, watermark)


# ===========================================================================
# G18 · zal_g18 — БОЛЬШОЕ ЧИСЛО ВО ВЕСЬ КАДР
# ===========================================================================
# Всё появляется ОДНИМ кадром, без пружины; дальше камера наезжает с
# торможением (число 23 % → 27 % высоты кадра за секунду). Лист 5,3×1,43 м,
# центр 0,80 м над полом, правый край дальше (yaw 5°); маркер по словам
# заголовка 0.567 · 0.700 · 0.800 · 0.867; строка источника с 0.30.
G18_ПОЛНОЕ = 4.5
G18_HERO = 2.60


def sheet_value(t, заголовок, ярлык, подстрока, подпись, дата, маркер, акцент,
                чернила, w=2000, h=540):
    """Лист-подтверждение: ярлык гаммой канала, заголовок с маркером по
    словам, серая подстрока, подпись, ряд безымянных кнопок."""
    img = Image.new("RGBA", (w, h), (250, 250, 249, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(212, 212, 210, 255), width=2)
    if ярлык:
        tf = zc.font(FONT_S, 22)
        tw = d.textlength(ярлык, font=tf)
        d.rectangle([(w - tw) / 2 - 14, 30, (w + tw) / 2 + 14, 62],
                    fill=tuple(акцент[:3]) + (255,))
        d.text(((w - tw) / 2, 34), ярлык, font=tf, fill=tuple(чернила[:3]) + (255,))
    hf = zc.font(FONT_S, 84)
    времена = [0.567, 0.700, 0.800, 0.867]
    nмарк = 0
    y = 86
    for ln in заголовок[:2]:
        ws = str(ln).split(" ")
        widths = [d.textlength(wd, font=hf) for wd in ws]
        sp = d.textlength(" ", font=hf)
        total = sum(widths) + sp * (len(ws) - 1)
        if total > w - 60 and total > 0:         # длинная русская строка — ужимаем кегль
            hf2 = zc.font(FONT_S, max(34, int(84 * (w - 60) / total)))
            widths = [d.textlength(wd, font=hf2) for wd in ws]
            sp = d.textlength(" ", font=hf2)
            total = sum(widths) + sp * (len(ws) - 1)
        else:
            hf2 = hf
        x = (w - total) / 2
        for i, (wd, ww) in enumerate(zip(ws, widths)):
            под = (маркер is not None and wd.strip(".,:;!?»«—-").upper() in маркер)
            if под:
                t0 = времена[min(nмарк, len(времена) - 1)]
                nмарк += 1
                if t >= t0 - 1e-6:
                    k = seg(t, t0, t0 + 0.067)   # маркер проводится за два кадра
                    d.rectangle([x - 6, y + 8, x - 6 + (ww + 12) * k, y + 80],
                                fill=tuple(акцент[:3]) + (255,))
            d.text((x, y), wd, font=hf2, fill=(22, 22, 24, 255))
            x += ww + sp
        y += 90
    sf = zc.font(FONT_S, 30)
    if подстрока:
        d.text(((w - d.textlength(подстрока, font=sf)) / 2, 282), подстрока, font=sf,
               fill=(132, 132, 134, 255))
    bf = zc.font(FONT_S, 22)
    if подпись:
        d.text(((w - d.textlength(подпись, font=bf)) / 2, 330), подпись, font=bf,
               fill=(90, 90, 92, 255))
    if дата:
        d.text(((w - d.textlength(дата, font=bf)) / 2, 366), дата, font=bf,
               fill=(170, 170, 172, 255))
    x0 = w * 0.30
    yb = 440
    d.rounded_rectangle([x0, yb - 20, x0 + 150, yb + 20], radius=20,
                        fill=(32, 92, 196, 255))
    cols = [(32, 92, 196), (24, 24, 26), (210, 40, 40), (32, 92, 196), (60, 60, 64),
            (32, 92, 196)]
    for i, c in enumerate(cols):
        cx = x0 + 200 + i * 56
        d.ellipse([cx - 20, yb - 20, cx + 20, yb + 20], fill=c + (255,))
    d.rounded_rectangle([x0 + 560, yb - 20, x0 + 820, yb + 20], radius=20,
                        fill=(32, 92, 196, 255))
    return img


_G18 = {}


def _g18_words(число, строки):
    """Плитки приёма. Кэш ключуется содержанием — см. `_g48_tex`."""
    key = (число, tuple(строки))
    if key not in _G18:
        if len(_G18) > 8:
            _G18.clear()
        _G18[key] = {
            "num": words_block([число], 1.06, cond=0.90),
            "sub": words_block(list(строки), 0.27, cond=1.08),
        }
    return _G18[key]


def zal_g18(out=None, t=None, text="", na_polu="", accent="", words=(),
            sheets=(), kick="", say="", author="", value="", value_sub="",
            channel="", watermark="", dur=0.0, sfx=None, **_):
    """G18. Большое число во весь кадр: значение на треть высоты висит на
    тросах, пояснение вчетверо мельче под ним, ниже — лист-подтверждение с
    маркером, который проводится по словам заголовка. Камера наезжает.

    `value` — само число, `value_sub` — подпись под ним, `text` — заголовок
    листа, `accent` — слова под маркером, `sheets` — подстрока и дата листа,
    `kick` — ярлык листа, `author` — подпись на листе.

    Возвращает RGB-кадр 1920×1080.
    """
    tt = G18_HERO if t is None else _время(t, dur, G18_ПОЛНОЕ)
    bg, fg = цвета(channel)
    акц = tuple(bg[:3]) + (255,)

    слова_т = _слова(text)
    число_ист = _первый(value, _число_из(text))
    # ЧИСЛА НЕТ — КРУПНО ИДЁТ ПЕРВОЕ СЛОВО ФРАЗЫ, А ПОДПИСЬЮ ОСТАТОК, не вся
    # фраза целиком: иначе один и тот же текст стоял бы в кадре трижды
    # (крупно, подписью и на листе) — поймано кадром на пустых аргументах.
    if число_ист:
        число, остаток = число_ист.upper(), слова_т
    else:
        число = (слова_т[0] if слова_т else "").upper()
        остаток = слова_т[1:]
    подпись = _строки(_первый(value_sub, na_polu, " ".join(остаток)), строк=2,
                      знаков=22)
    заголовок = _строки(text, строк=2, знаков=34) or подпись
    маркер = set(w.strip(".,:;!?»«—-") for w in _слова(accent)) or None
    листы = [str(s) for s in (sheets or ()) if str(s).strip()]
    wd = _g18_words(число, подпись)

    cz = 1.3 * (1 - (1 - clamp01(tt / G18_ПОЛНОЕ)) ** 2)   # наезд с торможением
    cam = Cam(0.0, 1.55, cz, 0.0)
    img = room(cam)
    D = 9.0

    блок, sc = _ужать(wd["num"], 5.0)
    place_words(img, cam, tt, блок, (-0.09, 2.92, D), 0.0, sc,
                [-1.0] * len(блок[2]), depth=0.26, side=DARK_SIDE, hang=True,
                wire_per_word=3, k0=1.0)
    _ev(sfx, 0.0, "accent")
    if подпись:
        блок2, sc2 = _ужать(wd["sub"], 6.0)
        place_words(img, cam, tt, блок2, (0.0, 2.02, D), 0.0, sc2,
                    [-1.0] * len(блок2[2]), depth=0.10, side=DARK_SIDE, k0=1.0)

    лист = sheet_value(tt, заголовок, _первый(kick).upper(),
                       листы[0] if листы else "",
                       _первый(author),
                       листы[1] if len(листы) > 1 else "",
                       маркер, акц, fg)
    put_plate(img, cam, лист, (0.05, 0.80, D), 5.3, 1.43, math.radians(5.0), 0.0,
              depth=0.02, side=(180, 180, 182), wires=(0.12, 0.88))
    if tt >= 0.30:
        _подпись_источника(img, _.get("source", "") if _ else "")
    return _готово(img, out, watermark)


# ===========================================================================
# G25 · zal_ekran — ПАНЕЛЬ ЭФИРА РАЗВОРАЧИВАЕТСЯ В ПОЛНЫЙ ЭКРАН И УЕЗЖАЕТ
# ===========================================================================
# ЗАМЕНЯЕТ прежнюю реализацию вида `card:zal_ekran` (она осталась в
# `zal_scenes2.py` под именем `zal_ekran_opus_1111` как след) — его прямое
# слово 13.11: «если это обновлённая версия, то её менять. Старую удалять, а
# новую ставить». Имя вида в двери карточек НЕ меняется.
#
# Числа с плёнки: плавный уход в эфир на всём ролике ровно один — 181.00 →
# 181.73 (0,73 с, панель под углом ~18° выпрямляется и заполняет кадр, ширина
# 0.44 → 0.57 → 0.85 → 1.0, ход почти ровный с лёгким разгоном). Отъезда без
# склейки на плёнке нет — он построен зеркально входу, ходом с торможением
# (out_cubic). Слова субтитра — через 0,27 с после заполнения, шаг 0,165 с;
# плашка с именем въезжает шторкой слева 0.37 → 0.57.
E_ПОЛНОЕ = 5.0
E_HERO = 2.40
E_PANEL_W, E_PANEL_H = 3.2, 1.8      # панель 16:9, метры
E_ZP, E_EYE = 8.0, 1.55              # где висит и на какой высоте центр
E_FLY0 = 0.60                        # зал, панель висит
E_FLY_IN = 0.73                      # разворот во весь кадр
E_FULL = E_FLY0 + E_FLY_IN           # 1.33 — экран целиком
E_BACK0 = 3.50                       # эфир держится 2.17 с
E_FLY_OUT = 0.95                     # отъезд: быстро отходим, долго садимся
E_BACK1 = E_BACK0 + E_FLY_OUT        # 4.45 — снова зал
E_YAW0 = math.radians(30)            # наклон панели в зале
E_YAW1 = math.radians(22)            # наклон после отъезда
E_XOFF0 = 1.0                        # камера левее оси панели
E_LT0, E_LT1 = 0.37, 0.57            # шторка плашки с именем
E_SUB0, E_SUB_STEP = 0.27, 0.165     # первое слово субтитра и шаг
# ОФОРМЛЕНИЕ ЭФИРА ЗАНИМАЕТ ВЕСЬ КАДР, поэтому его доли переставлены в
# безопасную зону (13.11, пункт 0-В): у образца атрибуция стояла на 0.035
# ширины (67 px — за рамкой), логотип на 0.965 (правый край 1853), а нижняя
# плашка с именем на 0.858-0.934 высоты, то есть ЦЕЛИКОМ в полосе субтитров.
# Переставлено только РАЗМЕЩЕНИЕ: времена шторки, субтитра и ход камеры те же.
# Доли считаны С УЧЁТОМ ПЕРЕКРЫТИЯ: в полном экране панель занимает 1.02
# ширины кадра, то есть по 1 % картинки с каждой стороны за кадром, и доля
# 0.945 ложилась на 1831 px — за рамкой на 7 px. Поэтому поля заложены на
# 2 % шире расчётных (0.062 вместо 0.050).
E_SL, E_SR, E_ST = 0.062, 0.938, 0.062
E_PODEM = 0.130                      # на сколько поднят нижний блок (140 px)
E_SUB_DNO = 0.685                    # ниже этой доли субтитр не опускается


def shadow_text(d, xy, txt, f, fill, shadow=(0, 0, 0, 160), r=2):
    x, y = xy
    for dx, dy in ((r, r), (-r, r), (r, -r), (-r, -r), (0, r + 1)):
        d.text((x + dx, y + dy), txt, font=f, fill=shadow)
    d.text((x, y), txt, font=f, fill=fill)


_STUDIO = None


def studio_parts(w=1920, h=1080):
    """(задник, фигура ведущего отдельным слоем). Своя студия и свой ведущий —
    чужих кадров в сцене нет."""
    global _STUDIO
    if _STUDIO is not None:
        return _STUDIO
    img = Image.new("RGBA", (w, h), (16, 40, 112, 255))
    d = ImageDraw.Draw(img)
    for i in range(h):
        k = i / h
        d.line([(0, i), (w, i)], fill=(int(14 + 20 * (1 - k)), int(44 + 36 * (1 - k)),
                                       int(118 + 52 * (1 - k)), 255))
    arcs = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arcs)
    for (cx, cy, r0, step, wd) in ((w * 1.06, h * 0.40, 120, 92, 14),
                                   (w * -0.12, h * 0.62, 90, 70, 9)):
        for r in range(r0, 1700, step):
            ad.ellipse([cx - r, cy - r * 0.64, cx + r, cy + r * 0.64],
                       outline=(96, 150, 236, 70), width=wd)
    img.alpha_composite(arcs.filter(ImageFilter.GaussianBlur(2.5)))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([w * 0.22, h * 0.02, w * 0.78, h * 0.80],
                                 fill=(120, 170, 255, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))
    fig = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fig)
    cx = w * 0.50
    fd.polygon([(cx - w * 0.235, h * 1.02), (cx - w * 0.21, h * 0.64),
                (cx - w * 0.09, h * 0.54), (cx + w * 0.09, h * 0.54),
                (cx + w * 0.21, h * 0.64), (cx + w * 0.235, h * 1.02)],
               fill=(12, 12, 16, 255))
    fd.polygon([(cx - w * 0.055, h * 0.54), (cx + w * 0.055, h * 0.54), (cx, h * 0.70)],
               fill=(30, 30, 36, 255))
    fd.rectangle([cx - w * 0.034, h * 0.42, cx + w * 0.034, h * 0.58],
                 fill=(206, 160, 134, 255))
    fd.ellipse([cx - w * 0.066, h * 0.13, cx + w * 0.066, h * 0.47],
               fill=(222, 182, 156, 255))
    fd.chord([cx - w * 0.070, h * 0.10, cx + w * 0.070, h * 0.33], 180, 360,
             fill=(74, 50, 34, 255))
    fd.chord([cx - w * 0.066, h * 0.30, cx + w * 0.066, h * 0.49], 20, 160,
             fill=(92, 62, 42, 255))
    fd.rectangle([cx - w * 0.070, h * 0.22, cx - w * 0.054, h * 0.30],
                 fill=(74, 50, 34, 255))
    fd.rectangle([cx + w * 0.054, h * 0.22, cx + w * 0.070, h * 0.30],
                 fill=(74, 50, 34, 255))
    for sx in (-1, 1):
        ex = cx + sx * w * 0.026
        fd.ellipse([ex - 11, h * 0.283, ex + 11, h * 0.303], fill=(40, 30, 28, 255))
        fd.line([(ex - 22, h * 0.262), (ex + 22, h * 0.258)], fill=(60, 40, 30, 255),
                width=5)
    fd.line([(cx - 16, h * 0.385), (cx + 16, h * 0.385)], fill=(150, 96, 84, 255),
            width=4)
    vig = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vig)
    vd.rectangle([0, 0, w, h], fill=170)
    vd.ellipse([-w * 0.05, -h * 0.30, w * 1.05, h * 1.05], fill=0)
    vig = vig.filter(ImageFilter.GaussianBlur(140))
    dk = Image.new("RGBA", (w, h), (0, 2, 14, 255))
    dk.putalpha(vig)
    img.alpha_composite(dk)
    sh = fig.filter(ImageFilter.GaussianBlur(30))
    dark = Image.new("RGBA", (w, h), (4, 6, 30, 255))
    dark.putalpha(sh.split()[3].point(lambda v: int(v * 0.6)))
    img.alpha_composite(dark, (int(w * 0.015), int(h * 0.012)))
    _STUDIO = (img, fig)
    return _STUDIO


def studio_tex(t):
    back, fig = studio_parts()
    img = back.copy()
    dx = int(round(4 * math.sin(t * 1.3)))          # дыхание, покачивание
    dy = int(round(2.5 * math.sin(t * 0.8 + 1.0)))
    img.alpha_composite(fig, (dx, dy))
    return img


def overlay_tex(tt, содержание, акцент, чернила, w=1920, h=1080):
    """Оформление эфира поверх картинки. `tt` — время от заполнения кадра
    (до него отрицательное: плашка пуста, субтитров нет)."""
    (атрибуция, подпись1, подпись2, программа, имя, должность, город,
     слова, канал) = содержание
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if атрибуция:
        d.text((w * E_SL, h * E_ST), атрибуция, font=zc.font(FONT_S, 22),
               fill=(255, 255, 255, 190))
    d.rectangle([w * E_SL, h * 0.098, w * E_SL + 6, h * 0.172],
                fill=tuple(акцент[:3]) + (255,))
    fl = zc.font(FONT_B, 34)
    if подпись1:
        shadow_text(d, (w * E_SL + 0.015 * w, h * 0.096), подпись1, fl,
                    (255, 255, 255, 255))
    if подпись2:
        shadow_text(d, (w * E_SL + 0.015 * w, h * 0.134), подпись2, fl,
                    (255, 255, 255, 255))
    fs = zc.font(FONT_S, 24)
    if канал:                                  # мелкий логотип справа — имя канала
        tw = d.textlength(канал, font=fs)
        d.text((w * E_SR - tw, h * E_ST), канал, font=fs,
               fill=(255, 255, 255, 200))
    fb = zc.font(FONT_B, 84)
    for i, word in enumerate(программа[:2]):
        tw = d.textlength(word, font=fb)
        while tw > w * 0.32 and fb.size > 34:  # длинное русское слово ужимаем
            fb = zc.font(FONT_B, fb.size - 4)
            tw = d.textlength(word, font=fb)
        shadow_text(d, (w * E_SR - tw, h * 0.090 + i * h * 0.080), word, fb,
                    (255, 255, 255, 255) if i == 0 else (200, 222, 255, 255), r=3)
    стр_прог = " ".join(программа)
    П = E_PODEM
    d.rectangle([0, h * (0.858 - П), w * 0.232, h * (0.912 - П)],
                fill=tuple(акцент[:3]) + (255,))
    fp = zc.font(FONT_B, 36)
    while стр_прог and d.textlength(стр_прог, font=fp) > w * 0.17 and fp.size > 18:
        fp = zc.font(FONT_B, fp.size - 2)
    d.text((w * E_SL, h * (0.863 - П)), стр_прог, font=fp,
           fill=tuple(чернила[:3]) + (255,))
    d.rectangle([w * 0.232, h * (0.858 - П), w * 0.790, h * (0.912 - П)],
                fill=(246, 246, 248, 255))
    d.rectangle([w * 0.232, h * (0.912 - П), w * 0.790, h * (0.934 - П)],
                fill=tuple(акцент[:3]) + (255,))
    k = seg(tt, E_LT0, E_LT1)
    if k > 0 and (имя or должность):
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ld.text((w * 0.248, h * (0.860 - П)), имя, font=zc.font(FONT_B, 42),
                fill=(24, 26, 34, 255))
        ld.text((w * 0.248, h * (0.911 - П)), должность, font=zc.font(FONT_S, 18),
                fill=tuple(чернила[:3]) + (255,))
        if город:
            ld.rectangle([w * 0.232, h * (0.826 - П), w * 0.300, h * (0.858 - П)],
                         fill=tuple(акцент[:3]) + (255,))
            ld.text((w * 0.240, h * (0.829 - П)), город, font=zc.font(FONT_S, 20),
                    fill=tuple(чернила[:3]) + (255,))
        xcut = int(w * (0.232 + 0.558 * out_cubic(k)))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rectangle([0, 0, xcut, h], fill=255)
        lay.putalpha(Image.fromarray(np.minimum(np.asarray(lay.split()[3]),
                                                np.asarray(mask))))
        img.alpha_composite(lay)
    показаны = [wd for i, wd in enumerate(слова)
                if tt >= E_SUB0 + i * E_SUB_STEP]
    if показаны:
        f = zc.font(FONT_S, 40)
        lines, cur = [], ""
        for wd in показаны:
            trial = (cur + " " + wd).strip()
            if d.textlength(trial, font=f) > w * 0.62 and cur:
                lines.append(cur)
                cur = wd
            else:
                cur = trial
        lines.append(cur)
        # СУБТИТР ВЫРАСТАЕТ ВВЕРХ ОТ НИЖНЕЙ ГРАНИЦЫ, а не вниз от 0.720, как в
        # образце: на трёх строках он доезжал до плашки с именем и до полосы.
        y = h * (E_SUB_DNO - 0.052 * len(lines))
        for ln in lines:
            shadow_text(d, (w * 0.115, y), ln, f, (255, 255, 255, 255), r=2)
            y += h * 0.052
    return img


_TV_CACHE = {}


def tv_frame(tt, содержание, акцент, чернила):
    """Кадр эфира целиком: студия + оформление на момент `tt`."""
    key = (round(tt, 3), содержание, tuple(акцент), tuple(чернила))
    if key in _TV_CACHE:
        return _TV_CACHE[key]
    img = studio_tex(tt)
    img.alpha_composite(overlay_tex(tt, содержание, акцент, чернила))
    _TV_CACHE.clear()
    _TV_CACHE[key] = img
    return img


def panel_width(dist, yaw, xoff):
    cam = Cam(xoff, E_EYE, E_ZP - dist)
    pts = [cam.proj(p) for p in quad((0.0, E_EYE, E_ZP), E_PANEL_W, E_PANEL_H, yaw=yaw)]
    xs = [p[0] for p in pts]
    return (max(xs) - min(xs)) / W


def dist_for_width(want, yaw, xoff):
    """Дальность камеры, при которой панель занимает долю `want` ширины."""
    lo, hi = 1.0, 16.0
    for _i in range(32):
        mid = (lo + hi) / 2
        if panel_width(mid, yaw, xoff) > want:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def e_camera(t):
    """(камера, наклон панели, доля ширины) по времени приёма."""
    if t < E_FLY0:                                   # зал: лёгкий дрейф вперёд
        want = 0.42 + 0.02 * (t / E_FLY0)
        yaw, xoff = E_YAW0, E_XOFF0
    elif t < E_FULL:                                 # разворот: 0.44 → 1.02
        k = seg(t, E_FLY0, E_FULL)
        want = float(np.interp(k, [0.0, 0.41, 0.82, 1.0], [0.44, 0.57, 0.85, 1.02]))
        e = 1 - (1 - k) ** 2
        yaw, xoff = E_YAW0 * (1 - e), E_XOFF0 * (1 - e)
    elif t < E_BACK0:                                # экран целиком
        want, yaw, xoff = 1.02, 0.0, 0.0
    elif t < E_BACK1:                                # отъезд: мягкая посадка
        k = out_cubic(seg(t, E_BACK0, E_BACK1))
        want = 1.02 + (0.40 - 1.02) * k
        yaw = E_YAW1 * k
        xoff = 0.7 * k
    else:                                            # зал: дрейф назад
        want = 0.40 - 0.015 * seg(t, E_BACK1, E_ПОЛНОЕ)
        yaw, xoff = E_YAW1, 0.7
    d = dist_for_width(want, yaw, xoff)
    return Cam(xoff, E_EYE, E_ZP - d), yaw, want


_LABEL = {}


def hall_label(строки):
    key = tuple(строки)
    if key not in _LABEL:
        if len(_LABEL) > 8:
            _LABEL.clear()
        _LABEL[key] = text_tex(list(строки), fsize=180, cond=0.82)
    return _LABEL[key]


def zal_ekran(out=None, t=None, text="", say="", author="", role="", source="",
              sheets=(), channel="", watermark="", dur=0.0, sfx=None, **_):
    """G25. Панель эфира висит в зале на тросах, РАЗВОРАЧИВАЕТСЯ В ПОЛНЫЙ
    ЭКРАН, держит его и уезжает назад в зал, доворачиваясь до 22°. На панели
    свой эфир: студия, ведущий, оформление, плашка с именем въезжает шторкой,
    реплика набирается словами субтитра.

    Переносит в бой разбор образца 13.11 и ЗАМЕНЯЕТ прежнюю реализацию вида
    `card:zal_ekran` (его слово: «старую удалять, а новую ставить»).

    `text` — фраза сцены: объёмная надпись в зале над панелью. `say` —
    реплика (слова субтитра), `author` и `role` — кто говорит, `source` — где
    и когда сказано, `sheets` — подпись сюжета, название программы и город.

    Возвращает RGB-кадр 1920×1080.
    """
    tt = E_HERO if t is None else _время(t, dur, E_ПОЛНОЕ)
    bg, fg = цвета(channel)
    акц = tuple(bg[:3]) + (255,)

    листы = [str(s).strip() for s in (sheets or ()) if str(s).strip()]
    заголовок = _строки(_первый(листы[0] if листы else "", text), строк=2, знаков=22)
    подпись1 = заголовок[0] if заголовок else ""
    подпись2 = заголовок[1] if len(заголовок) > 1 else ""
    программа = _слова(_первый(листы[1] if len(листы) > 1 else "",
                               " ".join(_слова(text, 2))), 2)
    город = (листы[2] if len(листы) > 2 else "")
    слова_реплики = [w for w in str(say or "").split() if w]
    содержание = (_первый(source), подпись1, подпись2, tuple(программа),
                  _первый(author), _первый(role).upper(), город,
                  tuple(слова_реплики), _первый(watermark, channel).upper())

    tex = tv_frame(tt - E_FULL, содержание, акц, fg)
    cam, yaw, _want = e_camera(tt)
    pc = (0.0, E_EYE, E_ZP)
    corners = quad(pc, E_PANEL_W, E_PANEL_H, yaw=yaw)
    for i, _w in enumerate(слова_реплики):
        _ev(sfx, E_FULL + E_SUB0 + i * E_SUB_STEP, "label")

    if E_FULL <= tt < E_BACK0:
        # Экран целиком: панель чуть больше кадра (1.02), зала под ней не
        # видно — его не считаем, а картинку кладём тем же `paste_quad`, что
        # и в зале, чтобы стык был без скачка.
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        paste_quad(img, tex, [cam.proj(p) for p in corners])
        return _готово(img, out, watermark)

    img = room(cam)
    for fx in (0.10, 0.90):                      # тросы к верхним углам
        px = (fx - 0.5) * E_PANEL_W
        wire(img, cam, (px * math.cos(yaw), E_EYE + E_PANEL_H / 2,
                        E_ZP + px * math.sin(yaw)), color=(92, 94, 98, 230), width=3)
    стр = _строки(text, строк=2, знаков=18)
    if стр:
        lab = hall_label(стр)
        lh = 0.34 * (1 if len(стр) < 2 else 1.6)
        lw = lh * lab.size[0] / lab.size[1]
        # НА ВХОДЕ КАМЕРА БЛИЖЕ ВСЕГО, и двухстрочная русская надпись уходила
        # за верхнюю кромку на 54 px — вписываем её в безопасную рамку
        # (размер и место, ход панели не трогаем).
        цн, lw, lh = _вписать_в_рамку(
            cam, (0.0, E_EYE + E_PANEL_H / 2 + 0.45, E_ZP), lw, lh, yaw=yaw)
        lc = quad(цн, lw, lh, yaw=yaw)
        zc.extrude(img, cam, lc, lab, depth=0.06, steps=4)
    zc.floor_shadow(img, cam, corners, tex)
    zc.reflection(img, cam, corners, tex, strength=0.22)
    body = Image.new("RGBA", (16, 9), (26, 26, 30, 255))
    bc = quad((pc[0] + 0.02 * math.sin(yaw), pc[1], pc[2] + 0.03),
              E_PANEL_W * 1.03, E_PANEL_H * 1.05, yaw=yaw)
    paste_quad(img, body, [cam.proj(p) for p in bc])
    paste_quad(img, tex, [cam.proj(p) for p in corners])
    return _готово(img, out, watermark)


ВИДЫ = {
    "zal_g01": zal_g01,
    "zal_g48": zal_g48,
    "zal_g44": zal_g44,
    "zal_g18": zal_g18,
    "zal_ekran": zal_ekran,
}
