"""Script-free SVG for the eight visuals (D-073 point 6).

A chart draws exactly the rows reports/visuals.py gives, which its table prints beneath it. The
SVG is inline and uses presentation attributes only: no script, no event attribute, no style
attribute or element, and no outside reference. Every mark carries a <title> with its row, series
and value as the table words them. Text takes the page's colour through currentColor, so it reads
in light and dark modes, and the two series colours keep contrast on both backgrounds.
"""

import html

from personal_finance.money import format_cents
from personal_finance.reports.report_text import shown

# Mid-tone blue and orange: each keeps at least 3:1 contrast against both the light page
# (#ffffff) and the dark one (#1d1d1f), as marks need (WCAG 1.4.11).
SERIES_COLOURS = ("#2f6fde", "#d0661f")
WIDTH = 640
LABEL_WIDTH = 220
BAR_WIDTH = 400
BAR_HEIGHT = 14
ROW_GAP = 8
TOP = 28


def attribute(text: str) -> str:
    return html.escape(text, quote=True)


def mark_title(label: str, series: str, value_cents: int, note: str) -> str:
    """A mark's words: its row's label, its series and value, and any note, as the table has
    them."""
    return (f"{shown(label)}: {series} {format_cents(value_cents)}"
            + (f" ({note})" if note else ""))


def chart_svg(chart) -> str:
    """One chart as inline SVG, or nothing when it has no rows."""
    if not chart.rows:
        return ""
    largest = max((abs(value) for row in chart.rows for value in row.values), default=0) or 1
    row_height = len(chart.series) * BAR_HEIGHT + ROW_GAP
    height = TOP + row_height * len(chart.rows) + ROW_GAP
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" width="{WIDTH}" '
             f'height="{height}" viewBox="0 0 {WIDTH} {height}">',
             f"<title>{attribute(chart.title)}</title>",
             f'<text x="0" y="16" font-size="14" font-weight="bold" fill="currentColor">'
             f"{attribute(chart.title)}</text>"]
    for number, (series, colour) in enumerate(zip(chart.series, SERIES_COLOURS)):
        x = LABEL_WIDTH + number * 120
        parts.append(f'<rect x="{x}" y="6" width="10" height="10" fill="{colour}"/>'
                     f'<text x="{x + 14}" y="15" font-size="11" fill="currentColor">'
                     f"{attribute(series)}</text>")
    for index, row in enumerate(chart.rows):
        y = TOP + index * row_height
        parts.append(f'<text x="0" y="{y + BAR_HEIGHT - 3}" font-size="12" '
                     f'fill="currentColor">{attribute(shown(row.label)[:34])}</text>')
        for number, (series, value) in enumerate(zip(chart.series, row.values)):
            length = round(BAR_WIDTH * abs(value) / largest)
            bar_y = y + number * BAR_HEIGHT
            words = attribute(mark_title(row.label, series, value, row.note))
            parts.append(f'<rect x="{LABEL_WIDTH}" y="{bar_y}" width="{max(length, 1)}" '
                         f'height="{BAR_HEIGHT - 2}" fill="{SERIES_COLOURS[number]}">'
                         f"<title>{words}</title></rect>")
    parts.append("</svg>")
    return "".join(parts)
