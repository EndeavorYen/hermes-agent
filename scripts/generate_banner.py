from PIL import Image, ImageDraw, ImageFilter

W, H = 1145, 240
SCALE = 4
BG = "#07111f"
BG2 = "#0b1730"
PANEL = "#0d1e39"
PANEL2 = "#11284a"
GRID = "#0f2746"
OUTLINE = "#79c3ff"
ACCENT = "#55a8ff"
ACCENT2 = "#2f6fd6"
GLOW = "#9fd8ff"
TEXT_TOP = "#dff4ff"
TEXT_MID = "#8fd0ff"
TEXT_LOW = "#5b98ff"
SHADOW = "#173662"
SUBTLE = "#7ca5d6"
SUBTLE2 = "#4e76a7"

FONT = {
    'A': [
        '0011100',
        '0100010',
        '1000001',
        '1111111',
        '1000001',
        '1000001',
        '1000001',
    ],
    'E': [
        '1111111',
        '1000000',
        '1000000',
        '1111110',
        '1000000',
        '1000000',
        '1111111',
    ],
    'G': [
        '0011110',
        '0100001',
        '1000000',
        '1001111',
        '1000001',
        '0100001',
        '0011110',
    ],
    'H': [
        '1000001',
        '1000001',
        '1000001',
        '1111111',
        '1000001',
        '1000001',
        '1000001',
    ],
    'M': [
        '1000001',
        '1100011',
        '1010101',
        '1001001',
        '1000001',
        '1000001',
        '1000001',
    ],
    'N': [
        '1000001',
        '1100001',
        '1010001',
        '1001001',
        '1000101',
        '1000011',
        '1000001',
    ],
    'R': [
        '1111110',
        '1000001',
        '1000001',
        '1111110',
        '1001000',
        '1000100',
        '1000010',
    ],
    'S': [
        '0111110',
        '1000001',
        '1000000',
        '0111110',
        '0000001',
        '1000001',
        '0111110',
    ],
    'T': [
        '1111111',
        '0001000',
        '0001000',
        '0001000',
        '0001000',
        '0001000',
        '0001000',
    ],
    '-': [
        '0000000',
        '0000000',
        '0000000',
        '1111111',
        '0000000',
        '0000000',
        '0000000',
    ],
}

SMALL_FONT = {
    'A': ['010','101','111','101','101'],
    'B': ['110','101','110','101','110'],
    'C': ['011','100','100','100','011'],
    'D': ['110','101','101','101','110'],
    'E': ['111','110','100','110','111'],
    'F': ['111','110','100','100','100'],
    'G': ['011','100','101','101','011'],
    'H': ['101','101','111','101','101'],
    'I': ['111','010','010','010','111'],
    'K': ['101','101','110','101','101'],
    'L': ['100','100','100','100','111'],
    'M': ['101','111','111','101','101'],
    'N': ['101','111','111','111','101'],
    'O': ['111','101','101','101','111'],
    'P': ['110','101','110','100','100'],
    'R': ['110','101','110','101','101'],
    'S': ['011','100','010','001','110'],
    'T': ['111','010','010','010','010'],
    'X': ['101','101','010','101','101'],
    'U': ['101','101','101','101','111'],
    'V': ['101','101','101','101','010'],
    'W': ['101','101','111','111','101'],
    'Y': ['101','101','010','010','010'],
    ' ': ['000','000','000','000','000'],
    '-': ['000','000','111','000','000'],
}


def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    return int(a + (b - a) * t)


def blend(c1, c2, t):
    a = hex_to_rgb(c1)
    b = hex_to_rgb(c2)
    return tuple(lerp(a[i], b[i], t) for i in range(3))


def draw_gradient_rect(draw, xy, c1, c2):
    x0, y0, x1, y1 = xy
    h = max(1, y1 - y0)
    for i in range(h):
        color = blend(c1, c2, i / max(1, h - 1))
        draw.line((x0, y0 + i, x1 - 1, y0 + i), fill=color)


def draw_bitmap_text(img, text, x, y, pixel=5, spacing=2):
    draw = ImageDraw.Draw(img)
    cursor = x
    for ch in text:
        glyph = FONT[ch]
        gw = len(glyph[0])
        gh = len(glyph)
        # shadow
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == '1':
                    sx = cursor + gx * pixel + pixel
                    sy = y + gy * pixel + pixel
                    draw.rectangle((sx, sy, sx + pixel - 1, sy + pixel - 1), fill=SHADOW)
        # outline
        for oy, ox in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1),(-1,1),(1,-1)]:
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit == '1':
                        px = cursor + gx * pixel + ox
                        py = y + gy * pixel + oy
                        draw.rectangle((px, py, px + pixel - 1, py + pixel - 1), fill=OUTLINE)
        # fill gradient
        for gy, row in enumerate(glyph):
            row_t = gy / max(1, gh - 1)
            fill = blend(TEXT_TOP, TEXT_LOW, row_t)
            for gx, bit in enumerate(row):
                if bit == '1':
                    px = cursor + gx * pixel
                    py = y + gy * pixel
                    draw.rectangle((px, py, px + pixel - 1, py + pixel - 1), fill=fill)
        cursor += gw * pixel + spacing * pixel
    return cursor


