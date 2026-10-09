def print_table(
    headers: list[str],
    rows: list[tuple],
    *,
    sep: str = "  ",
) -> None:
    """Печатает таблицу с выравниванием по левому краю."""
    rows = [tuple(str(c) for c in row) for row in rows]
    widths = [
        max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
        for i, h in enumerate(headers)
    ]

    def fmt(cells) -> str:
        return sep.join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()

    print(fmt(headers))
    print(sep.join("-" * w for w in widths))
    for row in rows:
        print(fmt(row))
