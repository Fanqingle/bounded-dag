"""Render a week-aligned calendar heatmap of daily session counts from workbuddy.db.

The database is opened read-only. Each cell is one calendar day, columns are
ISO weeks (Monday first), and the caption under every cell is the day number.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DB_PATH = Path("C:/Users/Fql18/.workbuddy/workbuddy.db")
OUT_PATH = Path(__file__).resolve().parent / "usage-heatmap.png"
SOURCE_NOTE = "Source: WorkBuddy local sessions table"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

CELL_W = 30
CELL_H = 24
DAY_LABEL_H = 14
COL_GAP = 6
ROW_GAP = 6
LEFT_PAD = 54
TOP_PAD = 96
RIGHT_PAD = 20
BOTTOM_PAD = 76

# Quartile-like bins over positive counts; zero keeps its own neutral color.
BINS = [0, 1, 4, 8, 16]
COLORS = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]
TEXT_DARK = "#1f2937"
TEXT_LIGHT = "#64748b"


def load_counts(db_path: Path) -> tuple[dict[date, int], date, date]:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        values = [
            row[0]
            for row in connection.execute(
                "SELECT created_at FROM sessions WHERE created_at IS NOT NULL"
            )
        ]
    finally:
        connection.close()

    if not values:
        raise RuntimeError("sessions table has no created_at values")

    days: list[date] = []
    for value in values:
        timestamp = value / 1000 if isinstance(value, int) and value > 10**11 else value
        days.append(datetime.fromtimestamp(timestamp).date())

    counts = Counter(days)
    return counts, min(days), max(days)


def color_for(count: int) -> str:
    index = 0
    for bucket in range(1, len(BINS)):
        if count >= BINS[bucket]:
            index = bucket
    return COLORS[index]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["C:/Windows/Fonts/arialbd.ttf"] if bold else []
    ) + ["C:/Windows/Fonts/arial.ttf"]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main() -> None:
    counts, first_day, last_day = load_counts(DB_PATH)

    # Extend to full Monday..Sunday weeks so no cell is clipped.
    grid_start = first_day - timedelta(days=first_day.weekday())
    grid_end = last_day + timedelta(days=6 - last_day.weekday())
    weeks = (grid_end - grid_start).days // 7 + 1

    col_pitch = CELL_W + COL_GAP
    row_pitch = CELL_H + DAY_LABEL_H + ROW_GAP
    width = LEFT_PAD + weeks * col_pitch + RIGHT_PAD
    height = TOP_PAD + 7 * row_pitch + BOTTOM_PAD

    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)

    title_font = font(22, bold=True)
    small_font = font(12)
    month_font = font(13, bold=True)
    day_font = font(11)
    legend_font = font(11)

    header = f"WorkBuddy Sessions per Day  ({first_day.isoformat()} to {last_day.isoformat()})"
    draw.text((LEFT_PAD, 20), header, fill=TEXT_DARK, font=title_font)
    draw.text(
        (LEFT_PAD, 52),
        "Each cell = one day; value = number of sessions created that day.",
        fill=TEXT_LIGHT,
        font=small_font,
    )

    for row, label in enumerate(WEEKDAYS):
        cell_top = TOP_PAD + row * row_pitch
        draw.text(
            (LEFT_PAD - 42, cell_top + CELL_H // 2 - 6),
            label,
            fill=TEXT_LIGHT,
            font=small_font,
        )

    # Month abbreviations are placed once at the first column where the month appears.
    seen_months: set[tuple[int, int]] = set()
    for week_index in range(weeks):
        week_start = grid_start + timedelta(weeks=week_index)
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            key = (day.year, day.month)
            if day < first_day or day > last_day or key in seen_months:
                continue
            seen_months.add(key)
            draw.text(
                (LEFT_PAD + week_index * col_pitch, TOP_PAD - 26),
                MONTHS[day.month - 1],
                fill=TEXT_DARK,
                font=month_font,
            )

    for week_index in range(weeks):
        week_start = grid_start + timedelta(weeks=week_index)
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            if day < first_day or day > last_day:
                continue
            count = counts.get(day, 0)
            x = LEFT_PAD + week_index * col_pitch
            y = TOP_PAD + offset * row_pitch
            draw.rounded_rectangle(
                [x, y, x + CELL_W, y + CELL_H],
                radius=4,
                fill=color_for(count),
                outline="#d1d5db",
                width=1,
            )
            label = str(day.day)
            bbox = draw.textbbox((0, 0), label, font=day_font)
            text_w = bbox[2] - bbox[0]
            draw.text(
                (x + (CELL_W - text_w) / 2, y + CELL_H + 1),
                label,
                fill=TEXT_DARK,
                font=day_font,
            )

    legend_y = TOP_PAD + 7 * row_pitch + 16
    draw.text((LEFT_PAD, legend_y), "Sessions/day:", fill=TEXT_LIGHT, font=legend_font)
    legend_x = LEFT_PAD + 100
    legend_labels = ["0", "1-3", "4-7", "8-15", "16+"]
    for index, label in enumerate(legend_labels):
        x = legend_x + index * (CELL_W + 18)
        draw.rounded_rectangle(
            [x, legend_y - 2, x + CELL_W - 6, legend_y + 16],
            radius=3,
            fill=COLORS[index],
            outline="#d1d5db",
            width=1,
        )
        draw.text((x + 2, legend_y + 20), label, fill=TEXT_LIGHT, font=legend_font)

    draw.text((LEFT_PAD, height - 24), SOURCE_NOTE, fill=TEXT_LIGHT, font=small_font)

    image.save(OUT_PATH)
    print(f"saved: {OUT_PATH}")
    print(f"size: {image.size[0]}x{image.size[1]}")
    print(f"range: {first_day} .. {last_day}")
    print(f"active days: {len(counts)}")


if __name__ == "__main__":
    main()
