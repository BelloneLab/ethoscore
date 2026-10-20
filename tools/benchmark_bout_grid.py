"""Reproduce paired bounded-cache montage timings on generated test footage.

Run from an IDE or ``python tools/benchmark_bout_grid.py``. Requires matplotlib
for PNG/PDF/SVG plots. The baseline uses a 1 MiB cache and the comparison uses
128 MiB. Both encode and validate identical movies. This is a controlled
engineering measurement, not evidence of a general speedup on user footage.
"""
from pathlib import Path
import csv
import statistics
import subprocess
import sys
import tempfile
import time

import numpy as np

# User configuration: synthetic input, paired repetitions, output and styling.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_STEM = PROJECT_ROOT / "tests/artifacts/bout_grid_benchmark"
REPETITIONS = 3
SOURCE_FPS = 12
SOURCE_FRAMES = 36
SOURCE_WIDTH, SOURCE_HEIGHT = 320, 240
CACHE_BUDGETS_MB = (1, 128)
FIGURE_SIZE = (4.5, 3.4)
COLORS = ("#8c9aab", "#247f72")

sys.path.insert(0, str(PROJECT_ROOT))
from annotator_libs.arena_export import ffmpeg_executable
from annotator_libs.bout_grid import GridConfig, GridSource, export_bout_grid


def main():
    """Measure paired wall times, export raw observations and three plots."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUTPUT_STEM.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix="ethoscore-grid-benchmark-") as temporary:
        root = Path(temporary)
        source = root / "synthetic.mkv"
        rng = np.random.default_rng(153)
        frames = rng.integers(30, 210, (SOURCE_FRAMES, SOURCE_HEIGHT, SOURCE_WIDTH, 3), dtype=np.uint8)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.run([ffmpeg_executable(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                        "-s", f"{SOURCE_WIDTH}x{SOURCE_HEIGHT}", "-r", str(SOURCE_FPS), "-i", "pipe:0",
                        "-c:v", "ffv1", str(source)], input=frames.tobytes(), capture_output=True,
                       check=True, creationflags=flags)
        annotations = {i: ["synthetic bout"] for i in range(SOURCE_FRAMES)}
        for repetition in range(REPETITIONS):
            # Alternate order to reduce a systematic filesystem warmup bias.
            for budget in CACHE_BUDGETS_MB[::1 if repetition % 2 == 0 else -1]:
                config = GridConfig(rows=2, columns=2, tile_width=320, tile_height=240,
                                    output_fps=12, page_seconds=9, cache_megabytes=budget)
                start = time.perf_counter()
                result = export_bout_grid([GridSource(source, annotations, f"Arena {i + 1}") for i in range(4)],
                                         "synthetic bout", root / f"run-{repetition}-{budget}", config)
                elapsed = time.perf_counter() - start
                rows.append(dict(repetition=repetition + 1, cache_mb=budget, seconds=elapsed,
                                 frames=result["frames"], fps=result["frames"] / elapsed))
    with OUTPUT_STEM.with_suffix(".csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    medians = [statistics.median(row["seconds"] for row in rows if row["cache_mb"] == budget)
               for budget in CACHE_BUDGETS_MB]
    fig, ax = plt.subplots(figsize=FIGURE_SIZE, layout="constrained")
    ax.bar([0, 1], medians, width=.38, color=COLORS)
    for repetition in range(1, REPETITIONS + 1):
        values = [next(row["seconds"] for row in rows if row["cache_mb"] == budget and row["repetition"] == repetition)
                  for budget in CACHE_BUDGETS_MB]
        ax.plot([0, 1], values, "o-", color="#515d6b", lw=.6, markersize=3, alpha=.6)
    ax.set_xticks([0, 1], ["1 MiB cache", "128 MiB cache"])
    ax.set_ylabel("Export + validation (seconds)")
    ax.set_title("Synthetic looping grid movie", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.supxlabel(f"{REPETITIONS} paired runs; bars show medians.\nGenerated footage only; descriptive timing, no significance test.", fontsize=8)
    for extension in ("png", "pdf", "svg"):
        fig.savefig(OUTPUT_STEM.with_suffix(f".{extension}"), dpi=200)
    plt.close(fig)
    print({"median_seconds": dict(zip(CACHE_BUDGETS_MB, medians)), "csv": str(OUTPUT_STEM.with_suffix('.csv'))})


if __name__ == "__main__":
    main()
