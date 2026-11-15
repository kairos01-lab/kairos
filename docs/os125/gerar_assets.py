#!/usr/bin/env python3
"""Gera a identidade visual mínima do Kairós (OS125).

Fonte vetorial e PNG são produzidos a partir da mesma lista de operações.
Não usa imagens, fontes ou recursos externos: as letras são polilinhas
definidas neste arquivo.

Uso:
    python3 docs/os125/gerar_assets.py
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"

# Paleta
BG_TOP = (10, 16, 30)
BG_BOTTOM = (22, 35, 61)
NAVY = (14, 23, 41)
GOLD = (227, 179, 65)
TEAL = (53, 183, 166)
IVORY = (245, 241, 232)
MUTED = (154, 167, 189)

AUTHOR = "Diego Melo Rodrigues Ferraz"
COPYRIGHT = "Copyright (C) 2026 Diego Melo Rodrigues Ferraz"
LICENSE_NOTE = "CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/"
METHOD = "Python 3 + Pillow 11.1.0; paths geométricos originais; sem fontes externas"

# Letras em grade 4 x 6 (y para baixo). Cada entrada é uma lista de polilinhas.
GLYPHS = {
    "A": [[(0, 6), (2, 0), (4, 6)], [(1, 4), (3, 4)]],
    "C": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5)]],
    "D": [[(0, 0), (0, 6)], [(0, 0), (3, 0), (4, 1), (4, 5), (3, 6), (0, 6)]],
    "E": [[(4, 0), (0, 0), (0, 6), (4, 6)], [(0, 3), (3, 3)]],
    "F": [[(4, 0), (0, 0), (0, 6)], [(0, 3), (3, 3)]],
    "G": [
        [(4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 3), (2, 3)]
    ],
    "H": [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    "I": [[(2, 0), (2, 6)], [(1, 0), (3, 0)], [(1, 6), (3, 6)]],
    "K": [[(0, 0), (0, 6)], [(0, 3), (4, 0)], [(0, 3), (4, 6)]],
    "L": [[(0, 0), (0, 6), (4, 6)]],
    "N": [[(0, 6), (0, 0), (4, 6), (4, 0)]],
    "O": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1)]],
    "R": [
        [(0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)],
        [(2, 3), (4, 6)],
    ],
    "S": [
        [(4, 1), (3, 0), (1, 0), (0, 1), (0, 2), (1, 3), (3, 3), (4, 4), (4, 5), (3, 6), (1, 6), (0, 5)]
    ],
    "T": [[(0, 0), (4, 0)], [(2, 0), (2, 6)]],
    "U": [[(0, 0), (0, 5), (1, 6), (3, 6), (4, 5), (4, 0)]],
    "V": [[(0, 0), (2, 6), (4, 0)]],
}

ADVANCE = 5.4  # unidades por letra, incluindo espaçamento
SPACE_ADVANCE = 2.8
DOT_ADVANCE = 3.4


def rgb_hex(color: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % color


def circle(cx, cy, r, fill=None, stroke=None, width=0, alpha=255):
    return {
        "type": "circle",
        "cx": cx,
        "cy": cy,
        "r": r,
        "fill": fill,
        "stroke": stroke,
        "width": width,
        "alpha": alpha,
    }


def dot(cx, cy, r, color, alpha=255):
    return {
        "type": "dot",
        "cx": cx,
        "cy": cy,
        "r": r,
        "color": color,
        "alpha": alpha,
    }


def line(points, color, width, alpha=255):
    return {
        "type": "polyline",
        "points": points,
        "color": color,
        "width": width,
        "alpha": alpha,
    }


def rect(x0, y0, x1, y1, color, alpha=255):
    return {
        "type": "rect",
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "color": color,
        "alpha": alpha,
    }


def glyph_ops(char: str, x: float, y: float, unit: float, color, width: float):
    """Desenha um caractere. y é o topo da caixa de 6 unidades."""
    ops = []
    if char == " ":
        return ops
    if char == "·":
        ops.append(dot(x + 2 * unit, y + 3 * unit, 0.42 * unit, color))
        return ops
    if char == "Ó":
        # O + acento agudo desenhado como traço.
        ops.extend(glyph_ops("O", x, y, unit, color, width))
        ops.append(
            line(
                [(x + 1.35 * unit, y - 0.35 * unit), (x + 2.75 * unit, y - 1.15 * unit)],
                color,
                width,
            )
        )
        return ops
    for stroke in GLYPHS[char]:
        pts = [(x + px * unit, y + py * unit) for px, py in stroke]
        ops.append(line(pts, color, width))
    return ops


def text_width(text: str, unit: float) -> float:
    width = 0.0
    for char in text:
        if char == " ":
            width += SPACE_ADVANCE * unit
        elif char == "·":
            width += DOT_ADVANCE * unit
        else:
            width += ADVANCE * unit
    # remove o espaçamento final
    if text:
        last = text[-1]
        if last == " ":
            width -= SPACE_ADVANCE * unit
        elif last == "·":
            width -= (ADVANCE - DOT_ADVANCE) * unit
        else:
            width -= (ADVANCE - 4.0) * unit
    return width


def text_ops(text: str, x: float, y: float, unit: float, color, width: float):
    ops = []
    cursor = x
    for char in text:
        ops.extend(glyph_ops(char, cursor, y, unit, color, width))
        if char == " ":
            cursor += SPACE_ADVANCE * unit
        elif char == "·":
            cursor += DOT_ADVANCE * unit
        else:
            cursor += ADVANCE * unit
    return ops


def badge_ops(cx: float, cy: float, r: float):
    """Insígnia circular com K geométrico e ponto teal."""
    ops = [circle(cx, cy, r, fill=NAVY)]
    ops.append(circle(cx, cy, r * 0.95, stroke=GOLD, width=max(2.0, r * 0.028)))
    ops.append(circle(cx, cy, r * 0.88, stroke=TEAL, width=max(1.0, r * 0.008), alpha=90))

    unit = r * 0.1525
    sw = r * 0.102
    x0 = cx - 2 * unit
    y0 = cy - 3 * unit
    for stroke in GLYPHS["K"]:
        pts = [(x0 + px * unit, y0 + py * unit) for px, py in stroke]
        ops.append(line(pts, IVORY, sw))
    ops.append(dot(cx, cy, r * 0.11, TEAL))
    return ops


def banner_ops():
    ops = []
    # Formas geométricas discretas ao fundo.
    ops.append(circle(1040, 320, 292, stroke=GOLD, width=1.4, alpha=30))
    ops.append(circle(1040, 320, 214, stroke=TEAL, width=1.4, alpha=26))
    ops.append(line([(930, 92), (1248, 410)], GOLD, 1.4, alpha=18))
    ops.append(line([(960, 548), (1200, 548)], TEAL, 2.0, alpha=32))

    ops.extend(badge_ops(180, 310, 96))

    unit = 24.0
    x_text = 330.0
    y_text = 238.0
    ops.extend(text_ops("KAIRÓS", x_text, y_text, unit, IVORY, 11.0))
    wordmark_width = text_width("KAIRÓS", unit)

    ops.append(line([(x_text, 410), (x_text + wordmark_width, 410)], GOLD, 4.0))

    tagline = "AFFECTIVE CONTROL · GUARDRAILS · RESEARCH"
    tag_unit = 4.2
    tag_width = text_width(tagline, tag_unit)
    tag_x = x_text + (wordmark_width - tag_width) / 2
    ops.extend(text_ops(tagline, tag_x, 445, tag_unit, MUTED, 1.8))
    return ops


def logo_ops():
    return badge_ops(256, 256, 236)


def svg_document(width, height, title, description, ops, gradient=False):
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f"<title id=\"title\">{escape(title)}</title>",
        f"<desc id=\"desc\">{escape(description)}</desc>",
        "<metadata>"
        + escape(f"{COPYRIGHT}. {LICENSE_NOTE}. {METHOD}.")
        + "</metadata>",
    ]
    if gradient:
        parts.append("<defs>")
        parts.append('<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">')
        parts.append(f'<stop offset="0" stop-color="{rgb_hex(BG_TOP)}"/>')
        parts.append(f'<stop offset="1" stop-color="{rgb_hex(BG_BOTTOM)}"/>')
        parts.append("</linearGradient>")
        parts.append("</defs>")
        parts.append(f'<rect width="{width}" height="{height}" fill="url(#bg)"/>')

    for op in ops:
        alpha = op["alpha"]
        opacity = "" if alpha == 255 else f' opacity="{alpha / 255:.4f}"'
        if op["type"] == "circle":
            attrs = [
                f'cx="{op["cx"]:.2f}"',
                f'cy="{op["cy"]:.2f}"',
                f'r="{op["r"]:.2f}"',
                f'fill="{rgb_hex(op["fill"])}"' if op["fill"] else 'fill="none"',
            ]
            if op["stroke"]:
                attrs.append(f'stroke="{rgb_hex(op["stroke"])}"')
                attrs.append(f'stroke-width="{op["width"]:.2f}"')
            parts.append(f"<circle {' '.join(attrs)}{opacity}/>")
        elif op["type"] == "dot":
            parts.append(
                f'<circle cx="{op["cx"]:.2f}" cy="{op["cy"]:.2f}" r="{op["r"]:.2f}" '
                f'fill="{rgb_hex(op["color"])}"{opacity}/>'
            )
        elif op["type"] == "polyline":
            points = " ".join(f"{x:.2f},{y:.2f}" for x, y in op["points"])
            parts.append(
                f'<polyline points="{points}" fill="none" stroke="{rgb_hex(op["color"])}" '
                f'stroke-width="{op["width"]:.2f}" stroke-linecap="round" '
                f'stroke-linejoin="round"{opacity}/>'
            )
        elif op["type"] == "rect":
            parts.append(
                f'<rect x="{op["x0"]:.2f}" y="{op["y0"]:.2f}" '
                f'width="{op["x1"] - op["x0"]:.2f}" height="{op["y1"] - op["y0"]:.2f}" '
                f'fill="{rgb_hex(op["color"])}"{opacity}/>'
            )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def render_png(width, height, ops, gradient=False, scale=4):
    w, h = width * scale, height * scale
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if gradient:
        for y in range(h):
            color = lerp(BG_TOP, BG_BOTTOM, y / max(1, h - 1))
            draw.line([(0, y), (w, y)], fill=color + (255,))

    for op in ops:
        alpha = op["alpha"]
        target = img
        overlay = None
        if alpha < 255:
            overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            target = overlay
        d = ImageDraw.Draw(target)

        if op["type"] == "circle":
            box = [
                (op["cx"] - op["r"]) * scale,
                (op["cy"] - op["r"]) * scale,
                (op["cx"] + op["r"]) * scale,
                (op["cy"] + op["r"]) * scale,
            ]
            fill = (op["fill"] + (255,)) if op["fill"] else None
            outline = (op["stroke"] + (255,)) if op["stroke"] else None
            d.ellipse(box, fill=fill, outline=outline, width=max(1, round(op["width"] * scale)))
        elif op["type"] == "dot":
            box = [
                (op["cx"] - op["r"]) * scale,
                (op["cy"] - op["r"]) * scale,
                (op["cx"] + op["r"]) * scale,
                (op["cy"] + op["r"]) * scale,
            ]
            d.ellipse(box, fill=op["color"] + (255,))
        elif op["type"] == "polyline":
            pts = [(x * scale, y * scale) for x, y in op["points"]]
            width_px = max(1, round(op["width"] * scale))
            d.line(pts, fill=op["color"] + (255,), width=width_px, joint="curve")
            radius = width_px / 2
            for px, py in (pts[0], pts[-1]):
                d.ellipse(
                    [px - radius, py - radius, px + radius, py + radius],
                    fill=op["color"] + (255,),
                )
        elif op["type"] == "rect":
            d.rectangle(
                [op["x0"] * scale, op["y0"] * scale, op["x1"] * scale, op["y1"] * scale],
                fill=op["color"] + (255,),
            )

        if overlay is not None:
            overlay.putalpha(overlay.getchannel("A").point(lambda v: int(v * alpha / 255)))
            img.alpha_composite(overlay)

    return img.resize((width, height), Image.LANCZOS)


def png_info(title, description):
    info = PngInfo()
    info.add_text("Title", title)
    info.add_text("Author", AUTHOR)
    info.add_text("Copyright", COPYRIGHT)
    info.add_text("Description", description)
    info.add_text("License", LICENSE_NOTE)
    info.add_text("Software", METHOD)
    return info


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)

    banner_desc = (
        "Banner original do Kairós: fundo escuro, insígnia geométrica e letras "
        "desenhadas como paths. Sem imagens, fontes ou recursos de terceiros."
    )
    logo_desc = (
        "Logo original do Kairós: insígnia circular com K geométrico e ponto teal. "
        "Sem imagens, fontes ou recursos de terceiros."
    )

    banner = banner_ops()
    logo = logo_ops()

    (ASSETS / "banner.svg").write_text(
        svg_document(1280, 640, "Kairós — banner", banner_desc, banner, gradient=True),
        encoding="utf-8",
    )
    (ASSETS / "logo.svg").write_text(
        svg_document(512, 512, "Kairós — logo", logo_desc, logo, gradient=False),
        encoding="utf-8",
    )

    render_png(1280, 640, banner, gradient=True).save(
        ASSETS / "banner.png",
        format="PNG",
        optimize=True,
        pnginfo=png_info("Kairós — banner", banner_desc),
    )
    render_png(512, 512, logo, gradient=False).save(
        ASSETS / "logo.png",
        format="PNG",
        optimize=True,
        pnginfo=png_info("Kairós — logo", logo_desc),
    )

    print("gerado:", ASSETS / "banner.svg")
    print("gerado:", ASSETS / "banner.png")
    print("gerado:", ASSETS / "logo.svg")
    print("gerado:", ASSETS / "logo.png")


if __name__ == "__main__":
    main()
