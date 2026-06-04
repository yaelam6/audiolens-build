"""Creates AudioLens v2 icons with v2 badge — for both Mac (.icns) and Windows (.ico)."""
from PIL import Image, ImageDraw, ImageFont
import os, subprocess, sys, tempfile

def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    margin = max(1, int(size * 0.04))
    d.ellipse([margin, margin, size - margin, size - margin],
              fill=(20, 16, 40, 255))

    ring = max(1, int(size * 0.035))
    d.ellipse([margin, margin, size - margin, size - margin],
              outline=(124, 92, 252, 255), width=ring)

    inner_m = int(size * 0.18)
    inner_ring = max(1, int(size * 0.022))
    d.ellipse([inner_m, inner_m, size - inner_m, size - inner_m],
              outline=(160, 130, 255, 180), width=inner_ring)

    cx, cy = size / 2, size / 2
    sym_r = size * 0.26
    sym_ring = max(1, int(size * 0.038))
    d.ellipse([cx - sym_r, cy - sym_r, cx + sym_r, cy + sym_r],
              outline=(255, 255, 255, 255), width=sym_ring)
    dot_r = sym_r * 0.28
    d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
              fill=(255, 255, 255, 255))

    # v2 badge — only draw if large enough to be readable
    if size >= 48:
        font_size = max(6, int(size * 0.18))
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except Exception:
            try:
                font = ImageFont.truetype("/Library/Fonts/Arial.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()

        text = "v2"
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        # Badge background — bottom right area
        pad = max(2, int(size * 0.04))
        bx1 = size - tw - pad * 2 - int(size * 0.06)
        by1 = size - th - pad * 2 - int(size * 0.06)
        bx2 = bx1 + tw + pad * 2
        by2 = by1 + th + pad * 2
        r = max(2, int((by2 - by1) * 0.4))
        d.rounded_rectangle([bx1, by1, bx2, by2], radius=r, fill=(38, 198, 160, 230))

        # Text
        tx = bx1 + pad - bbox[0]
        ty = by1 + pad - bbox[1]
        d.text((tx, ty), text, font=font, fill=(255, 255, 255, 255))

    return img


# ── Windows .ico ──────────────────────────────────────────────────────────────
sizes = [16, 32, 48, 64, 128, 256]
images = [make_icon(s) for s in sizes]
images[0].save(
    "AudioLens.ico",
    format="ICO",
    sizes=[(s, s) for s in sizes],
    append_images=images[1:],
)
print("AudioLens.ico created")

# .icns is macOS-only — skip on Windows
if sys.platform == "darwin":
    iconset_dir = tempfile.mkdtemp(suffix=".iconset")
    size_map = {
        16:   ("icon_16x16.png",     "icon_16x16@2x.png",   32),
        32:   ("icon_32x32.png",     "icon_32x32@2x.png",   64),
        128:  ("icon_128x128.png",   "icon_128x128@2x.png", 256),
        256:  ("icon_256x256.png",   "icon_256x256@2x.png", 512),
        512:  ("icon_512x512.png",   "icon_512x512@2x.png", 1024),
    }
    for base, (name1, name2, double) in size_map.items():
        make_icon(base).save(os.path.join(iconset_dir, name1))
        make_icon(double).save(os.path.join(iconset_dir, name2))
    out_icns = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AudioLens.icns")
    result = subprocess.run(["iconutil", "-c", "icns", iconset_dir, "-o", out_icns], capture_output=True)
    if result.returncode == 0:
        print(f"AudioLens.icns created → {out_icns}")
    else:
        print("iconutil failed:", result.stderr.decode())
