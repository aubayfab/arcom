"""Génère arcom.ico (16 à 256 px) : ampoule blanche sur tuile ambrée, lisible sur barre des tâches claire ou sombre.

Usage : python make_icon.py <sortie.ico>
"""
import sys

from PIL import Image, ImageDraw

S = 1024  # dessin en grand puis réduction : bords lissés à toutes les tailles
AMBER = (245, 165, 36, 255)
WHITE = (255, 255, 255, 255)
BASE = (58, 38, 0, 255)


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((48, 48, S - 48, S - 48), radius=220, fill=AMBER)
    cx = S // 2
    d.ellipse((cx - 250, 150, cx + 250, 650), fill=WHITE)                       # ampoule
    d.polygon([(cx - 175, 560), (cx + 175, 560), (cx + 115, 720), (cx - 115, 720)], fill=WHITE)  # col
    d.rounded_rectangle((cx - 125, 735, cx + 125, 790), radius=24, fill=BASE)  # culot
    d.rounded_rectangle((cx - 110, 808, cx + 110, 860), radius=24, fill=BASE)
    d.rounded_rectangle((cx - 60, 876, cx + 60, 912), radius=18, fill=BASE)
    return img


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "arcom.ico"
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    draw().resize((256, 256), Image.LANCZOS).save(out, sizes=[(s, s) for s in sizes])
    print(f"{out} ({', '.join(map(str, sizes))} px)")
