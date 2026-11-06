"""Generates synthetic statements for scale tests and measurements (A39)."""

import random
from datetime import date, timedelta

CARD_HEADER = "Date,Description,Debit,Credit\n"
MERCHANTS = [f"SYNTHETIC MERCHANT{number:04d}" for number in range(400)]


def _card_date(day: date) -> str:
    return day.strftime("%m/%d/%Y")


def ordinary_rows(months: int, rows_per_month: int, seed: int = 7) -> list[list[str]]:
    """Varied merchants and amounts, one list of rows per month."""
    generator = random.Random(seed)
    start = date(2024, 1, 1)
    months_of_rows = []
    for month in range(months):
        rows = []
        for _ in range(rows_per_month):
            day = start + timedelta(days=30 * month + generator.randrange(30))
            cents = generator.randrange(100, 20000)
            merchant = generator.choice(MERCHANTS)
            rows.append(f"{_card_date(day)},{merchant},{cents // 100}.{cents % 100:02d},")
        months_of_rows.append(rows)
    return months_of_rows


def dense_rows(months: int, rows_per_month: int) -> list[list[str]]:
    """One merchant and one amount every day: the worst shape for candidate grouping."""
    start = date(2024, 1, 1)
    months_of_rows = []
    for month in range(months):
        rows = [
            f"{_card_date(start + timedelta(days=30 * month + index % 30))},SYNTHETIC CAFE,5.00,"
            for index in range(rows_per_month)
        ]
        months_of_rows.append(rows)
    return months_of_rows


def variant_rows(months: int, rows_per_month: int) -> list[list[str]]:
    """One amount and one merchant with many reference-free spellings in one block."""
    start = date(2024, 1, 1)
    months_of_rows = []
    for month in range(months):
        rows = [
            f"{_card_date(start + timedelta(days=30 * month + index % 30))},"
            f"SYNTHETIC CAFE BRANCH{index % 500:03d}X,5.00,"
            for index in range(rows_per_month)
        ]
        months_of_rows.append(rows)
    return months_of_rows


def with_overlap(months_of_rows: list[list[str]], overlap_fraction: int = 10) -> list[str]:
    """Build one file per month that repeats the end of the month before."""
    files = []
    for position, rows in enumerate(months_of_rows):
        carried = []
        if position:
            previous = months_of_rows[position - 1]
            carried = previous[-(len(previous) // overlap_fraction) :]
        files.append(CARD_HEADER + "".join(f"{row}\n" for row in carried + rows))
    return files
