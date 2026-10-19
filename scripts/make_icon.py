"""Draw the Meliora icon (brand zig-zag on a violet squircle) into an .icns file.

Usage: python scripts/make_icon.py OUT.icns
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from AppKit import (
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSGraphicsContext,
    NSPNGFileType,
    NSRoundLineCapStyle,
    NSRoundLineJoinStyle,
)


def draw_png(size: int, path: Path) -> None:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, "NSDeviceRGBColorSpace", 0, 0
    )
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))

    s = size / 1024
    inset = 100 * s  # Apple's icon grid leaves a margin around the squircle
    rect = ((inset, inset), (size - 2 * inset, size - 2 * inset))
    NSColor.colorWithSRGBRed_green_blue_alpha_(0x5B / 255, 0x4B / 255, 0xC4 / 255, 1).setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 185 * s, 185 * s).fill()

    # Mockup brand path "M3 17 L15 13 L5 9 L15 5 L9 2" in a 20x20 box (y flipped for AppKit).
    pts = [(3, 17), (15, 13), (5, 9), (15, 5), (9, 2)]
    box, off = 824 * s * 0.62, (size - 824 * s * 0.62) / 2
    line = NSBezierPath.bezierPath()
    for i, (x, y) in enumerate(pts):
        p = (off + x / 20 * box, off + (20 - y) / 20 * box)
        line.moveToPoint_(p) if i == 0 else line.lineToPoint_(p)
    line.setLineWidth_(2.2 / 20 * box)
    line.setLineCapStyle_(NSRoundLineCapStyle)
    line.setLineJoinStyle_(NSRoundLineJoinStyle)
    NSColor.whiteColor().setStroke()
    line.stroke()

    NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(str(path), True)


def main(out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Meliora.iconset"
        iconset.mkdir()
        for pt in (16, 32, 128, 256, 512):
            draw_png(pt, iconset / f"icon_{pt}x{pt}.png")
            draw_png(pt * 2, iconset / f"icon_{pt}x{pt}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
