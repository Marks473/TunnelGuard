from functools import lru_cache
from math import cos, sin, tau
from pathlib import Path
from random import Random

from PIL import Image, ImageDraw, ImageFilter


def mix(start, end, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(start, end))


def brand_icon(size):
    image = Image.new("RGBA", (256, 256))
    draw = ImageDraw.Draw(image)
    for y in range(256):
        draw.line((0, y, 255, y), fill=mix((255, 197, 161), (174, 119, 255), y / 255))
    mask = Image.new("L", image.size)
    ImageDraw.Draw(mask).rounded_rectangle((3, 3, 252, 252), 62, fill=255)
    image.putalpha(mask)
    draw.rounded_rectangle((14, 14, 241, 241), 53, outline="#ffe1d3", width=3)
    draw.rounded_rectangle((38, 49, 217, 207), 40, fill="#282044")
    draw.line([(76, 99), (111, 128), (76, 157)], fill="#fff4ed", width=16, joint="curve")
    draw.rounded_rectangle((123, 147, 175, 162), 7, fill="#ffbd9f")
    draw.ellipse((178, 66, 196, 84), fill="#d9bfff")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def orbit(radius, angle, center):
    x = radius * cos(angle)
    y = radius * 0.36 * sin(angle)
    return center[0] + 0.87 * x + .49 * y, center[1] - .49 * x + .87 * y


@lru_cache(maxsize=8)
def launch_art(background, light_theme):
    width, height = 450, 214
    image = Image.new("RGBA", (width, height), background)
    glow = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(glow)
    purple = (173, 125, 243, 122) if light_theme else (104, 61, 209, 153)
    pink = (255, 156, 144, 125) if light_theme else (254, 125, 190, 145)
    draw.ellipse((177, 5, 403, 207), fill=purple)
    draw.ellipse((247, 62, 338, 151), fill=pink)
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(32)))
    draw = ImageDraw.Draw(image)
    center = (288, 108)
    rng = Random(33)
    stars = ("#e1cdf1", "#d1b1e3", "#ae8fc5") if light_theme else ("#423768", "#654f91", "#a88ac0")
    inner_ring, outer_ring = ((148, 95, 179), (223, 206, 245)) if light_theme else ((231, 166, 248), (87, 67, 132))
    for _ in range(92):
        x, y = rng.randint(120, 449), rng.randint(8, 210)
        draw.point((x, y), fill=rng.choice(stars))
    for radius in range(50, 167, 13):
        points = [orbit(radius, step * tau / 160, center) for step in range(161)]
        tint = mix(inner_ring, outer_ring, (radius - 45) / 135)
        draw.line(points, fill=tint, width=1)
    for radius, angle, color in ((89, 1.15, "#febea9"), (128, 2.8, "#c2a8ff"), (154, 0.1, "#faf2ff")):
        x, y = orbit(radius, angle, center)
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
    emblem = brand_icon(66)
    image.alpha_composite(emblem, (center[0] - 33, center[1] - 33))
    return image


