"""Render the reproducible synthetic crop-export benchmark in three formats.

Run from an IDE, or use ``python tools/plot_export_benchmark.py``. The CSV is
produced by ``python -m tests.test_arena_backend --benchmark`` in the application's
Python environment. This plot needs matplotlib only and uses descriptive timing
summaries. Three engineering runs do not support a general performance claim or
an inferential significance test.
"""

from pathlib import Path
import argparse
import csv
import statistics
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# User configuration: paths, figure dimensions, typography, and colors.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = PROJECT_ROOT / "tests" / "artifacts" / "arena_export_benchmark.csv"
OUTPUT_STEM = INPUT_CSV.with_suffix("")
FIGURE_SIZE_INCHES = (4.2, 3.8)
PNG_DPI = 240
FONT_FAMILY = "DejaVu Sans"
FONT_SIZE = 9
SHARED_COLOR = "#167d72"
BASELINE_COLOR = "#6a7484"
PAIR_COLOR = "#c6ccd3"
TEXT_COLOR = "#263343"


def read_paired_timings(path):
    """Validate raw run records and return aligned shared/sequential timings."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Benchmark CSV is empty.")
    by_repeat = {}
    for row in rows:
        if row["validated"].lower() != "true" or int(row["output_frames_each"]) != int(row["source_frames"]):
            raise ValueError("Every plotted export must pass exact frame-count validation.")
        repeat, method = int(row["repeat"]), row["method"]
        if method not in ("shared_decode", "sequential"):
            raise ValueError(f"Unexpected benchmark method: {method}")
        if method in by_repeat.setdefault(repeat, {}):
            raise ValueError("Duplicate benchmark run.")
        elapsed = float(row["elapsed_seconds"])
        if elapsed <= 0:
            raise ValueError("Export durations must be positive.")
        by_repeat[repeat][method] = elapsed
    if any(set(pair) != {"shared_decode", "sequential"} for pair in by_repeat.values()):
        raise ValueError("Each repeat needs one shared and one sequential export.")
    pairs = [by_repeat[repeat] for repeat in sorted(by_repeat)]
    return pairs, rows[0]


def render_benchmark(input_csv=INPUT_CSV, output_stem=OUTPUT_STEM):
    """Draw paired raw observations and medians, then export PNG/PDF/SVG."""
    pairs, workload = read_paired_timings(input_csv)
    shared = [pair["shared_decode"] for pair in pairs]
    baseline = [pair["sequential"] for pair in pairs]
    shared_median = statistics.median(shared)
    baseline_median = statistics.median(baseline)
    speedup = baseline_median / shared_median
    plt.rcParams.update({"font.family": FONT_FAMILY, "font.size": FONT_SIZE,
                         "text.color": TEXT_COLOR, "axes.labelcolor": TEXT_COLOR,
                         "xtick.color": TEXT_COLOR, "ytick.color": TEXT_COLOR,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.linewidth": 0.65, "pdf.fonttype": 42, "svg.fonttype": "none"})
    figure = plt.figure(figsize=FIGURE_SIZE_INCHES)
    axis = figure.add_axes((0.17, 0.35, 0.76, 0.44))
    # Aligned offsets distinguish repeated observations while preserving pairs.
    count = len(pairs)
    for index, pair in enumerate(pairs):
        offset = (index - (count - 1) / 2) * 0.045
        axis.plot((offset, 1 + offset), (pair["shared_decode"], pair["sequential"]),
                  color=PAIR_COLOR, linewidth=0.8, zorder=1)
        axis.scatter(offset, pair["shared_decode"], s=26, color=SHARED_COLOR,
                     edgecolors="white", linewidths=0.5, zorder=3)
        axis.scatter(1 + offset, pair["sequential"], s=26, color=BASELINE_COLOR,
                     edgecolors="white", linewidths=0.5, zorder=3)
    for x, median, color in ((0, shared_median, SHARED_COLOR), (1, baseline_median, BASELINE_COLOR)):
        axis.plot((x - 0.13, x + 0.13), (median, median), color=color, linewidth=1.3, zorder=4)
        axis.text(x + 0.16, median, f"{median:.2f} s", ha="left", va="center", fontsize=8, color=color)
    axis.set_xlim(-0.3, 1.52)
    axis.set_ylim(0, max(baseline + shared) * 1.18)
    axis.set_xticks((0, 1), ("Shared decoder", "Sequential crops"))
    axis.set_ylabel("Validated export time (s)", labelpad=7)
    axis.tick_params(axis="x", length=0, pad=8)
    axis.tick_params(axis="y", width=0.65, length=3)
    axis.yaxis.grid(True, color="#e8ebef", linewidth=0.6)
    axis.set_axisbelow(True)
    figure.text(0.17, 0.94, "Arena crop export", fontsize=13, fontweight="bold", va="top")
    fps = int(workload["fps_num"]) / int(workload["fps_den"])
    subtitle = (f"{workload['arenas']} arenas | {workload['source_width']} × {workload['source_height']} | "
                f"{workload['source_frames']} frames at {fps:.2f} fps")
    figure.text(0.17, 0.855, subtitle, fontsize=7.8, color=BASELINE_COLOR)
    figure.text(0.17, 0.21, f"{speedup:.2f}× faster by median time", fontsize=10,
                color=SHARED_COLOR, fontweight="bold")
    note = (f"Synthetic clip; {count} paired runs. Lines join repeats; short bars mark medians. "
            "Both methods include exact frame-count validation. Timing depends on hardware and video.")
    figure.text(0.17, 0.14, textwrap.fill(note, width=65), va="top",
                fontsize=6.7, linespacing=1.4, color=BASELINE_COLOR)
    output_stem = Path(output_stem)
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    outputs = []
    for extension in ("png", "pdf", "svg"):
        output = output_stem.with_suffix(f".{extension}")
        figure.savefig(output, dpi=PNG_DPI, facecolor="white")
        outputs.append(output)
    plt.close(figure)
    summary = output_stem.with_name(output_stem.name + "_summary.csv")
    with summary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("paired_runs", "shared_median_seconds",
                                                   "sequential_median_seconds", "median_time_ratio"))
        writer.writeheader()
        writer.writerow({"paired_runs": count, "shared_median_seconds": shared_median,
                         "sequential_median_seconds": baseline_median, "median_time_ratio": speedup})
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_CSV)
    parser.add_argument("--output-stem", type=Path, default=OUTPUT_STEM)
    arguments = parser.parse_args()
    for artifact in render_benchmark(arguments.input, arguments.output_stem):
        print(artifact)
