"""Compare committed and working-tree arena detection on generated geometry.

Run from an IDE or ``python tools/benchmark_arena_detection.py`` in an environment
with NumPy, OpenCV, and matplotlib. The screenshot is read-only and is used only
for a qualitative preview. Synthetic known boundaries alone produce accuracy
statistics. Timings are descriptive engineering measurements, not significance
tests or evidence about unseen recordings.
"""

from pathlib import Path
import argparse
import csv
import itertools
import statistics
import subprocess
import sys
import time
import types

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


# User configuration: workload, output location, reference, and figure styling.
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "artifacts" / "arena_detection"
BASELINE_REVISION = "d34d1e9"
REPEATS = 9
PNG_DPI = 180
COLORS = ("#7d8797", "#168b77")
ARENA_COLORS = ("#18bddb", "#9470e6", "#efa936", "#32c69c")
SCREENSHOT = Path("C:/Users/andry/AppData/Local/Temp/codex-clipboard-HYw41a.png")
SCREENSHOT_VIDEO_BOUNDS = (37, 185, 1226, 1078)
sys.path.insert(0, str(ROOT))
from annotator_libs.arena_model import detect_arenas
from tests.test_arena_detection import synthetic_scene


def baseline_detector(revision):
    """Load historical model code without changing the checkout or importing UI."""
    source = subprocess.check_output(
        ["git", "show", f"{revision}:annotator_libs/arena_model.py"], cwd=ROOT, text=True)
    module = types.ModuleType("_ethoscore_historical_arena_model")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{revision}:arena_model.py", "exec"), module.__dict__)
    return module.detect_arenas


def rectangle_iou(first, second):
    """Calculate half-open rectangle intersection over union without rasterizing."""
    overlap = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1]))
    area = lambda box: (box[2] - box[0]) * (box[3] - box[1])
    return overlap / (area(first) + area(second) - overlap)


def score(arenas, expected):
    """Match four rectangles by greatest overlap; penalize missing proposals.

    Boundary error is undefined when the count differs and is recorded as blank.
    This prevents a missing dark-floor result from looking geometrically accurate.
    """
    actual = [(a.x, a.y, a.x + a.width, a.y + a.height) for a in arenas]
    if len(actual) != len(expected):
        return 0.0, ""
    matches = max(itertools.permutations(actual),
                  key=lambda boxes: sum(rectangle_iou(a, b) for a, b in zip(boxes, expected)))
    mean_iou = statistics.mean(rectangle_iou(a, b) for a, b in zip(matches, expected))
    max_error = max(abs(x - y) for a, b in zip(matches, expected) for x, y in zip(a, b))
    return mean_iou, max_error


