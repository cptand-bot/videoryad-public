"""Общие примитивы для "богатой" графики документального стиля: карточка-
глава, карточка-факт (concept card), анимированные графики (bars/slider).
Выведено 2026-10-06 на тесте про гриву льва — пользователь прямо попросил
закрепить этот визуальный язык как стандарт, не как запасной вариант на
случай отсутствия футажа, а как инструмент авторитетности для научпопа.

Единая палитра: золото (заголовки/цитаты/подписи-источники, как в
карточке-главы) + бирюза (акцент для данных/графиков — явно отличает
"сюжетную" золотую типографику от "цифровой" бирюзовой). Тёмный почти-
чёрный фон с лёгкой виньеткой и едва заметной сеткой — читается как
HUD/data-viz, не как случайный чёрный экран.

Шрифты: Playfair Display (Regular + Italic) лежат рядом, в fonts/ — грузить
через fontsdir при прожиге ASS (subtitles=...:fontsdir=.../fonts), для PIL
просто ImageFont.truetype(FONT_ITALIC/FONT_REGULAR).
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

W, H = 1920, 1080
FPS = 30

BG0 = (8, 10, 13)
BG1 = (18, 22, 28)
GOLD = (196, 162, 97)
TEAL = (90, 210, 210)
WHITE = (235, 232, 226)
GREY = (140, 148, 158)
INK = (20, 18, 17)  # фон карточки-главы/факта (тёплый почти-чёрный)

_FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_ITALIC = os.path.join(_FD, "PlayfairDisplay-Italic.ttf")
FONT_REGULAR = os.path.join(_FD, "PlayfairDisplay-Regular.ttf")
_SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def hexcolor(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def data_canvas():
    """Тёмный HUD-фон для графиков/чартов: виньетка + едва заметная сетка."""
    im = Image.new("RGB", (W, H), BG0)
    d = ImageDraw.Draw(im)
    for i in range(0, 600, 4):
        a = 1 - i / 600
        c = tuple(int(BG0[k] + (BG1[k] - BG0[k]) * a) for k in range(3))
        d.ellipse((W/2-900+i, H/2-700+i*0.8, W/2+900-i, H/2+700-i*0.8), outline=c)
    grid = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 90):
        gd.line([(x, 0), (x, H)], fill=18)
    for y in range(0, H, 90):
        gd.line([(0, y), (W, y)], fill=18)
    im = Image.composite(Image.new("RGB", (W, H), (60, 70, 85)), im, grid)
    return im


def photo_canvas(src_path, blur=18, brightness=0.45, saturation=0.75, darken=0.35):
    """Фон для карточки-факта: настоящее фото, размытое и затемнённое."""
    from PIL import ImageEnhance
    im = Image.open(src_path).convert("RGB")
    iw, ih = im.size
    scale = max(W / iw, H / ih)
    im = im.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
    x0 = (im.width - W) // 2
    y0 = (im.height - H) // 2
    im = im.crop((x0, y0, x0 + W, y0 + H))
    im = im.filter(ImageFilter.GaussianBlur(blur))
    im = ImageEnhance.Brightness(im).enhance(brightness)
    im = ImageEnhance.Color(im).enhance(saturation)
    dark = Image.new("RGB", (W, H), (10, 8, 7))
    im = Image.blend(im, dark, darken)
    return im


def eyebrow(im, text, alpha=255, y=120, color=GOLD):
    """Золотой мелкий капс-заголовок + тонкая линия — визуальная подпись
    карточек-глав/фактов/чартов, единая на всех типах."""
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = ImageFont.truetype(FONT_REGULAR, 34)
    up = text.upper()
    bbox = d.textbbox((0, 0), up, font=f)
    w = bbox[2] - bbox[0]
    x = (W - w) / 2
    d.text((x, y), up, font=f, fill=color + (alpha,))
    lw = 160
    d.line([(W/2 - lw/2, y + 58), (W/2 + lw/2, y + 58)], fill=color + (alpha,), width=2)
    im.paste(Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB"), (0, 0))


def circle_photo(path, size, border_color, border_w=7):
    src = Image.open(path).convert("RGB")
    src = ImageOps.fit(src, (size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size + border_w * 2, size + border_w * 2), (0, 0, 0, 0))
    out.paste(src, (border_w, border_w), mask)
    ImageDraw.Draw(out).ellipse(
        (border_w // 2, border_w // 2, size + border_w + border_w // 2, size + border_w + border_w // 2),
        outline=border_color, width=border_w)
    return out


def glow_rect(im, box, color, alpha=90, blur=22, pad=10):
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(overlay)
    gd.rectangle((box[0]-pad, box[1]-pad, box[2]+pad, box[3]+pad), fill=color + (alpha,))
    if blur:
        overlay = overlay.filter(ImageFilter.GaussianBlur(blur))
    im.paste(Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def glow_point(im, xy, color, r=10, glow=34, alpha=70):
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse((xy[0]-glow, xy[1]-glow, xy[0]+glow, xy[1]+glow), fill=color+(alpha,))
    overlay = overlay.filter(ImageFilter.GaussianBlur(14))
    im.paste(Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((xy[0]-r, xy[1]-r, xy[0]+r, xy[1]+r), fill=color)


def ease_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def pop_scale(t):
    """0->1: быстрый перелёт за 1.0 (до 1.18x) и усадка — "бульк"-эффект
    появления иконки, не просто fade."""
    t = max(0.0, min(1.0, t))
    if t < 0.6:
        return (t / 0.6) * 1.18
    return 1.18 - (t - 0.6) / 0.4 * 0.18


def render_video(frame_dir, out_mp4, n_frames, draw_fn, fps=FPS):
    """draw_fn(t_seconds) -> PIL.Image, рендерится покадрово и кодируется
    через ffmpeg. Не для долгих роликов (это для коротких вставок-карточек
    на несколько секунд) — кадры лежат как JPEG на диске, затем одной
    командой в libx264."""
    import shutil, subprocess
    if os.path.exists(frame_dir):
        shutil.rmtree(frame_dir)
    os.makedirs(frame_dir)
    for i in range(n_frames):
        t = i / fps
        im = draw_fn(t)
        im.convert("RGB").save(f"{frame_dir}/f_{i:04d}.jpg", quality=92)
    subprocess.run([
        "nice", "-n", "19", "ffmpeg", "-y", "-framerate", str(fps), "-i", f"{frame_dir}/f_%04d.jpg",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        out_mp4
    ], check=True, capture_output=True)
    shutil.rmtree(frame_dir)
    print("ok ->", out_mp4)
