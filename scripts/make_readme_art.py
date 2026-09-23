#!/usr/bin/env python3
"""Generate the themed SVG artwork used by README.md (written to docs/readme/).

Run from anywhere:  python scripts/make_readme_art.py
Pure standard library; edit the text or colours here and re-run.
"""
import math
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "readme"
FONT = "Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif"
MONO = "SFMono-Regular, Menlo, Consolas, Liberation Mono, monospace"
RED, BLUE, BRONZE, GOLD = "#e3262f", "#2a5bff", "#cd7f32", "#ffd9a3"
INK, MUTED, CARD = "#ffffff", "#aab3c8", "#0b0e1a"

DEFS = f"""<defs>
    <radialGradient id="bg" cx="50%" cy="45%" r="75%">
      <stop offset="0" stop-color="#161a2e"/><stop offset="1" stop-color="#05060b"/>
    </radialGradient>
    <radialGradient id="red" cx=".5" cy=".5" r=".5">
      <stop offset="0" stop-color="{RED}" stop-opacity=".55"/><stop offset="1" stop-color="{RED}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="blue" cx=".5" cy=".5" r=".5">
      <stop offset="0" stop-color="{BLUE}" stop-opacity=".55"/><stop offset="1" stop-color="{BLUE}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="bronze" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{GOLD}"/><stop offset=".35" stop-color="#e0914a"/>
      <stop offset=".65" stop-color="#b8692a"/><stop offset="1" stop-color="#7a3f17"/>
    </linearGradient>
    <linearGradient id="title" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#fff1dc"/><stop offset=".45" stop-color="#f0a860"/><stop offset="1" stop-color="#a4561f"/>
    </linearGradient>
    <linearGradient id="rb" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#ff3b45"/><stop offset=".5" stop-color="#ffe9e9"/><stop offset="1" stop-color="#5b83ff"/>
    </linearGradient>
    <linearGradient id="shine" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".45" stop-color="#fff" stop-opacity="0"/>
      <stop offset=".5" stop-color="#fff" stop-opacity=".9"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/>
      <stop offset="1" stop-color="#fff" stop-opacity="0"/>
      <animateTransform attributeName="gradientTransform" type="translate" values="-1 0; 1 0; 1 0" keyTimes="0; .5; 1" dur="4s" repeatCount="indefinite"/>
    </linearGradient>
    <linearGradient id="frame" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{RED}"/><stop offset=".5" stop-color="{BRONZE}"/><stop offset="1" stop-color="{BLUE}"/>
    </linearGradient>
    <linearGradient id="rule" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{RED}" stop-opacity="0"/><stop offset=".3" stop-color="{RED}"/>
      <stop offset=".5" stop-color="{GOLD}"/><stop offset=".7" stop-color="{BLUE}"/>
      <stop offset="1" stop-color="{BLUE}" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="vbar" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{RED}"/><stop offset=".5" stop-color="{BRONZE}"/><stop offset="1" stop-color="{BLUE}"/>
    </linearGradient>
    <linearGradient id="area" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{RED}" stop-opacity=".35"/><stop offset="1" stop-color="{BLUE}" stop-opacity=".08"/>
    </linearGradient>
    <filter id="glow" x="-20%" y="-50%" width="140%" height="200%">
      <feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="softglow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>"""


def svg(w, h, label, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="{label}" font-family="{FONT}">\n  {DEFS}\n{body}\n</svg>\n')


def web(cx, cy, a0, a1, rmax=230, rings=(45, 90, 135, 180, 225), spokes=7):
    out = []
    angs = [a0 + (a1 - a0) * i / (spokes - 1) for i in range(spokes)]
    for a in angs:
        r = math.radians(a)
        out.append(f'<line x1="{cx}" y1="{cy}" x2="{cx + rmax * math.cos(r):.1f}" y2="{cy + rmax * math.sin(r):.1f}"/>')
    for rr in rings:
        pts = [(cx + rr * math.cos(math.radians(a)), cy + rr * math.sin(math.radians(a))) for a in angs]
        d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f} "
        for i in range(1, len(pts)):
            a = math.radians((angs[i - 1] + angs[i]) / 2)
            d += f"Q{cx + rr * .88 * math.cos(a):.1f},{cy + rr * .88 * math.sin(a):.1f} {pts[i][0]:.1f},{pts[i][1]:.1f} "
        out.append(f'<path d="{d}"/>')
    return "\n    ".join(out)


