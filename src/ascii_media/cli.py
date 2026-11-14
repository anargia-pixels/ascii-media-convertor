"""Command-line interface for ascii-media."""

import io
import os
import sys
import time
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from ascii_media import __version__, update
from ascii_media.convert import (
    IMAGE_SUFFIXES,
    convert_image,
    convert_video,
    count_frames,
)

# Help formatting
click.rich_click.TEXT_MARKUP = "rich"
click.rich_click.STYLE_OPTIONS_TABLE_BOX = "SIMPLE"

# rich-click prints each blank-line-separated paragraph on its own line.
EPILOG = """
[bold]Examples[/]

ascii-media cat.png                          [dim]# writes cat-ascii.png[/]

ascii-media cat.png --text                   [dim]# writes cat-ascii.txt[/]

ascii-media clip.mp4 -r 72 -o small.mp4      [dim]# writes a 720p video[/]

ascii-media clip.mp4 -c h264_nvenc           [dim]# encodes on an NVIDIA GPU[/]

ascii-media update                           [dim]# installs the latest release[/]
"""

console = Console(stderr=True)


def default_output(input_path: Path, is_image: bool, text: bool) -> Path:
    """Return INPUT with an -ascii suffix and the extension for the mode."""
    if text:
        suffix = ".txt"
    elif is_image:
        suffix = input_path.suffix
    else:
        suffix = ".mp4"
    return input_path.with_name(f"{input_path.stem}-ascii{suffix}")


# Entry point
def run() -> None:
    """Send `ascii-media update` to the updater and all other input to main."""
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(errors="replace")  # legacy code pages lack ✓ and ━
    update.remove_stale()
    if sys.argv[1:2] == ["update"]:
        update_command.main(sys.argv[2:], prog_name="ascii-media update")
    else:
        main()


# Commands
@click.command(
    epilog=EPILOG,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument(
    "input",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Image or video file to convert.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output file. Default: INPUT name with an -ascii suffix.",
)
@click.option(
    "-r",
    "--rows",
    type=click.IntRange(min=1),
    default=108,
    show_default=True,
    help="Character rows. Output height is ROWS x 10 pixels (108 = 1080p).",
)
@click.option(
    "-t",
    "--text",
    is_flag=True,
    help="Write plain text instead of a picture. Images only.",
)
@click.option(
    "-c",
    "--codec",
    default="libx264",
    show_default=True,
    help="ffmpeg video encoder, such as libx265, h264_nvenc or hevc_amf.",
)
@click.option(
    "--crf",
    type=click.IntRange(0, 51),
    default=23,
    show_default=True,
    help="Video quality. Lower values give better quality and larger files.",
)
@click.version_option(__version__, "-V", "--version", prog_name="ascii-media")
def main(
    input: Path,  # named "input" so --help shows INPUT
    output: Path | None,
    rows: int,
    text: bool,
    codec: str,
    crf: int,
) -> None:
    """Convert an image or a video into ASCII art.

    Images (PNG, JPEG, BMP, WebP, TIFF) become a picture or a text file.
    Every other INPUT is read as a video and written as a video.
    """
    is_image = input.suffix.lower() in IMAGE_SUFFIXES
    if text and not is_image:
        raise click.UsageError("--text works only with image input.")
    output = output or default_output(input, is_image, text)
    started = time.perf_counter()

    try:
        if is_image:
            with console.status(f"Converting {input.name}"):
                convert_image(input, output, rows, text)
        else:
            convert_with_progress(input, output, rows, codec, crf)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    except OSError as error:
        if is_image:
            raise click.ClickException(str(error)) from error
        message = f"ffmpeg could not write {output} with codec {codec!r}."
        raise click.ClickException(f"{message} See the ffmpeg message above.")

    elapsed = time.perf_counter() - started
    console.print(f"[green]✓[/] Wrote [bold]{escape(str(output))}[/] in {elapsed:.1f}s")


def convert_with_progress(
    input_path: Path, output: Path, rows: int, codec: str, crf: int
) -> None:
    """Convert a video and show a frame progress bar on stderr."""
    total = count_frames(input_path) or None  # None shows a pulsing bar
    columns = (
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("frames"),
        TimeElapsedColumn(),
        TextColumn("eta"),
        TimeRemainingColumn(),
    )
    with Progress(*columns, console=console) as progress:
        task = progress.add_task(input_path.name, total=total)
        convert_video(
            input_path,
            output,
            rows,
            codec,
            crf,
            on_frame=lambda: progress.advance(task),
        )


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
def update_command() -> None:
    """Replace this binary with the latest release from GitHub.

    Checks the download against the release SHA256SUMS file.
    """
    if not update.is_standalone():
        raise click.ClickException(
            "update works only for the standalone binary. "
            "From source, run: git pull && uv sync"
        )

    try:
        with console.status("Checking for a new release"):
            tag = update.latest_tag()
        if not update.is_newer(tag):
            console.print(f"[green]✓[/] ascii-media {__version__} is up to date")
            return

        columns = (
            TextColumn(f"[bold]Downloading {tag}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
        )
        with Progress(*columns, console=console) as progress:
            task = progress.add_task("download", total=None)
            new = update.fetch(
                tag,
                on_start=lambda size: progress.update(task, total=size),
                on_chunk=lambda size: progress.advance(task, size),
            )
        exe = update.swap(new)
    except (ValueError, OSError) as error:
        raise click.ClickException(f"Update failed: {error}") from error

    # The binary on disk is now the new release, and PyInstaller would load
    # any further import from it. Print without rich and exit at once.
    sys.stderr.write(f"✓ Updated {exe} to {tag}\n")
    sys.stderr.flush()
    os._exit(0)
