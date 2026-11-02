"""Build-time icon generation for QGrab.

The repo ships the logo as base64 text (static/icons/logo-base64.txt)
because the upload route is text-only. This script decodes it back to
qgrab-logo.webp and derives every PNG icon the manifest/HTML reference.
Run once during the Docker build, before the server starts.
"""
import base64
import pathlib

from PIL import Image

BASE = pathlib.Path(__file__).resolve().parent
if not (BASE / "static").exists():
    BASE = BASE.parent
ICONS = BASE / "static" / "icons"
NAVY = (14, 30, 84)  # the logo's own background colour

raw = base64.b64decode((ICONS / "logo-base64.txt").read_text().strip())
logo_path = ICONS / "qgrab-logo.webp"
logo_path.write_bytes(raw)

img = Image.open(logo_path).convert("RGB")


def save_resized(name: str, size: int) -> None:
    img.resize((size, size), Image.LANCZOS).save(ICONS / name)


save_resized("icon-192.png", 192)
save_resized("icon-512.png", 512)
save_resized("apple-touch-icon.png", 180)

# Maskable: logo at ~80% inside the safe zone, padded with its own navy.
canvas = Image.new("RGB", (512, 512), NAVY)
inner = img.resize((410, 410), Image.LANCZOS)
canvas.paste(inner, (51, 51))
canvas.save(ICONS / "icon-maskable-512.png")

print("icons generated:", sorted(p.name for p in ICONS.glob("*.png")), "+ qgrab-logo.webp")