def backdrop(w, h, big=230, small=150, corners="tl tr bl br", stars=()):
    """Dark gradient, red/blue glows, corner webs and twinkles, clipped to the rounded frame."""
    webs = {
        "tl": web(8, 8, 0, 90, big),
        "tr": web(w - 8, 8, 90, 180, big),
        "bl": web(8, h - 8, -90, 0, small, (40, 80, 120)),
        "br": web(w - 8, h - 8, 180, 270, small, (40, 80, 120)),
    }
    twinkles = "\n    ".join(
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" opacity="0"><animate attributeName="opacity" '
        f'values="0;1;0" dur="3s" begin="{b}s" repeatCount="indefinite"/></circle>'
        for x, y, r, b in stars)
    return f"""  <clipPath id="clip"><rect x="8" y="8" width="{w - 16}" height="{h - 16}" rx="22"/></clipPath>
  <g clip-path="url(#clip)">
    <rect width="{w}" height="{h}" fill="url(#bg)"/>
    <ellipse cx="0" cy="{h}" rx="{w * .47:.0f}" ry="{max(h * 1.05, 300):.0f}" fill="url(#red)">
      <animate attributeName="opacity" values=".7;1;.7" dur="5s" repeatCount="indefinite"/></ellipse>
    <ellipse cx="{w}" cy="0" rx="{w * .47:.0f}" ry="{max(h * 1.05, 300):.0f}" fill="url(#blue)">
      <animate attributeName="opacity" values="1;.7;1" dur="5s" repeatCount="indefinite"/></ellipse>
    <g fill="none" stroke="#fff" stroke-opacity=".13" stroke-width="1.4">
    {chr(10).join(webs[c] for c in corners.split())}
    </g>
    {twinkles}
  </g>"""


def frame(w, h):
    return f'  <rect x="8" y="8" width="{w - 16}" height="{h - 16}" rx="22" fill="none" stroke="url(#frame)" stroke-width="3"/>'


def spider(x, y, drop=30, color=RED, scale=1.0):
    """A small spider bobbing on a thread hung from the top edge."""
    return f"""  <line x1="{x}" y1="8" x2="{x}" y2="{y}" stroke="#fff" stroke-opacity=".35">
    <animate attributeName="y2" values="{y};{y + drop};{y}" dur="4s" repeatCount="indefinite"/></line>
  <g><animateTransform attributeName="transform" type="translate" values="0 0;0 {drop};0 0" dur="4s" repeatCount="indefinite"/>
    <g transform="translate({x},{y + 10 * scale}) scale({scale})" fill="{color}" stroke="{color}" stroke-width="2" stroke-linecap="round">
      <ellipse rx="7" ry="9"/><circle cy="-10" r="5"/>
      <path fill="none" d="M-5,-4 L-16,-14 M-6,0 L-18,-3 M-6,4 L-17,10 M-4,7 L-13,18 M5,-4 L16,-14 M6,0 L18,-3 M6,4 L17,10 M4,7 L13,18"/>
    </g></g>"""


def ripple(cx, cy, r0, r1, colors, dur=3.0, width=2):
    """Expanding sonar rings -- the 'tingle'."""
    n = len(colors)
    return "\n".join(
        f'  <circle cx="{cx}" cy="{cy}" r="{r0}" fill="none" stroke="{c}" stroke-width="{width}" opacity="0">'
        f'<animate attributeName="r" values="{r0};{r1}" dur="{dur}s" begin="{dur * i / n:.2f}s" repeatCount="indefinite"/>'
        f'<animate attributeName="opacity" values=".8;0" dur="{dur}s" begin="{dur * i / n:.2f}s" repeatCount="indefinite"/></circle>'
        for i, c in enumerate(colors))


def hero():
    w, h = 1200, 400
    stars = [(120, 300, 2.2, 0), (1080, 95, 2.6, .8), (300, 60, 1.8, 1.6), (900, 340, 2, .4),
             (560, 30, 1.6, 2.1), (1010, 260, 1.8, 1.2), (190, 170, 1.6, 2.6), (760, 370, 1.8, 1.9)]
    body = f"""{backdrop(w, h, stars=stars)}
  <g clip-path="url(#clip)">
{ripple(600, 200, 40, 560, [RED, BLUE, RED, BLUE], dur=6, width=1.5)}
  </g>
{frame(w, h)}
{spider(1080, 140)}
{spider(130, 90, drop=22, color=BLUE, scale=.8)}
  <g text-anchor="middle">
    <text x="600" y="82" font-size="17" font-weight="700" letter-spacing="8" fill="#ff5a5f">HACK THE NORTH 2026  ·  HEAD-WORN WEARABLE</text>
    <text x="600" y="228" font-size="150" font-weight="900" letter-spacing="2" fill="url(#rb)" filter="url(#glow)">SpideyIRL</text>
    <text x="600" y="228" font-size="150" font-weight="900" letter-spacing="2" fill="url(#shine)">SpideyIRL</text>
    <rect x="360" y="258" width="480" height="2" fill="url(#rule)"/>
    <path d="M600,251 l8,8 l-8,8 l-8,-8 Z" fill="{GOLD}"/>
    <text x="600" y="306" font-size="22" font-weight="700" letter-spacing="12" fill="{INK}">A REAL-LIFE SPIDEY SENSE</text>
    <text x="600" y="346" font-size="19" font-style="italic" fill="{MUTED}">Feel where obstacles are. Ask what the camera sees. Hands-free.</text>
  </g>"""
    return svg(w, h, "SpideyIRL: a real-life Spidey Sense. Feel where obstacles are, ask what the camera sees.", body)


