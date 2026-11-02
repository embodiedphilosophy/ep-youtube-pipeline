"""EP YouTube thumbnail renderer (1280x720), modelled on the channel's current look:
art/collage background, teacher cut out on the right, stacked white all-caps headline
in black rounded label boxes on the left, an optional italic serif accent line in EP orange,
a small series badge top-left and a "WITH <TEACHER>" credit."""
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
ASSETS = Path(__file__).resolve().parent.parent / "assets"
SANS = str(ASSETS / "fonts/Montserrat-Black.ttf")
SERIF = str(ASSETS / "fonts/PlayfairDisplay-BoldItalic.ttf")
ORANGE = (232, 86, 52)
LABEL = (12, 12, 12, 235)
WHITE = (255, 255, 255)


# ------------------------------------------------------------------ frame picking
_face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def score_frame(path):
    """Sharp, well-lit frame with one large face, ideally right of centre or centred."""
    img = cv2.imread(str(path))
    if img is None:
        return -1
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sharp = cv2.Laplacian(g, cv2.CV_64F).var()
    faces = () if _face.empty() else _face.detectMultiScale(
        g, 1.1, 6, minSize=(g.shape[1] // 12, g.shape[1] // 12))
    if len(faces) == 0:
        return sharp * 0.1
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    size = (w * h) / (g.shape[0] * g.shape[1])
    bright = g[y:y + h, x:x + w].mean()
    return sharp * (1 + 20 * size) * (1 if 70 < bright < 210 else 0.5)


def pick_frame(paths):
    return max(paths, key=score_frame)


# ------------------------------------------------------------------ helpers
def cover(img, w, h):
    r = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * r + 1), int(img.height * r + 1)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def cutout(frame):
    """Person cut-out via rembg if available; else None."""
    try:
        from rembg import remove, new_session
        return remove(frame, session=new_session("u2net_human_seg"))
    except Exception as e:  # noqa: BLE001
        print("rembg unavailable, using framed photo:", e, file=sys.stderr)
        return None


def font_for(path, size, text):
    f = ImageFont.truetype(path, size)
    try:
        from fontTools.ttLib import TTFont
        cm = TTFont(path).getBestCmap()
        if any(ord(c) not in cm for c in text if not c.isspace()):
            return ImageFont.truetype(SANS, size)  # fall back when diacritics missing
    except Exception:  # noqa: BLE001
        pass
    return f


def wrap(text, font, max_w, draw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    return lines + [cur] if cur else lines


# ------------------------------------------------------------------ render
def render(frame_path, headline, out_path, accent=None, teacher=None, series=None,
           background=None, max_text_w=560, bg_frame=None):
    """headline: 2–6 words, rendered all caps. accent: optional short phrase in italic serif."""
    bg_files = [background] if background else sorted((ASSETS / "backgrounds").glob("*.[jp][pn]g"))
    if bg_files:
        bg = cover(Image.open(random.choice(bg_files)).convert("RGB"), W, H)
    elif bg_frame:  # no art supplied yet: blurred, darkened, tinted frame from the video
        from PIL import ImageEnhance
        bg = cover(Image.open(bg_frame).convert("RGB"), W, H).filter(ImageFilter.GaussianBlur(28))
        bg = ImageEnhance.Brightness(bg).enhance(0.55)
        bg = Image.blend(bg, Image.new("RGB", (W, H), (34, 52, 48)), 0.35)
    else:
        bg = Image.new("RGB", (W, H), (24, 22, 30))
    canvas = bg.convert("RGBA")

    frame = Image.open(frame_path).convert("RGB")
    person = cutout(frame)
    if person is not None:
        bbox = person.getbbox() or (0, 0, person.width, person.height)
        person = person.crop(bbox)
        r = (H * 0.98) / person.height
        person = person.resize((int(person.width * r), int(person.height * r)), Image.LANCZOS)
        if person.width > W * 0.62:
            r2 = W * 0.62 / person.width
            person = person.resize((int(person.width * r2), int(person.height * r2)), Image.LANCZOS)
        shadow = Image.new("RGBA", person.size, (0, 0, 0, 0))
        shadow.putalpha(person.getchannel("A").point(lambda a: int(a * 0.45)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))
        px, py = W - person.width + int(person.width * 0.04), H - person.height
        canvas.alpha_composite(shadow, (px - 10, py + 6))
        canvas.alpha_composite(person, (px, py))
    else:  # framed photo occupying the right ~58%, feathered into the background
        pw = int(W * 0.58)
        ph = cover(frame, pw, H).convert("RGBA")
        mask = Image.linear_gradient("L").rotate(90).resize((pw, H))  # dark left → light right
        mask = mask.point(lambda v: min(255, v * 3))
        ph.putalpha(mask)
        canvas.alpha_composite(ph, (W - pw, 0))

    d = ImageDraw.Draw(canvas)
    x0, pad, gap = 48, 18, 10
    headline = headline.upper()
    size = 96
    while size > 46:
        f = ImageFont.truetype(SANS, size)
        lines = wrap(headline, f, max_text_w, d)
        if len(lines) <= (3 if accent else 4):
            break
        size -= 4
    asize = int(size * 1.05)
    af = font_for(SERIF, asize, accent) if accent else None
    credit_f = ImageFont.truetype(SANS, 20)

    line_h = size * 1.02
    block_h = len(lines) * line_h + (asize * 1.15 if accent else 0) + (34 if teacher else 0) + 2 * pad
    y = max(150, (H - block_h) / 2 + 40)

    # one label box per line, ragged right (as on the channel)
    for ln in lines:
        tw = d.textlength(ln, font=f)
        d.rounded_rectangle([x0, y, x0 + tw + 2 * pad, y + line_h + pad * 0.6], radius=14, fill=LABEL)
        d.text((x0 + pad, y + pad * 0.3), ln, font=f, fill=WHITE)
        y += line_h + gap * 0.2
    if accent:
        tw = d.textlength(accent, font=af)
        d.rounded_rectangle([x0, y, x0 + tw + 2 * pad, y + asize * 1.2], radius=14, fill=LABEL)
        d.text((x0 + pad, y + asize * 0.02), accent, font=af, fill=ORANGE)
        y += asize * 1.2
    if teacher:
        d.text((x0 + pad, y + 8), f"WITH {teacher.upper()}", font=credit_f, fill=WHITE,
               stroke_width=3, stroke_fill=(0, 0, 0))

    if series:
        badge_png = ASSETS / "badges" / f"{series.lower().replace(' ', '-')}.png"
        if badge_png.exists():
            b = Image.open(badge_png).convert("RGBA")
            b.thumbnail((220, 70))
            canvas.alpha_composite(b, (x0, 36))
        else:
            bf = ImageFont.truetype(SANS, 22)
            tw = d.textlength(series.upper(), font=bf)
            d.rounded_rectangle([x0, 36, x0 + tw + 28, 76], radius=10, fill=LABEL)
            d.text((x0 + 14, 44), series.upper(), font=bf, fill=WHITE)

    out = canvas.convert("RGB")
    out.save(out_path, "JPEG", quality=90, optimize=True)  # YouTube limit is 2 MB
    return out_path


if __name__ == "__main__":
    # quick test: python thumbnail.py frame.jpg "What karma actually means" out.jpg
    render(sys.argv[1], sys.argv[2], sys.argv[3], accent=(sys.argv[4] if len(sys.argv) > 4 else None),
           teacher="Test Teacher", series="CHITHEADS")
