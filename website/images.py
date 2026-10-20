"""Make any uploaded picture fit a fixed frame.

fit_to_frame() crops the picture to the frame's shape (it never stretches or squashes it), resizes it to
exactly the frame size, fixes the rotation that phones store inside the file, puts transparent pictures on
white, and saves a light JPEG. A huge photo straight from a phone becomes a small file, and every blog
cover and doctor photo has the same shape, so the pages stay tidy whatever the staff upload.
"""
import os
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

BLOG_FRAME = (1200, 675)     # 16:9, for blog covers
DOCTOR_FRAME = (640, 800)    # 4:5, for doctor portraits


def fit_to_frame(upload, size, quality=85):
    """Return a ContentFile (a JPEG of exactly `size` pixels) made from the uploaded picture."""
    upload.seek(0)
    img = Image.open(upload)
    img = ImageOps.exif_transpose(img)                      # a photo taken sideways is turned upright
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        white = Image.new("RGB", img.size, (255, 255, 255))
        white.paste(img, mask=img.getchannel("A"))          # transparent areas become white, not black
        img = white
    else:
        img = img.convert("RGB")                            # also turns CMYK and grey pictures into RGB
    # centering slightly above the middle keeps faces in the frame when a tall photo is cropped
    img = ImageOps.fit(img, size, Image.LANCZOS, centering=(0.5, 0.35))
    out = BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    stem = os.path.splitext(os.path.basename(getattr(upload, "name", "") or "image"))[0] or "image"
    return ContentFile(out.getvalue(), name=f"{stem}.jpg")


def needs_fitting(field_file):
    """True when the picture was just uploaded (not saved yet), so it should be fitted before saving."""
    return bool(field_file) and not getattr(field_file, "_committed", True)