def draw_small_text(draw, text, x, y, pixel=3, color=TEXT_MID, spacing=1):
    cursor = x
    for ch in text:
        glyph = SMALL_FONT[ch]
        gw = len(glyph[0])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == '1':
                    px = cursor + gx * pixel
                    py = y + gy * pixel
                    draw.rectangle((px, py, px + pixel - 1, py + pixel - 1), fill=color)
        cursor += gw * pixel + spacing * pixel


def draw_panel(draw, xy, border=ACCENT):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=12, fill=PANEL, outline=border, width=2)
    draw.rounded_rectangle((x0+8, y0+8, x1-8, y1-8), radius=10, outline=PANEL2, width=1)


def draw_grid(draw):
    for x in range(0, W, 48):
        draw.line((x, 0, x, H), fill=GRID, width=1)
    for y in range(0, H, 48):
        draw.line((0, y, W, y), fill=GRID, width=1)


def draw_crest(draw, x, y, scale=8):
    # Hermes-inspired winged staff icon with a stronger silhouette.
    wing = [
        (0,2),(1,1),(2,1),(3,0),(4,1),(5,2),
        (1,3),(2,3),(3,2),(4,3),
        (2,4),(3,4),
    ]
    for px, py in wing:
        draw.rectangle((x + px*scale, y + py*scale, x + (px+1)*scale - 2, y + (py+1)*scale - 2), fill=TEXT_MID)
        rx = x + (15-px)*scale
        draw.rectangle((rx, y + py*scale, rx + scale - 2, y + (py+1)*scale - 2), fill=TEXT_MID)

    staff = [(7,1),(8,1),(7,2),(8,2),(7,3),(8,3),(7,4),(8,4),(7,5),(8,5),(7,6),(8,6),(7,7),(8,7),(7,8),(8,8)]
    for px, py in staff:
        color = TEXT_TOP if py <= 2 else ACCENT
        draw.rectangle((x + px*scale, y + py*scale, x + (px+1)*scale - 2, y + (py+1)*scale - 2), fill=color)

    snakes = [(6,3),(9,3),(6,4),(9,4),(5,5),(10,5),(6,6),(9,6),(6,7),(9,7)]
    for px, py in snakes:
        draw.rectangle((x + px*scale, y + py*scale, x + (px+1)*scale - 2, y + (py+1)*scale - 2), fill=GLOW)

    orb = [(6,0),(7,0),(8,0),(9,0)]
    for px, py in orb:
        draw.rectangle((x + px*scale, y + py*scale, x + (px+1)*scale - 2, y + (py+1)*scale - 2), fill=TEXT_TOP)


def add_scanlines(img):
    overlay = Image.new('RGBA', img.size, (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    for y in range(0, H, 6):
        d.line((0, y, W, y), fill=(255,255,255,10), width=1)
    return Image.alpha_composite(img.convert('RGBA'), overlay)


def main():
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw_gradient_rect(draw, (0, 0, W, H), BG, BG2)
    draw_grid(draw)

    # outer frame
    draw.rounded_rectangle((10, 10, W-10, H-10), radius=18, outline=ACCENT2, width=3)
    draw.rounded_rectangle((22, 22, W-22, H-22), radius=14, outline='#16365f', width=1)

    # left crest panel
    draw_panel(draw, (34, 34, 248, 206), border=OUTLINE)
    draw_crest(draw, 74, 58, scale=7)
    draw_small_text(draw, 'HERMES CORE', 74, 168, pixel=4, color=SUBTLE)

    # right information panel
    draw_panel(draw, (272, 30, 1106, 210), border=ACCENT)
    draw_small_text(draw, 'SELF-IMPROVING AI AGENT', 304, 50, pixel=5, color=GLOW)
    draw_bitmap_text(img, 'HERMES-AGENT', 302, 82, pixel=8, spacing=1)

    # bottom HUD bars with safe padding
    hud_y = 164
    slots = [
        (304, 158, 510, 194, 'MEMORY', ACCENT2),
        (530, 158, 736, 194, 'SKILLS', OUTLINE),
        (756, 158, 1038, 194, 'CONTEXT', '#21446f'),
    ]
    for x0, y0, x1, y1, label, fill in slots:
        draw.rounded_rectangle((x0, y0, x1, y1), radius=8, fill=BG2, outline=ACCENT2, width=1)
        draw.rounded_rectangle((x0 + 10, y0 + 8, x1 - 10, y0 + 18), radius=4, fill=fill)
        draw_small_text(draw, label, x0 + 18, y0 + 22, pixel=4, color=SUBTLE2)

    # top-right tag
    draw_small_text(draw, 'BLUE EDITION', 896, 40, pixel=4, color=SUBTLE)

    img = add_scanlines(img).convert('RGB')
    img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=130, threshold=3))

    for path in ['assets/banner.png', 'landingpage/hermes-agent-banner.png', 'website/static/img/hermes-agent-banner.png']:
        img.save(path)
        print(f'saved {path}')

if __name__ == '__main__':
    main()