def draw_cover_scene(image, accent, scene, light_theme):
    width, height = image.size
    draw = ImageDraw.Draw(image)
    base = (249, 244, 252) if light_theme else (24, 23, 38)
    for x in range(width):
        tint = .13 + .27 * (1 - min(abs(x - 238) / 270, 1))
        draw.line((x, 0, x, height), fill=mix(base, accent, tint if light_theme else tint * .62))
    mist = mix(base, accent, .46)
    haze = mix(base, accent, .31)
    highlight = mix(accent, (255, 255, 255), .43)
    ink = mix(accent, (30, 24, 46), .68)
    subdued = mist if light_theme else mix(base, accent, .32)

    if scene == "orbit":
        for offset, fill in ((26, haze), (12, mist), (0, subdued)):
            line = [(x, round(66 + 13 * sin(x / 28) + offset)) for x in range(76, width + 1, 4)]
            draw.polygon(line + [(width, height), (76, height)], fill=fill)
        draw.polygon([(133, 59), (148, 44), (173, 37), (203, 37), (226, 43),
                      (238, 38), (246, 22), (258, 19), (254, 31), (268, 25),
                      (275, 29), (267, 39), (248, 44), (234, 56), (210, 67),
                      (182, 70), (153, 67)], fill=ink)
        draw.polygon([(149, 62), (176, 55), (204, 59), (224, 54), (213, 64), (180, 69)], fill=highlight)
        draw.ellipse((161, 48, 165, 52), fill=highlight)
        draw.line([(192, 66), (183, 78), (169, 81), (171, 70)], fill=ink, width=3)
    elif scene == "spark":
        draw.ellipse((147, 6, 277, 136), fill=haze)
        draw.ellipse((169, 27, 255, 113), fill=mist)
        for index in range(12):
            angle = index * tau / 12
            draw.line([(212 + radius * cos(angle), 69 + radius * sin(angle)) for radius in (23, 75)],
                      fill=subdued if light_theme else accent, width=1)
        draw.polygon([(209, 19), (220, 57), (260, 67), (220, 78), (209, 116),
                      (197, 78), (157, 67), (197, 56)], fill=ink)
        draw.line((209, 39, 209, 95), fill=highlight, width=3)
        draw.line((181, 67, 237, 67), fill=highlight, width=3)
    elif scene == "terminal":
        draw.rounded_rectangle((129, 21, 270, 86), 9, fill=ink, outline=accent, width=2)
        draw.line((132, 39, 267, 39), fill=accent, width=1)
        for x in (141, 149, 157):
            draw.ellipse((x, 28, x + 3, 31), fill=accent)
        draw.line([(143, 53), (151, 60), (143, 67)], fill=highlight, width=3, joint="curve")
        draw.rounded_rectangle((160, 62, 180, 65), 1, fill=accent)
        draw.line([(193, 66), (204, 66), (213, 50), (223, 72), (230, 59), (254, 59)],
                  fill=accent, width=2, joint="curve")
        draw.line((274, 56, 355, 56), fill=subdued, width=2)
        draw.line((274, 68, 331, 68), fill=subdued, width=2)
    elif scene == "pixels":
        for region, fill in (((132, 52, 174, 93), mist), ((169, 36, 209, 77), subdued),
                             ((205, 17, 250, 61), accent), ((240, 41, 288, 89), ink),
                             ((280, 14, 309, 44), mist), ((301, 58, 341, 99), haze)):
            draw.rectangle(region, fill=fill)
            x, y, right, bottom = region
            draw.line((x, y, right, y, right, bottom), fill=highlight, width=2)
        for x, y in ((151, 67), (221, 31), (256, 56), (314, 70)):
            draw.rectangle((x, y, x + 7, y + 7), fill=highlight)
    elif scene == "wave":
        for shift, fill in ((24, haze), (10, mist), (0, subdued)):
            wave = [(x, round(63 + 15 * sin((x - shift) / 28) + shift)) for x in range(78, width + 1, 5)]
            draw.polygon(wave + [(width, height), (78, height)], fill=fill)
            draw.line(wave, fill=accent, width=1)
        draw.polygon([(147, 73), (170, 51), (195, 37), (220, 35), (242, 42),
                      (253, 50), (265, 51), (253, 57), (237, 55), (216, 46),
                      (201, 51), (180, 68), (160, 77), (146, 87), (149, 78),
                      (136, 79)], fill=ink)
        draw.polygon([(188, 43), (188, 30), (204, 36), (210, 39)], fill=ink)
        draw.ellipse((238, 44, 242, 48), fill=highlight)
    elif scene == "code":
        draw.rounded_rectangle((155, 10, 303, 78), 8, fill=mist, outline=subdued, width=2)
        draw.rounded_rectangle((126, 24, 269, 90), 8, fill=ink, outline=accent, width=2)
        draw.line((128, 41, 267, 41), fill=accent)
        draw.line((151, 43, 151, 86), fill=accent)
        for y, offset, gutter, fill in ((50, 0, 52, highlight), (58, 10, 64, accent),
                                       (66, 10, 43, highlight), (74, 0, 31, accent)):
            draw.line((160 + offset, y, 160 + offset + gutter, y), fill=fill, width=2)
    else:
        draw.rounded_rectangle((160, 25, 239, 84), 12, fill=ink, outline=accent, width=2)
        draw.rounded_rectangle((230, 10, 291, 59), 11, fill=mist)
        draw.line((187, 54, 213, 54), fill=highlight, width=3)
        draw.line((200, 41, 200, 67), fill=highlight, width=3)


@lru_cache(maxsize=18)
def card_art(color, symbol, light_theme):
    accent = tuple(bytes.fromhex(color.lstrip("#")))
    tile = (255, 255, 255) if light_theme else (20, 19, 31)
    glyph = mix(accent, (40, 29, 70), .50) if light_theme else color
    image = Image.new("RGB", (410, 100))
    draw_cover_scene(image, accent, symbol, light_theme)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((17, 14, 69, 66), 13, fill=mix(tile, accent, .23),
                           outline=mix(tile, accent, .72 if light_theme else .65))
    def line(points, width=2):
        draw.line([(x + 43, y + 40) for x, y in points], fill=glyph, width=width, joint="curve")

    if symbol == "orbit":
        draw.ellipse((31, 33, 55, 47), outline=glyph, width=2)
        draw.ellipse((40, 37, 46, 43), fill=glyph)
        draw.ellipse((49, 29, 55, 35), fill=glyph)
    elif symbol == "spark":
        for angle in range(8):
            a = angle * tau / 8
            line([(round(4 * cos(a)), round(4 * sin(a))), (round(12 * cos(a)), round(12 * sin(a)))])
    elif symbol == "terminal":
        line([(-10, -7), (-3, 0), (-10, 7)], 3)
        line([(0, 7), (10, 7)], 3)
    elif symbol == "pixels":
        line([(0, -10), (10, -10), (10, 10), (-10, 10), (-10, -10), (-3, -10)], 3)
        line([(-4, 0), (4, 0)], 2)
    elif symbol == "wave":
        line([(-12, 2), (-6, -5), (0, 2), (6, -5), (12, 2)], 3)
        line([(-12, 8), (-6, 1), (0, 8), (6, 1), (12, 8)])
    elif symbol == "code":
        line([(-4, -8), (-12, 0), (-4, 8)], 2)
        line([(4, -8), (12, 0), (4, 8)], 2)
    else:
        draw.rounded_rectangle((32, 29, 54, 51), 4, outline=glyph, width=2)
        line([(-5, 0), (5, 0)], 2)
        line([(0, -5), (0, 5)], 2)
    return image


if __name__ == "__main__":
    brand_icon(256).save(Path(__file__).with_name("TunnelGuard.ico"),
                         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
