"""Generate split-screen comparison GIF for RTFM.

Both agents succeed. The contrast is in HOW MUCH it costs:
  Left  (vanilla Claude Code): N tool calls, tokens climbing into red,
                                context window filling up, slower.
  Right (with RTFM)          : 1 search, 1 expand. Done fast. Bars stay green.

Run: python3 docs/demo/make_split_gif.py
Output: docs/demo/rtfm-split.gif
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

# ── Layout ──────────────────────────────────────────────────────────────
W, H = 880, 510
SPLIT = W // 2
PAD = 30

# ── Palette (Tokyo Night-ish) ───────────────────────────────────────────
BG = (26, 27, 38)
PANEL = (30, 32, 48)
FG = (192, 202, 245)
DIM = (86, 95, 137)
DIMMER = (60, 65, 95)
RED = (247, 118, 142)
ORANGE = (255, 158, 100)
YELLOW = (224, 175, 104)
GREEN = (158, 206, 106)
BLUE = (122, 162, 247)
PURPLE = (187, 154, 247)

# ── Fonts ───────────────────────────────────────────────────────────────
def find_font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/{name}",
        f"/usr/share/fonts/TTF/{name}",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

F_TITLE = find_font(22, bold=True)
F_SUB = find_font(13)
F_PANEL_HDR = find_font(17, bold=True)
F_LOG = find_font(13)
F_BAR_LBL = find_font(12, bold=True)
F_BAR_VAL = find_font(11)
F_RESULT = find_font(14, bold=True)
F_FOOTER = find_font(12)

# ── Animation parameters ────────────────────────────────────────────────
FPS = 10
DURATION_S = 3.5
N_FRAMES = int(FPS * DURATION_S)  # 35 frames

# Left panel : sequence of tool calls — each appears at a given frame
LEFT_CALLS = [
    (2,  "Glob   '**/*sync*'"),
    (5,  "Read   src/sync_handler.py"),
    (8,  "Grep   'embed' -r"),
    (11, "Read   src/pipeline.py"),
    (14, "Read   src/embeddings.py"),
    (17, "Glob   '**/*.py'"),
    (20, "Grep   'background'"),
    (23, "Read   src/sync.py"),
]
LEFT_FOUND_FRAME = 26  # ✓ found
LEFT_FINAL_TOKENS = 142_000  # 142k of 200k context
LEFT_FINAL_CALLS = 22
LEFT_FINAL_TIME = "2m18s"
LEFT_FINAL_COST = 0.83

# Right panel : just 2 calls
RIGHT_CALLS = [
    (2,  "rtfm_search  'embedding sync logic'"),
    (5,  "rtfm_expand  src/sync.py L138-156"),
]
RIGHT_FOUND_FRAME = 8   # ✓ found — fast
RIGHT_FINAL_TOKENS = 6_500
RIGHT_FINAL_CALLS = 2
RIGHT_FINAL_TIME = "3.4s"
RIGHT_FINAL_COST = 0.03

CONTEXT_MAX = 200_000

# ── Drawing helpers ─────────────────────────────────────────────────────
def lerp(a, b, t):
    return a + (b - a) * max(0.0, min(1.0, t))

def progress_left(frame):
    """Returns (calls_so_far, tokens, time_str, cost, found)."""
    found = frame >= LEFT_FOUND_FRAME
    if frame < 3:
        return 0, 0, "0.0s", 0.0, False
    # Linear ramp until found
    end_frame = LEFT_FOUND_FRAME
    t = min(1.0, (frame - 3) / (end_frame - 3))
    calls = int(lerp(0, LEFT_FINAL_CALLS, t))
    tokens = int(lerp(0, LEFT_FINAL_TOKENS, t))
    secs = lerp(0, 138, t)
    cost = lerp(0, LEFT_FINAL_COST, t)
    if secs < 60:
        time_str = f"{secs:.0f}s"
    else:
        m, s = divmod(int(secs), 60)
        time_str = f"{m}m{s:02d}s"
    return calls, tokens, time_str, cost, found

def progress_right(frame):
    found = frame >= RIGHT_FOUND_FRAME
    if frame < 3:
        return 0, 0, "0.0s", 0.0, False
    t = min(1.0, (frame - 3) / (RIGHT_FOUND_FRAME - 3))
    calls = int(lerp(0, RIGHT_FINAL_CALLS, t))
    tokens = int(lerp(0, RIGHT_FINAL_TOKENS, t))
    secs = lerp(0, 3.4, t)
    cost = lerp(0, RIGHT_FINAL_COST, t)
    return calls, tokens, f"{secs:.1f}s", cost, found

def color_for_pct(pct):
    if pct < 30:
        return GREEN
    if pct < 55:
        return YELLOW
    if pct < 75:
        return ORANGE
    return RED

def draw_bar(d, x, y, w, h, pct, label, value_str, font_lbl, font_val):
    # Track
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2,
                        fill=DIMMER)
    # Fill
    fill_w = int(w * (pct / 100))
    if fill_w >= h:
        d.rounded_rectangle([x, y, x + fill_w, y + h], radius=h // 2,
                            fill=color_for_pct(pct))
    elif fill_w > 0:
        d.ellipse([x, y, x + h, y + h], fill=color_for_pct(pct))
    # Label above-left
    d.text((x, y - 22), label, font=font_lbl, fill=FG)
    # Value above-right
    bbox = d.textbbox((0, 0), value_str, font=font_val)
    vw = bbox[2] - bbox[0]
    d.text((x + w - vw, y - 20), value_str, font=font_val, fill=DIM)

def draw_panel_bg(d, x0, x1):
    d.rounded_rectangle([x0, 100, x1, H - 70], radius=10, fill=PANEL)

def draw_log(d, frame, calls, x, log_y, accent):
    """Show tool calls as a stacked log; old ones dim, latest highlighted."""
    visible = [(f, t) for f, t in calls if frame >= f]
    # Show last ~8
    show = visible[-8:]
    line_h = 22
    for i, (f_appear, txt) in enumerate(show):
        is_latest = (i == len(show) - 1) and (frame - f_appear < 4)
        color = accent if is_latest else DIM
        d.text((x, log_y + i * line_h), f"› {txt}", font=F_LOG, fill=color)

def draw_static(d):
    # Title
    title = "where is the embedding sync logic?"
    bbox = d.textbbox((0, 0), title, font=F_TITLE)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) // 2, 28), title, font=F_TITLE, fill=FG)
    # Subtitle
    sub = "same task · same model · ~2,000 files · who pays the bill?"
    bbox = d.textbbox((0, 0), sub, font=F_SUB)
    sw = bbox[2] - bbox[0]
    d.text(((W - sw) // 2, 65), sub, font=F_SUB, fill=DIM)

    # Footer
    footer = "RTFM · open source · local · zero LLM cost at index time"
    bbox = d.textbbox((0, 0), footer, font=F_FOOTER)
    fw = bbox[2] - bbox[0]
    d.text(((W - fw) // 2, H - 35), footer, font=F_FOOTER, fill=PURPLE)

def draw_panel(d, frame, side):
    is_left = (side == "left")
    if is_left:
        px0, px1 = PAD, SPLIT - 12
        accent = RED
        header = "WITHOUT RTFM"
        calls_data = LEFT_CALLS
        progress = progress_left(frame)
    else:
        px0, px1 = SPLIT + 12, W - PAD
        accent = GREEN
        header = "WITH RTFM"
        calls_data = RIGHT_CALLS
        progress = progress_right(frame)

    draw_panel_bg(d, px0, px1)

    # Header
    d.text((px0 + 24, 116), header, font=F_PANEL_HDR, fill=accent)

    # Tool calls log
    draw_log(d, frame, calls_data, px0 + 24, 158, accent)

    calls, tokens, time_str, cost, found = progress

    # Result line (above bars)
    result_y = 380
    if found:
        result_text = "✓ found · src/sync.py:142"
        d.text((px0 + 24, result_y), result_text, font=F_RESULT, fill=GREEN)
    else:
        result_text = "searching..."
        d.text((px0 + 24, result_y), result_text, font=F_RESULT, fill=DIM)

    # Bars area
    bar_x = px0 + 24
    bar_w = (px1 - px0) - 48
    bar_h = 14

    # Tokens bar
    pct_tokens = (tokens / 150_000) * 100  # cap visualization at 150k for left
    pct_tokens = min(100, pct_tokens)
    draw_bar(d, bar_x, result_y + 70, bar_w, bar_h, pct_tokens,
             "TOKENS USED", f"{tokens:,}", F_BAR_LBL, F_BAR_VAL)

    # Context bar
    pct_ctx = (tokens / CONTEXT_MAX) * 100
    draw_bar(d, bar_x, result_y + 130, bar_w, bar_h, pct_ctx,
             "CONTEXT WINDOW", f"{pct_ctx:.0f}% of 200k", F_BAR_LBL, F_BAR_VAL)

    # Bottom stats
    stats_y = result_y + 190
    stats = f"{calls} calls   ·   ${cost:.2f}   ·   {time_str}"
    d.text((bar_x, stats_y), stats, font=F_RESULT, fill=accent)

# ── Frame composition ───────────────────────────────────────────────────
def make_frame(frame_idx):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    draw_static(d)
    draw_panel(d, frame_idx, "left")
    draw_panel(d, frame_idx, "right")
    return img

# ── Main ────────────────────────────────────────────────────────────────
def main():
    out = Path(__file__).parent / "rtfm-split.gif"
    frames = [make_frame(i) for i in range(N_FRAMES)]
    durations = [int(1000 / FPS)] * (N_FRAMES - 1) + [600]  # hold last
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    total_s = sum(durations) / 1000
    print(f"Generated: {out}  ({N_FRAMES} frames, {total_s:.1f}s)")
    print(f"Size: {out.stat().st_size / 1024:.1f} KB")

if __name__ == "__main__":
    main()