def medal(x, y, ribbon_l, ribbon_r):
    return f"""  <g transform="translate({x},{y})">
    <path d="M-22,-78 L-6,-26 L6,-26 L-8,-78 Z" fill="{ribbon_l}"/>
    <path d="M22,-78 L6,-26 L-6,-26 L8,-78 Z" fill="{ribbon_r}"/>
    <circle r="40" fill="url(#bronze)" stroke="#5a2f12" stroke-width="3" filter="url(#softglow)"/>
    <circle r="31" fill="none" stroke="#ffe0b3" stroke-opacity=".55" stroke-width="2" stroke-dasharray="4 4"/>
    <text y="15" text-anchor="middle" font-size="42" font-weight="900" fill="#4a230c">3</text>
  </g>"""


def award():
    w, h = 1200, 400
    stars = [(120, 300, 2.2, 0), (1080, 95, 2.6, .8), (300, 60, 1.8, 1.6), (900, 340, 2, .4),
             (560, 30, 1.6, 2.1), (1010, 260, 1.8, 1.2), (190, 170, 1.6, 2.6), (760, 370, 1.8, 1.9)]
    body = f"""{backdrop(w, h, stars=stars)}
{frame(w, h)}
{spider(1080, 140)}
  <g text-anchor="middle">
    <text x="600" y="72" font-size="17" font-weight="700" letter-spacing="7" fill="#ff5a5f">HACK THE NORTH 2026  ·  AWARD WINNER</text>
{medal(235, 178, RED, BLUE)}
{medal(965, 178, BLUE, RED)}
    <text x="600" y="200" font-size="100" font-weight="900" letter-spacing="2" fill="url(#title)" filter="url(#glow)">3RD PLACE</text>
    <text x="600" y="200" font-size="100" font-weight="900" letter-spacing="2" fill="url(#shine)">3RD PLACE</text>
    <rect x="330" y="232" width="540" height="2" fill="url(#rule)"/>
    <path d="M600,225 l8,8 l-8,8 l-8,-8 Z" fill="{GOLD}"/>
    <text x="600" y="290" font-size="34" font-weight="700" fill="{INK}">QNX: Embedded Systems with QNX that uses AI</text>
    <text x="600" y="338" font-size="19" font-style="italic" fill="{MUTED}">With great power comes great responsibility… and a podium finish.</text>
  </g>"""
    return svg(w, h, "Hack the North 2026 award winner: 3rd Place, QNX: Embedded Systems with QNX that uses AI", body)


def section(n, title, sub, accent):
    w, h = 1200, 150
    body = f"""{backdrop(w, h, big=130, small=90, corners="tr br", stars=[(900, 40, 1.8, 0), (1000, 120, 1.6, 1.4), (640, 30, 1.4, 2.2)])}
  <g clip-path="url(#clip)">
{ripple(1100, 75, 6, 70, [accent, accent, accent], dur=3)}
  </g>
  <circle cx="1100" cy="75" r="6" fill="{accent}" filter="url(#softglow)"/>
{frame(w, h)}
  <text x="120" y="108" text-anchor="middle" font-size="86" font-weight="900" fill="none" stroke="url(#frame)" stroke-width="2.2">{n:02d}</text>
  <rect x="210" y="34" width="4" height="82" rx="2" fill="url(#vbar)"/>
  <text x="240" y="56" font-size="14" font-weight="700" letter-spacing="6" fill="{accent if accent != BLUE else '#6d93ff'}">CHAPTER {n:02d}</text>
  <text x="240" y="97" font-size="42" font-weight="800" fill="{INK}">{title}</text>
  <text x="240" y="126" font-size="17" font-style="italic" fill="{MUTED}">{sub}</text>"""
    return svg(w, h, f"Chapter {n}: {title}. {sub}", body)


