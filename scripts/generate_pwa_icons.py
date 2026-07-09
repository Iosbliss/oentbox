"""Generate PWA icons (192px and 512px) for MovieHub."""
from PIL import Image, ImageDraw, ImageFont
import os

OUT_DIR = "/home/z/my-project/moviehub/static/pwa"
os.makedirs(OUT_DIR, exist_ok=True)

# Background gradient (deep dark + red accent)
def make_icon(size, path):
    img = Image.new("RGB", (size, size), (10, 10, 15))
    draw = ImageDraw.Draw(img)
    # Rounded background — dark gradient effect
    # Draw a stylized "M" / play-button hybrid
    # Background: dark with a red diagonal accent
    cx, cy = size // 2, size // 2
    # Outer rounded square (slightly lighter)
    pad = size // 16
    draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=size // 8,
                           fill=(18, 18, 26))
    # Red gradient circle behind the M
    r = int(size * 0.32)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(229, 9, 20))
    # White play triangle (movie symbol)
    tri = int(size * 0.14)
    draw.polygon([
        (cx - tri // 2, cy - tri),
        (cx - tri // 2, cy + tri),
        (cx + tri, cy),
    ], fill=(255, 255, 255))
    # Save
    img.save(path, "PNG", optimize=True)
    print(f"Saved {path} ({size}x{size})")

make_icon(192, os.path.join(OUT_DIR, "icon-192.png"))
make_icon(512, os.path.join(OUT_DIR, "icon-512.png"))

# Also create a smaller favicon-style 32px icon
make_icon(32, os.path.join(OUT_DIR, "icon-32.png"))

# Apple touch icon (just reuse 192)
print("All PWA icons generated.")
