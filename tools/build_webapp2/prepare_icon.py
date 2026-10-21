"""Render the supplied SVG into a Windows icon; needed only for asset updates."""

from pathlib import Path
import struct


def main():
    import resvg_py

    assets = Path(__file__).resolve().parents[2] / "src/program/webapp2/static"
    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = [resvg_py.svg_to_bytes(svg_path=str(assets / "svti-logo.svg"), width=size, height=size)
              for size in sizes]
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in zip(sizes, images):
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    destination = assets / "svti-logo.ico"
    destination.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(images))
    print(f"Icon ready: {destination}")


if __name__ == "__main__":
    main()