def powers():
    w, h = 1200, 340
    cards = [
        (RED, "FEEL WHERE THINGS ARE", ["Eight sensors, eight motors, 45° apart.",
                                        "Something on your left? Left temple buzzes.",
                                        "Closer means faster pulses."]),
        (BRONZE, "ASK WHAT IT IS", ["Say “what's in front of me”.",
                                    "Camera + YOLO + assistant answer",
                                    "out loud. Voice in, voice out."]),
        (BLUE, "NEVER NEEDS THE CLOUD", ["Haptics run on their own QNX Pi:",
                                         "no camera, no cloud, no Wi-Fi, no AI.",
                                         "The tingle keeps tingling."]),
    ]
    parts = [backdrop(w, h, big=150, small=110, stars=[(600, 25, 1.6, .5), (400, 318, 1.6, 1.5), (800, 318, 1.8, 2.5)]),
             frame(w, h)]
    for i, (c, title, lines) in enumerate(cards):
        x, y, cw, ch = 40 + i * 380, 36, 360, 268
        cx, iy = x + cw / 2, y + 78
        parts.append(f'  <rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="18" fill="{CARD}" fill-opacity=".72" stroke="{c}" stroke-opacity=".8" stroke-width="1.5"/>')
        if i == 0:  # head with eight pulsing sensors
            dots = "".join(
                f'<circle cx="{38 * math.sin(math.radians(b)):.1f}" cy="{-38 * math.cos(math.radians(b)):.1f}" r="5" fill="{RED}">'
                f'<animate attributeName="opacity" values="1;.15;1" dur="1.6s" begin="{k * .2:.1f}s" repeatCount="indefinite"/></circle>'
                for k, b in enumerate(range(0, 360, 45)))
            icon = f'<circle r="22" fill="none" stroke="#fff" stroke-width="2"/><path d="M-6,-21 L0,-30 L6,-21" fill="none" stroke="#fff" stroke-width="2"/>{dots}'
        elif i == 1:  # eye inside a detection box
            icon = (f'<path d="M-36,0 Q0,-32 36,0 Q0,32 -36,0 Z" fill="none" stroke="#fff" stroke-width="2"/>'
                    f'<circle r="13" fill="{BRONZE}"><animate attributeName="cx" values="-8;8;-8" dur="4s" repeatCount="indefinite"/></circle>'
                    f'<path d="M-50,-30 h12 M-50,-30 v12 M50,-30 h-12 M50,-30 v12 M-50,30 h12 M-50,30 v-12 M50,30 h-12 M50,30 v-12" stroke="{GOLD}" stroke-width="2.5" fill="none"/>')
        else:  # local chip with a heartbeat
            pins = "".join(f'<path d="M{p},-30 v-8 M{p},30 v8 M-30,{p} h-8 M30,{p} h8" stroke="#6d93ff" stroke-width="2"/>' for p in (-14, 0, 14))
            icon = (f'<rect x="-30" y="-30" width="60" height="60" rx="6" fill="none" stroke="#6d93ff" stroke-width="2"/>{pins}'
                    f'<text y="5" text-anchor="middle" font-family="{MONO}" font-size="14" font-weight="700" fill="#fff">QNX</text>'
                    f'<polyline points="-70,50 -30,50 -20,40 -10,60 0,50 70,50" fill="none" stroke="#6d93ff" stroke-width="2" stroke-dasharray="160" stroke-dashoffset="160">'
                    f'<animate attributeName="stroke-dashoffset" values="160;0;-160" dur="2.4s" repeatCount="indefinite"/></polyline>')
        parts.append(f'  <g transform="translate({cx},{iy})">{icon}</g>')
        tl = "\n    ".join(f'<text x="{cx}" y="{y + 200 + 25 * j}" font-size="15" fill="{MUTED}">{t}</text>' for j, t in enumerate(lines))
        parts.append(f'  <g text-anchor="middle">\n    <text x="{cx}" y="{y + 168}" font-size="19" font-weight="800" letter-spacing="3" fill="{INK}">{title}</text>\n    {tl}\n  </g>')
    return svg(w, h, "Three powers: feel where things are, ask what it is, and it never needs the cloud.", "\n".join(parts))


def chip(x, y, w, text, color, h=32, size=13):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{CARD}" stroke="{color}" stroke-opacity=".75"/>'
            f'<text x="{x + w / 2}" y="{y + h / 2 + size * .36:.1f}" text-anchor="middle" font-family="{MONO}" font-size="{size}" fill="{INK}">{text}</text>')


