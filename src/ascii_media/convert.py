"""Turn images and video frames into ASCII art."""

import math
from collections.abc import Callable, Generator
from functools import cache
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

# Rendering constants
CHARSET = np.array(list(" .:-=+*#%@"))  # dark to bright
CELL_SIZE = 10  # pixels per character cell, in width and height
FONT_PATH = Path(__file__).parent / "assets" / "Inconsolata_Expanded-Black.ttf"
SHARPEN = ImageFilter.Kernel((3, 3), [-1, -1, -1, -1, 9, -1, -1, -1, -1], scale=1)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


# Glyph rendering
@cache
def glyph_tiles() -> np.ndarray:
    """Draw each CHARSET character once, white on black, without anti-aliasing.

    Returns an array of shape (len(CHARSET), CELL_SIZE, CELL_SIZE).
    """
    font = ImageFont.truetype(FONT_PATH, 9)
    tiles = []
    for char in CHARSET:
        tile = Image.new("L", (CELL_SIZE, CELL_SIZE))
        draw = ImageDraw.Draw(tile)
        draw.fontmode = "1"  # crisp pixels
        draw.text((0, 0), char, fill=255, font=font)
        tiles.append(np.asarray(tile))
    return np.stack(tiles)


def to_indices(gray: Image.Image, rows: int) -> np.ndarray:
    """Map a grayscale image to a rows x columns grid of CHARSET indices."""
    columns = math.ceil(rows * gray.width / gray.height)  # keep the aspect ratio
    small = gray.resize((columns, rows), Image.Resampling.BILINEAR).filter(SHARPEN)
    return np.asarray(small, dtype=np.uint16) * len(CHARSET) // 256  # 0-255 to 0-9


def render(indices: np.ndarray) -> np.ndarray:
    """Tile the glyphs for each index into one grayscale image."""
    rows, columns = indices.shape
    tiles = glyph_tiles()[indices]  # (rows, columns, cell, cell)
    return tiles.transpose(0, 2, 1, 3).reshape(rows * CELL_SIZE, columns * CELL_SIZE)


def to_text(indices: np.ndarray) -> str:
    """Join the characters for each index into lines, one space apart."""
    return "\n".join(" ".join(row) for row in CHARSET[indices])


# Converters
def convert_image(input_path: Path, output_path: Path, rows: int, text: bool) -> None:
    """Write the ASCII version of an image as a picture or as plain text.

    Applies the EXIF orientation first. Raises OSError when Pillow cannot read
    the input, and ValueError when it cannot save to the output extension.
    """
    with Image.open(input_path) as image:
        rgba = ImageOps.exif_transpose(image).convert("RGBA")  # palettes too
    gray = rgba.convert("L")
    indices = to_indices(gray, rows)

    if text:
        output_path.write_text(to_text(indices), encoding="utf-8")
    else:
        Image.fromarray(render(indices)).save(output_path)


def open_frames(input_path: Path) -> Generator:
    """Start ffmpeg and yield its metadata dict, then each frame as gray bytes."""
    return imageio_ffmpeg.read_frames(
        str(input_path),
        pix_fmt="gray",
        bits_per_pixel=8,  # the default of 24 reads 3 frames at a time
    )


def count_frames(input_path: Path) -> int:
    """Estimate the frame count from the video header, or return 0 if unknown."""
    reader = open_frames(input_path)
    try:
        meta = next(reader)
    except OSError:
        return 0
    finally:
        reader.close()
    return round(meta["duration"] * meta["fps"])


def convert_video(
    input_path: Path,
    output_path: Path,
    rows: int,
    codec: str,
    crf: int,
    on_frame: Callable[[], None] = lambda: None,
) -> None:
    """Encode the ASCII version of each video frame with the bundled ffmpeg.

    Calls on_frame after each written frame. Drops the audio track.
    Raises ValueError when ffmpeg cannot read or decode the input, and OSError
    when ffmpeg cannot encode the output.
    """
    # Open: read the decoded frame size and rate from ffmpeg.
    reader = open_frames(input_path)
    try:
        meta = next(reader)
    except OSError as error:
        raise ValueError(f"Cannot read video: {input_path}") from error
    size = meta["size"]  # after rotation, as ffmpeg outputs it
    columns = math.ceil(rows * size[0] / size[1])
    writer = imageio_ffmpeg.write_frames(
        str(output_path),
        (columns * CELL_SIZE, rows * CELL_SIZE),
        pix_fmt_in="gray",
        fps=meta["fps"] or 30,
        codec=codec,
        quality=None,  # use --crf instead
        macro_block_size=1,  # sizes are multiples of CELL_SIZE, so even
        ffmpeg_log_level="error",
        output_params=["-crf", str(crf), "-preset", "fast"],
    )

    # Encode: stream each rendered frame into ffmpeg.
    try:
        writer.send(None)
        for frame in reader:
            gray = Image.frombytes("L", size, frame)
            writer.send(render(to_indices(gray, rows)))
            on_frame()
    except RuntimeError as error:  # raised by the reader on a broken frame
        raise ValueError(f"Cannot decode video: {input_path}") from error
    finally:
        reader.close()
        writer.close()
