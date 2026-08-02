from __future__ import annotations

from pathlib import Path
from typing import TextIO

import qrcode
from qrcode.image.svg import SvgPathImage


def write_qr_svg(payload: str, destination: str | Path) -> Path:
    """Write a scan-ready SVG QR without requiring Pillow."""
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    image = qrcode.make(payload, image_factory=SvgPathImage, border=4)
    image.save(target)
    return target


def print_qr_ascii(payload: str, stream: TextIO) -> None:
    """Render a terminal QR using only text blocks."""
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    qr.print_ascii(out=stream, invert=True)