def devices():
    w, h = 1200, 480
    parts = [backdrop(w, h, big=160, small=120, stars=[(600, 120, 1.8, 0), (600, 400, 1.6, 1.3)]), frame(w, h)]
    parts.append(f'  <text x="600" y="44" text-anchor="middle" font-size="17" font-style="italic" fill="{MUTED}">Both Pis ride on the same headband, linked for proximity alerts. The reflexes never wait on the brain.</text>')
    # Left: Spidey Sense Pi
    lx, cy0 = 40, 70
    parts.append(f'  <rect x="{lx}" y="{cy0}" width="500" height="380" rx="18" fill="{CARD}" fill-opacity=".75" stroke="{RED}" stroke-width="1.5"/>')
    parts.append(f'  <text x="{lx + 250}" y="{cy0 + 36}" text-anchor="middle" font-size="20" font-weight="800" letter-spacing="4" fill="#ff5a5f">SPIDEY SENSE PI</text>')
    parts.append(f'  <text x="{lx + 250}" y="{cy0 + 58}" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{MUTED}">QNX · C firmware · firmware/</text>')
    steps = ["8× ultrasonic sensors", "validate", "median filter", "band + hysteresis", "pulse-rate pattern", "8× vibration motors"]
    for k, s in enumerate(steps):
        y = cy0 + 78 + k * 46
        parts.append("  " + chip(lx + 110, y, 280, s, RED))
        if k:
            parts.append(f'  <path d="M{lx + 250},{y - 12} v8 m-5,-5 l5,5 l5,-5" stroke="{RED}" stroke-width="2" fill="none"/>')
    parts.append(f'  <circle cx="{lx + 250}" r="5" fill="#ff5a5f" filter="url(#softglow)"><animate attributeName="cy" values="{cy0 + 94};{cy0 + 94 + 5 * 46}" dur="2.2s" repeatCount="indefinite"/>'
                 f'<animate attributeName="opacity" values="0;1;1;0" dur="2.2s" repeatCount="indefinite"/></circle>')
    parts.append(f'  <text x="{lx + 250}" y="{cy0 + 362}" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{MUTED}">local · no network · no camera · no AI · ~200 ms loop</text>')
    # Right: Eyes & Voice
    rx = 660
    parts.append(f'  <rect x="{rx}" y="{cy0}" width="500" height="380" rx="18" fill="{CARD}" fill-opacity=".75" stroke="{BLUE}" stroke-width="1.5"/>')
    parts.append(f'  <text x="{rx + 250}" y="{cy0 + 36}" text-anchor="middle" font-size="20" font-weight="800" letter-spacing="4" fill="#6d93ff">EYES &amp; VOICE</text>')
    parts.append(f'  <text x="{rx + 250}" y="{cy0 + 58}" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{MUTED}">Linux Pi or laptop · Python · main.py</text>')
    rows = [(["camera", "YOLO tracker", "SceneState"], "LOCAL", BLUE),
            (["mic", "Vosk STT", "commands"], "OFFLINE", BLUE),
            (["question", "frame + audio", "OMNI"], "CLOUD*", BRONZE),
            (["answer", "Piper TTS", "speaker"], "OFFLINE", BLUE)]
    for k, (cells, tag, tc) in enumerate(rows):
        y = cy0 + 96 + k * 62
        for j, c in enumerate(cells):
            x = rx + 18 + j * 137
            parts.append("  " + chip(x, y, 112, c, BLUE))
            if j:
                parts.append(f'  <path d="M{x - 21},{y + 16} h14 m-5,-5 l5,5 l-5,5" stroke="#6d93ff" stroke-width="2" fill="none"/>')
        parts.append(f'  <rect x="{rx + 418}" y="{y + 6}" width="66" height="20" rx="10" fill="{tc}" fill-opacity=".2" stroke="{tc}"/>'
                     f'<text x="{rx + 451}" y="{y + 20}" text-anchor="middle" font-size="11" font-weight="700" letter-spacing="1" fill="{INK}">{tag}</text>')
    parts.append(f'  <text x="{rx + 250}" y="{cy0 + 362}" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{MUTED}">* cloud is opt-in (--cloud) · one frame at a time</text>')
    # Proof-of-concept link: proximity alerts flow from the reflex Pi to the voice host
    parts.append(f'  <rect x="542" y="258.5" width="114" height="3" rx="1.5" fill="url(#frame)"/>'
                 f'<path d="M648,253 l10,7 l-10,7" fill="none" stroke="{BLUE}" stroke-width="3" stroke-linecap="round"/>'
                 + "".join(f'<circle cx="545" cy="260" r="4" opacity="0" fill="{GOLD}" filter="url(#softglow)">'
                           f'<animate attributeName="cx" values="545;655" dur="1.5s" begin="{b}s" repeatCount="indefinite"/>'
                           f'<animate attributeName="opacity" values="0;1;1;0" dur="1.5s" begin="{b}s" repeatCount="indefinite"/></circle>'
                           for b in (0, .5, 1.0))
                 + f'<circle cx="600" cy="260" r="17" fill="#05060b" stroke="{GOLD}" stroke-width="2"/>'
                 f'<path d="M591,260 a5,5 0 0 1 5,-5 h4 M609,260 a5,5 0 0 1 -5,5 h-4 M595,260 h10" fill="none" stroke="{GOLD}" stroke-width="2.5" stroke-linecap="round"/>'
                 f'<text x="600" y="228" text-anchor="middle" font-size="13" font-weight="700" letter-spacing="3" fill="{GOLD}">LINKED</text>'
                 f'<text x="600" y="298" text-anchor="middle" font-size="12" font-style="italic" fill="{MUTED}">proximity alerts</text>'
                 f'<text x="600" y="314" text-anchor="middle" font-size="11" font-weight="700" letter-spacing="1" fill="{BRONZE}">PROOF OF CONCEPT</text>')
    return svg(w, h, "Two devices: the QNX Spidey Sense Pi runs sensors to motors locally; the Eyes and Voice host runs camera, speech and the optional cloud assistant. A proof-of-concept link carries proximity alerts from the Spidey Sense Pi to the Eyes and Voice host.", "\n".join(parts))


