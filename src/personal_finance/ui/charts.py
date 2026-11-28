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

# Mid-tone blue and orange: each keeps at least 3:1 contrast against the light card (#ffffff)
# and the dark one (#202023), as marks need (WCAG 1.4.11).
SERIES_COLOURS = ("#2f6fde", "#d0661f")
# The drawing's own units. It scales to the card's width (D-083 point 4), and at a desktop
# window's width one unit is about one pixel.
WIDTH = 920
LABEL_WIDTH = 200
# Room each side of the bars for a value's words, such as -12345.67.
VALUE_ROOM = 84
BAR_HEIGHT = 16
ROW_GAP = 10
LEGEND_Y = 40
TOP = 56


def attribute(text: str) -> str:
    return html.escape(text, quote=True)


def mark_title(label: str, series: str, value_cents: int, note: str) -> str:
    """A mark's words: its row's label, its series and value, and any note, as the table has
    them."""
    return (f"{shown(label)}: {series} {format_cents(value_cents)}"
            + (f" ({note})" if note else ""))


def chart_svg(chart) -> str:
    """One chart as inline SVG, or nothing when it has no rows. Bars run from a zero line,
    negative values to its left, each labelled with its value as the table words it."""
    if not chart.rows:
        return ""
    values = [value for row in chart.rows for value in row.values]
    below, above = max(0, -min(values)), max(0, max(values))
    extent = (below + above) or 1
    # The bars' span, less room for a value's words on each side a value can reach.
    span = WIDTH - LABEL_WIDTH - VALUE_ROOM * ((below > 0) + 1)
    zero_x = LABEL_WIDTH + (VALUE_ROOM if below else 0) + round(span * below / extent)
    row_height = len(chart.series) * BAR_HEIGHT + ROW_GAP
    height = TOP + row_height * len(chart.rows)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" width="100%" '
             f'viewBox="0 0 {WIDTH} {height}">',
             f"<title>{attribute(chart.title)}</title>",
             f'<text x="0" y="18" font-size="15" font-weight="bold" fill="currentColor">'
             f"{attribute(chart.title)}</text>"]
    for number, (series, colour) in enumerate(zip(chart.series, SERIES_COLOURS)):
        x = number * 130
        parts.append(f'<rect x="{x}" y="{LEGEND_Y - 10}" width="10" height="10" '
                     f'rx="2" fill="{colour}"/>'
                     f'<text x="{x + 15}" y="{LEGEND_Y - 1}" font-size="12" '
                     f'fill="currentColor">{attribute(series)}</text>')
    parts.append(f'<line x1="{zero_x}" y1="{TOP - 6}" x2="{zero_x}" y2="{height - ROW_GAP + 4}" '
                 'stroke="currentColor" stroke-opacity="0.35"/>')
    for index, row in enumerate(chart.rows):
        y = TOP + index * row_height
        label_y = y + (len(chart.series) * BAR_HEIGHT) // 2 + 4
        parts.append(f'<text x="0" y="{label_y}" font-size="13" '
                     f'fill="currentColor">{attribute(shown(row.label)[:30])}</text>')
        for number, (series, value) in enumerate(zip(chart.series, row.values)):
            length = max(round(span * abs(value) / extent), 1)
            bar_x = zero_x - length if value < 0 else zero_x
            bar_y = y + number * BAR_HEIGHT
            words = attribute(mark_title(row.label, series, value, row.note))
            parts.append(f'<rect x="{bar_x}" y="{bar_y}" width="{length}" '
                         f'height="{BAR_HEIGHT - 3}" rx="2" fill="{SERIES_COLOURS[number]}">'
                         f"<title>{words}</title></rect>")
            value_x, anchor = ((bar_x - 6, "end") if value < 0
                               else (zero_x + length + 6, "start"))
            parts.append(f'<text x="{value_x}" y="{bar_y + BAR_HEIGHT - 5}" font-size="11.5" '
                         f'text-anchor="{anchor}" fill="currentColor" fill-opacity="0.8">'
                         f"{format_cents(value)}</text>")
    parts.append("</svg>")
    return "".join(parts)