def write_csv(path, rows):
    """Persist complete per-run measurements with explicit column names."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save_figure(figure, stem):
    """Export the same verified layout in PNG, PDF, and editable SVG formats."""
    for extension in ("png", "pdf", "svg"):
        figure.savefig(stem.with_suffix(f".{extension}"), dpi=PNG_DPI, bbox_inches="tight")
    plt.close(figure)


def preview(before, after, output):
    """Show proposed rectangles on the read-only screenshot, without truth claims."""
    image = cv2.imread(str(SCREENSHOT)) if SCREENSHOT.exists() else None
    if image is None:
        image, _ = synthetic_scene()
        subtitle = "Synthetic example; colored lines show proposed crop bounds"
    else:
        x0, y0, x1, y1 = SCREENSHOT_VIDEO_BOUNDS
        image = image[y0:y1, x0:x1].copy()
        subtitle = "Screenshot preview only; existing colored overlays are part of the supplied image"
    figure, axes = plt.subplots(1, 2, figsize=(10, 4.8), layout="constrained")
    for axis, detector, title in zip(axes, (before, after), ("Before: brightness cutoff", "After: boundary edges")):
        axis.imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        for index, arena in enumerate(detector(image)):
            color = ARENA_COLORS[index % len(ARENA_COLORS)]
            axis.add_patch(Rectangle((arena.x, arena.y), arena.width, arena.height,
                                     fill=False, edgecolor=color, linewidth=2))
            axis.text(arena.x + 8, arena.y + 28, str(index + 1), color="white", fontsize=10,
                      bbox={"facecolor": color, "edgecolor": "none", "pad": 2})
        axis.set_title(title, fontsize=12)
        axis.set_axis_off()
    figure.suptitle(subtitle, fontsize=9)
    save_figure(figure, output / "screenshot_before_after")


def main():
    """Measure paired runs, export their summaries, and create compact figures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=BASELINE_REVISION)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    before = baseline_detector(args.baseline)
    scenarios = [("bright floor", dict()), ("dark floor", {"inverted": True}),
                 ("left border", {"border": "left"}), ("no border", {"border": "none"}),
                 ("animals", {"animals": True}),
                 ("illumination", {"border": "none", "gradient": True}),
                 ("shaded floor", {"shaded": True}),
                 ("shaded dark", {"shaded": True, "inverted": True})]
    rows, summaries = [], []
    for name, parameters in scenarios:
        image, expected = synthetic_scene(**parameters)
        for method, detector in (("previous", before), ("current", detect_arenas)):
            detector(image)  # Warm imports and OpenCV kernels before measurement.
        for repeat in range(REPEATS):
            methods = [("previous", before), ("current", detect_arenas)]
            if repeat % 2:
                methods.reverse()  # Alternate order to reduce systematic timing bias.
            for method, detector in methods:
                start = time.perf_counter()
                arenas = detector(image)
                elapsed_ms = 1000 * (time.perf_counter() - start)
                mean_iou, max_error = score(arenas, expected)
                rows.append(dict(scenario=name, method=method, repeat=repeat + 1,
                                 arena_count=len(arenas), mean_iou=mean_iou,
                                 maximum_boundary_error_pixels=max_error, elapsed_ms=elapsed_ms))
        for method in ("previous", "current"):
            subset = [r for r in rows if r["scenario"] == name and r["method"] == method]
            summaries.append(dict(scenario=name, method=method, arena_count=subset[0]["arena_count"],
                                  mean_iou=subset[0]["mean_iou"],
                                  maximum_boundary_error_pixels=subset[0]["maximum_boundary_error_pixels"],
                                  median_ms=statistics.median(r["elapsed_ms"] for r in subset)))
    write_csv(args.output / "runs.csv", rows)
    write_csv(args.output / "summary.csv", summaries)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False})
    figure, axes = plt.subplots(1, 2, figsize=(9, 3.7), layout="constrained")
    positions = np.arange(len(scenarios))
    for index, method in enumerate(("previous", "current")):
        values = [r for r in summaries if r["method"] == method]
        offset = (index - 0.5) * 0.28
        axes[0].bar(positions + offset, [r["mean_iou"] for r in values], width=0.25,
                    label=method.capitalize(), color=COLORS[index])
        axes[1].plot(positions, [r["median_ms"] for r in values], "o-", markersize=4,
                     label=method.capitalize(), color=COLORS[index])
    for axis in axes:
        axis.set_xticks(positions, [name.replace(" ", "\n").replace("illumination", "light\ngradient")
                                    for name, _ in scenarios])
    axes[0].set_ylim(0, 1.08)
    axes[0].set_ylabel("Mean crop intersection / union")
    axes[0].set_title("Known synthetic floor bounds")
    figure.legend(handles=axes[0].get_legend_handles_labels()[0],
                  labels=["Previous", "Current"], frameon=False,
                  loc="outside lower center", ncol=2)
    axes[1].set_ylabel("Median detection time (ms)")
    axes[1].set_title(f"640 × 480 pixels; {REPEATS} repeats per case")
    figure.suptitle("Geometry accuracy and descriptive runtime; no inferential statistics", fontsize=10)
    save_figure(figure, args.output / "benchmark")
    preview(before, detect_arenas, args.output)
    print(args.output / "summary.csv")


if __name__ == "__main__":
    main()