def directions():
    w, h = 1200, 560
    cx, cy = 360, 280
    chans = [("front", 0, "A"), ("front_right", 45, "B"), ("right", 90, "A"), ("rear_right", 135, "B"),
             ("rear", 180, "A"), ("rear_left", 225, "B"), ("left", 270, "A"), ("front_left", 315, "B")]
    parts = [backdrop(w, h, big=180, small=130, stars=[(640, 60, 1.8, 0), (1100, 480, 1.6, 1.1), (660, 500, 1.6, 2)]), frame(w, h)]

    def pt(r, b):
        return cx + r * math.sin(math.radians(b)), cy - r * math.cos(math.radians(b))

    for k, (name, b, g) in enumerate(chans):
        col = RED if g == "A" else BLUE
        lite = "#ff5a5f" if g == "A" else "#6d93ff"
        (x1, y1), (x2, y2) = pt(95, b - 11), pt(95, b + 11)
        (x3, y3), (x4, y4) = pt(205, b + 11), pt(205, b - 11)
        parts.append(f'  <path d="M{x1:.1f},{y1:.1f} A95,95 0 0 1 {x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} A205,205 0 0 0 {x4:.1f},{y4:.1f} Z" fill="{col}" fill-opacity=".16" stroke="{col}" stroke-opacity=".5"/>')
        (sx, sy), (ex, ey) = pt(95, b), pt(205, b)
        begin = (k % 2) * 1.0  # groups fire alternately
        parts.append(f'  <circle r="5" fill="{lite}" filter="url(#softglow)" opacity="0">'
                     f'<animate attributeName="cx" values="{sx:.1f};{ex:.1f}" dur="2s" begin="{begin}s" repeatCount="indefinite"/>'
                     f'<animate attributeName="cy" values="{sy:.1f};{ey:.1f}" dur="2s" begin="{begin}s" repeatCount="indefinite"/>'
                     f'<animate attributeName="opacity" values="0;1;0" dur="2s" begin="{begin}s" repeatCount="indefinite"/></circle>')
        parts.append(f'  <circle cx="{sx:.1f}" cy="{sy:.1f}" r="7" fill="{col}" stroke="#fff" stroke-width="1.5"/>')
        lx, ly = pt(238, b)
        s = math.sin(math.radians(b))
        anchor = "start" if s > .3 else "end" if s < -.3 else "middle"
        parts.append(f'  <text x="{lx:.1f}" y="{ly - 2:.1f}" text-anchor="{anchor}" font-family="{MONO}" font-size="15" font-weight="700" fill="{INK}">{name}</text>'
                     f'<text x="{lx:.1f}" y="{ly + 16:.1f}" text-anchor="{anchor}" font-family="{MONO}" font-size="12" fill="{MUTED}">{b}° · motor_{k}</text>')
    parts.append(f'  <g transform="translate({cx},{cy})"><ellipse rx="62" ry="74" fill="#12162a" stroke="#fff" stroke-opacity=".6" stroke-width="2"/>'
                 f'<ellipse cx="-64" rx="8" ry="16" fill="#12162a" stroke="#fff" stroke-opacity=".6" stroke-width="2"/>'
                 f'<ellipse cx="64" rx="8" ry="16" fill="#12162a" stroke="#fff" stroke-opacity=".6" stroke-width="2"/>'
                 f'<path d="M-12,-72 L0,-90 L12,-72" fill="none" stroke="#fff" stroke-opacity=".8" stroke-width="2"/>'
                 f'<text y="6" text-anchor="middle" font-size="13" font-weight="700" letter-spacing="3" fill="{MUTED}">WEARER</text></g>')
    x0 = 720
    parts.append(f"""  <text x="{x0}" y="110" font-size="13" font-weight="700" letter-spacing="3" fill="#ff5a5f">HEAD-RELATIVE · CLOCKWISE FROM ABOVE</text>
  <circle cx="{x0 + 9}" cy="164" r="9" fill="{RED}"/>
  <text x="{x0 + 30}" y="171" font-size="21" font-weight="800" fill="{INK}">Group A · cardinals</text>
  <text x="{x0 + 30}" y="197" font-family="{MONO}" font-size="13" fill="{MUTED}">front · right · rear · left · trigger BCM 11</text>
  <circle cx="{x0 + 9}" cy="244" r="9" fill="{BLUE}"/>
  <text x="{x0 + 30}" y="251" font-size="21" font-weight="800" fill="{INK}">Group B · diagonals</text>
  <text x="{x0 + 30}" y="277" font-family="{MONO}" font-size="13" fill="{MUTED}">the four 45° directions · trigger BCM 5</text>
  <text x="{x0}" y="336" font-size="16" fill="{INK}" fill-opacity=".85">The groups fire alternately, so two neighbouring</text>
  <text x="{x0}" y="359" font-size="16" fill="{INK}" fill-opacity=".85">sensors never listen for the same echo.</text>
  <rect x="{x0}" y="396" width="4" height="52" rx="2" fill="{BRONZE}"/>
  <text x="{x0 + 18}" y="416" font-size="15" font-style="italic" fill="{GOLD}">Beams don't overlap: this is eight-direction</text>
  <text x="{x0 + 18}" y="440" font-size="15" font-style="italic" fill="{GOLD}">sensing, not continuous 360° coverage.</text>""")
    return svg(w, h, "Direction map: eight sensors around the head, group A cardinals and group B diagonals, each driving the motor on the same side.", "\n".join(parts))


