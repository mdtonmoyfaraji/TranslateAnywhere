"""Creates assets/icon.ico for the exe (needs Pillow). No fonts required."""
import os

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# diagonal two-colour disc
for y in range(S):
    for x in range(S):
        if (x - S / 2) ** 2 + (y - S / 2) ** 2 <= (S / 2 - 6) ** 2:
            t = (x + y) / (2 * S)
            img.putpixel((x, y), (int(106 + 32 * t), int(141 - 50 * t), 255, 255))
# simple "T" with a small arrow-ish bar as the mark
d.rectangle((66, 78, 190, 106), fill="white")
d.rectangle((114, 106, 142, 196), fill="white")
d.polygon([(150, 150), (196, 150), (173, 186)], fill="white")
os.makedirs("assets", exist_ok=True)
img.save("assets/icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("assets/icon.ico written")
