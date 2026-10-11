"""Draw the Nookku logo files in this folder. Standard library only.

The letters are monoline paths, so no font is needed to show the logo.

usage: python docs/assets/logo/make.py
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
INK, PAPER, MARIGOLD = "#12203a", "#f3f6fa", "#d9822b"
STROKE = 9


def stroke(d: str, color: str, width: float = STROKE) -> str:
    return (
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )


def ring(cx: float, cy: float, r: float, color: str, width: float = STROKE) -> str:
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{width}"/>'
    )


def dot(cx: float, cy: float, r: float, color: str) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>'


def wordmark(ink: str) -> list[str]:
    """nookku on a baseline at y = 100, x-height 48. The two o's are eyes that look right."""
    return [
        stroke("M10 52V100M10 72A20 20 0 0 1 50 72V100", ink),
        ring(88, 76, 24, ink),
        ring(150, 76, 24, ink),
        stroke("M188 28V100M218 52L188 82M199 71L220 100", ink),
        stroke("M234 28V100M264 52L234 82M245 71L266 100", ink),
        stroke("M280 52V80A20 20 0 0 0 320 80M320 52V100", ink),
        dot(96, 76, 8.5, MARIGOLD),
        dot(158, 76, 8.5, MARIGOLD),
    ]


def eyes(ink: str) -> list[str]:
    """The mark: the two eyes of the wordmark, on a 128 square."""
    return [
        ring(37, 64, 22, ink, 10),
        ring(91, 64, 22, ink, 10),
        dot(45, 64, 9, MARIGOLD),
        dot(99, 64, 9, MARIGOLD),
    ]


def svg(w: int, h: int, parts: list[str], label: str, bg: str = "", rx: int = 0) -> str:
    back = f'<rect width="{w}" height="{h}" rx="{rx}" fill="{bg}"/>' if bg else ""
    body = "".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'role="img" aria-label="{label}"><title>{label}</title>{back}{body}</svg>\n'
    )


def main() -> None:
    files = {
        "nookku-mark.svg": svg(128, 128, eyes(INK), "Nookku"),
        "nookku-mark-dark.svg": svg(128, 128, eyes(PAPER), "Nookku"),
        "nookku-icon.svg": svg(128, 128, eyes(PAPER), "Nookku", bg=INK, rx=28),
        "nookku-wordmark.svg": svg(332, 112, wordmark(INK), "Nookku"),
        "nookku-wordmark-dark.svg": svg(332, 112, wordmark(PAPER), "Nookku"),
    }
    for name, text in files.items():
        (HERE / name).write_text(text)


if __name__ == "__main__":
    main()