def bands():
    w, h = 1200, 350
    x0, x1, ybase, ytop = 90, 1110, 215, 100
    px = (x1 - x0) / 3.5

    def X(m):
        return x0 + m * px

    def Y(hz):
        return ybase - hz * (ybase - ytop) / 10

    def rate(m):
        return max(0.0, 10 * (1 - m * 1000 / 3500))

    parts = [backdrop(w, h, big=140, small=100, corners="tl tr", stars=[(300, 300, 1.6, .3), (900, 30, 1.6, 1.7)]), frame(w, h)]
    parts.append(f'  <text x="{x0}" y="52" font-size="14" font-weight="700" letter-spacing="5" fill="#ff5a5f">DISTANCE → VIBRATION</text>'
                 f'<text x="{x1}" y="52" text-anchor="end" font-family="{MONO}" font-size="14" fill="{GOLD}">pulse rate = 10 × (1 − d / 3500 mm) · 30 % on-time</text>')
    parts.append(f'  <path d="M{X(0)},{Y(10)} L{X(3.5)},{Y(0)} L{X(0)},{Y(0)} Z" fill="url(#area)"/>'
                 f'<line x1="{X(0)}" y1="{Y(10)}" x2="{X(3.5)}" y2="{Y(0)}" stroke="url(#frame)" stroke-width="3"/>'
                 f'<text x="{x0 - 10}" y="{Y(10) + 5}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{MUTED}">10 Hz</text>'
                 f'<text x="{x0 - 10}" y="{Y(0) + 5}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{MUTED}">0</text>')
    segs = [("URGENT", 0, .4, "#ff2d3a", .2), ("NEAR", .4, .8, "#ff7a1a", .6), ("MID", .8, 1.5, "#ffc233", 1.15),
            ("FAR", 1.5, 3.0, "#3d7bff", 2.25), ("BEYOND", 3.0, 3.5, "#59607a", None)]
    for name, a, b, col, mid in segs:
        parts.append(f'  <rect x="{X(a) + 2:.1f}" y="229" width="{X(b) - X(a) - 4:.1f}" height="30" rx="6" fill="{col}" fill-opacity=".9"/>'
                     f'<text x="{(X(a) + X(b)) / 2:.1f}" y="249" text-anchor="middle" font-size="13" font-weight="800" letter-spacing="2" fill="#0b0e1a">{name}</text>')
        if mid is not None:
            r = rate(mid)
            dur = 1 / r
            parts.append(f'  <circle cx="{X(mid):.1f}" cy="{Y(r):.1f}" r="14" fill="none" stroke="{col}" stroke-opacity=".5"/>'
                         f'<circle cx="{X(mid):.1f}" cy="{Y(r):.1f}" r="8" fill="{col}" filter="url(#softglow)">'
                         f'<animate attributeName="opacity" values="1;.12" keyTimes="0;.3" calcMode="discrete" dur="{dur:.3f}s" repeatCount="indefinite"/></circle>'
                         f'<text x="{X(mid):.1f}" y="{Y(r) - 22:.1f}" text-anchor="middle" font-family="{MONO}" font-size="12" fill="{INK}">~{r:.1f} Hz</text>')
    for m, lab in [(0, "0"), (.4, "0.4 m"), (.8, "0.8 m"), (1.5, "1.5 m"), (3.0, "3.0 m"), (3.5, "3.5 m")]:
        parts.append(f'  <line x1="{X(m):.1f}" y1="263" x2="{X(m):.1f}" y2="271" stroke="{MUTED}"/>'
                     f'<text x="{X(m):.1f}" y="287" text-anchor="middle" font-family="{MONO}" font-size="12" fill="{MUTED}">{lab}</text>')
    parts.append(f'  <text x="600" y="324" text-anchor="middle" font-size="15" fill="{MUTED}">'
                 f'<tspan fill="{INK}" font-weight="700">unknown</tspan> (missing · stale · invalid) → no pulse, reported as a fault, never as “clear”</text>')
    return svg(w, h, "Distance to vibration: urgent up to 0.4 m, near to 0.8 m, mid to 1.5 m, far to 3 m; pulse rate rises linearly as distance shrinks.", "\n".join(parts))


