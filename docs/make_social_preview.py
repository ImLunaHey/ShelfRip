"""make_social_preview.py - builds docs/social-preview.png (1280x640), the picture GitHub, Reddit,
Discord and Bluesky show when someone shares a link to the repo.

    python docs/make_social_preview.py

Needs Pillow and the Inter fonts (falls back to Segoe UI on Windows). The right half is a crop of
docs/shelf.png, so re-run this after new screenshots. Upload the result in the repo's
Settings > General > Social preview.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
W, H = 1280, 640
BG, INK, MUTED, LINE = (14, 16, 20), (236, 239, 244), (154, 163, 178), (38, 44, 54)
GOLD, BLUE, GREEN, SHELF = (242, 179, 61), (108, 155, 255), (76, 195, 138), (201, 209, 220)


def font(names, size):
    for n in names:
        for d in ("/usr/share/fonts/opentype/inter", "C:/Windows/Fonts", str(Path.home() / "AppData/Local/Microsoft/Windows/Fonts")):
            p = Path(d) / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # The Shelf Screenshot, Cropped To The Top Row Of Cases, On The Right
    shot = Image.open(HERE / "shelf.png").convert("RGB")
    crop = shot.crop((130, 520, 1445, 1090))  # Four cases, the shelf under them and their names.
    scale = 640 / crop.width
    crop = crop.resize((640, int(crop.height * scale)), Image.LANCZOS)
    x0 = 620
    img.paste(crop, (x0, (H - crop.height) // 2))
    fade = Image.new("L", (W, H), 0)
    fd = ImageDraw.Draw(fade)
    for i in range(90):  # Fade the left edge of the screenshot into the background.
        fd.line([(x0 + i, 0), (x0 + i, H)], fill=255 - int(255 * i / 90))
    fd.rectangle([0, 0, x0, H], fill=255)
    img.paste(Image.new("RGB", (W, H), BG), (0, 0), fade)
    d = ImageDraw.Draw(img)

    # The Mark: Three Spines On A Shelf, As In The App
    k, mx, my = 3.2, 70, 92
    for x, y, w, h, c in ((3, 4, 5, 18, GOLD), (10, 7, 5, 15, BLUE), (17, 5, 5, 17, GREEN), (2, 23, 24, 2.5, SHELF)):
        d.rounded_rectangle([mx + x * k, my + y * k, mx + (x + w) * k, my + (y + h) * k], radius=1.5 * k, fill=c)
    d.text((mx + 100, my + 4), "Shelfrip", font=font(["InterDisplay-Bold.otf", "segoeuib.ttf"], 66), fill=INK)

    # Tagline And Detail
    big = font(["InterDisplay-SemiBold.otf", "seguisb.ttf"], 44)
    y = 250
    for line in ("Put a disc in.", "Get it named for", "your media server."):
        d.text((mx, y), line, font=big, fill=INK)
        y += 56
    small = font(["Inter-Regular.otf", "segoeui.ttf"], 24)
    d.text((mx, y + 18), "Movies, episodes and special features,", font=small, fill=MUTED)
    d.text((mx, y + 50), "ripped with MakeMKV. Free for Windows.", font=small, fill=MUTED)

    # Server Chips Along The Bottom
    chip = font(["Inter-Medium.otf", "segoeui.ttf"], 22)
    cx = mx
    for name in ("Plex", "Jellyfin", "Emby", "Kodi"):
        tw = d.textlength(name, font=chip)
        d.rounded_rectangle([cx, 548, cx + tw + 32, 590], radius=21, fill=(30, 35, 44), outline=LINE)
        d.text((cx + 16, 556), name, font=chip, fill=INK)
        cx += tw + 44

    img.save(HERE / "social-preview.png", optimize=True)
    print("Wrote", HERE / "social-preview.png")


if __name__ == "__main__":
    main()