def footer():
    w, h = 1200, 230
    body = f"""{backdrop(w, h, big=150, small=110, stars=[(200, 60, 1.8, 0), (1000, 170, 1.8, 1.2), (820, 50, 1.6, 2.2)])}
  <g clip-path="url(#clip)">
{ripple(600, 70, 10, 260, [RED, BLUE], dur=4, width=1.2)}
  </g>
{frame(w, h)}
{spider(600, 40, drop=18)}
  <g text-anchor="middle">
    <text x="600" y="150" font-size="32" font-weight="800" fill="url(#rb)">With great power comes great responsibility.</text>
    <text x="600" y="190" font-size="15" letter-spacing="2" fill="{MUTED}">BUILT AT HACK THE NORTH 2026  ·  3RD PLACE, QNX TRACK  ·  MIT LICENSE</text>
  </g>"""
    return svg(w, h, "With great power comes great responsibility. Built at Hack the North 2026.", body)


SECTIONS = [
    ("what-it-does", "What it does", "Feel where things are. Ask what they are.", RED),
    ("architecture", "System architecture", "Two Pis, one headband. The reflexes never wait on the brain.", BLUE),
    ("how-it-works", "How it works", "Directions, distances, and the words it listens for.", RED),
    ("getting-started", "Getting started", "Suit up: clone, build, run, test.", BLUE),
    ("configuration", "Configuration", "Every knob, versioned and validated.", RED),
    ("hardware", "Hardware", "Sensors, motors, and a headband.", BLUE),
    ("demo", "The 90-second demo", "Stationary wearer. Soft objects. One clean reveal.", RED),
    ("ground-rules", "Ground rules &amp; boundaries", "The lines this build doesn't cross.", BLUE),
    ("whats-next", "What's next", "What we'd build after the weekend.", RED),
    ("repository-layout", "Repository layout", "Where everything lives.", BLUE),
    ("team", "The team", "The people behind the mask.", RED),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = {"hero.svg": hero(), "award.svg": award(), "powers.svg": powers(), "devices.svg": devices(),
             "directions.svg": directions(), "bands.svg": bands(), "footer.svg": footer()}
    for i, (slug, title, sub, accent) in enumerate(SECTIONS, 1):
        files[f"section-{i:02d}-{slug}.svg"] = section(i, title, sub, accent)
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8")
        print(f"wrote docs/readme/{name}")


if __name__ == "__main__":
    main()
