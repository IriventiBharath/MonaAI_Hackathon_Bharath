#!/usr/bin/env python3
"""
ALKAME Studio Reel Generator
=============================
Produces a 15-second (5 scenes × 3 s) vertical reel at 1080×1920 (9:16).

Pipeline per scene:
  1. Veo 3.1 fast  →  raw clip (~8 s)
  2. ffmpeg trim   →  3-second clip
  3. PIL overlay   →  safe-zone text pills burned in
  4. ffmpeg concat →  final_reel.mp4

Safe zones (TikTok / Instagram):
  Top    : 140 px   (platform UI bar)
  Bottom : 600 px   (caption / CTA bar)  →  message band ends at y=1320
  Right  : 180 px   (action icons)        →  message band ends at x=900
  Left   :  40 px   minimum margin

HWG compliance: all Veo prompts and on-screen copy use sensation language only;
no therapeutic, medical-cure, or Heilmittelwerbegesetz-prohibited claims.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

# ── Environment ───────────────────────────────────────────────────────────────
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not API_KEY:
    sys.exit("ERROR: GEMINI_API_KEY not found in .env")

# ── Veo config ────────────────────────────────────────────────────────────────
BASE_URL       = "https://generativelanguage.googleapis.com/v1beta"
MODEL          = "veo-3.1-generate-preview"
POLL_INTERVAL  = 15   # seconds between status checks
POLL_TIMEOUT   = 600  # max 10 min per clip

# ── Canvas / safe-zone constants ──────────────────────────────────────────────
W, H         = 1080, 1920
SAFE_LEFT    = 40
SAFE_RIGHT   = 900   # 1080 - 180
SAFE_TOP     = 140
SAFE_BOTTOM  = 1320  # 1920 - 600
SCENE_DUR    = 3     # seconds per scene

# ── Output directory ──────────────────────────────────────────────────────────
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Font (Windows Arial Bold; falls back to PIL default) ─────────────────────
_FONT_PATH = Path("C:/Windows/Fonts/arialbi.ttf")   # Arial Bold Italic

def _font(size: int) -> ImageFont.FreeTypeFont:
    if _FONT_PATH.exists():
        return ImageFont.truetype(str(_FONT_PATH), size)
    return ImageFont.load_default()

# ─────────────────────────────────────────────────────────────────────────────
# STORYBOARD  (5 scenes, 4-5 hero SKUs)
# ─────────────────────────────────────────────────────────────────────────────
SCENES = [
    {
        "id": 1,
        "product": "5in1 Beinlotion",
        "price":   "€ 9,95  ·  200 ml",
        "hook":    "Schwere Beine\nnach der Schicht?",
        "prompt": (
            "Cinematic vertical 9:16. A woman sits on the edge of a bathtub after a long workday, "
            "gently massaging white lotion into her calves. Warm golden-hour light, soft background bokeh. "
            "The lotion bottle rests on the tiled edge. Slow, relaxing motion. "
            "Studio-quality beauty cinematography. Cosmetic wellness product only. No medical claims."
        ),
    },
    {
        "id": 2,
        "product": "Mobil Eisspray akut",
        "price":   "€ 9,40  ·  150 ml",
        "hook":    "Sofortige\nKühlung.",
        "prompt": (
            "Cinematic vertical 9:16. Athlete in dark sportswear sprays an aerosol can "
            "onto their calf muscle immediately after a sprint finish. Visible icy-white mist cloud "
            "in slow motion. High-contrast stadium / track lighting. Dynamic, powerful energy. "
            "Studio-quality sports cinematography. Cosmetic product. No medical-cure claims."
        ),
    },
    {
        "id": 3,
        "product": "Mobil Gel",
        "price":   "€ 5,83  ·  100 ml",
        "hook":    "Täglich.\nMobil.",
        "prompt": (
            "Cinematic vertical 9:16 macro close-up. Hands gently massaging clear, slightly "
            "blue-tinted gel into a knee joint. The gel glistens under soft diffused white studio "
            "lighting. A product tube rests on white marble. Calm, confident motion. "
            "Beauty macro cinematography. Cosmetic product only. No medical claims."
        ),
    },
    {
        "id": 4,
        "product": "Sole Fußbad + Fuß Butter",
        "price":   "€ 6,49 + € 7,71",
        "hook":    "Das\nRitual.",
        "prompt": (
            "Cinematic vertical 9:16 ASMR-style close-up. Bare, clean feet lowered slowly "
            "into a white ceramic bowl filled with steaming, slightly milky foot-bath water. "
            "Himalayan salt crystals dissolving. Warm candlelight. A jar of foot butter "
            "and a kraft-paper pack of foot-bath salts sit on a wooden bamboo tray beside the bowl. "
            "Ultra-relaxing Nordic spa atmosphere. Studio-quality wellness cinematography. "
            "Cosmetic product. No therapeutic claims."
        ),
    },
    {
        "id": 5,
        "product": "Hornhaut Entferner Maske",
        "price":   "€ 8,49  ·  2×20 ml",
        "hook":    "Sichtbar\nglatter.",
        "prompt": (
            "Cinematic vertical 9:16 beauty reveal. Extreme close-up of a heel: "
            "the left half shows dry, rough skin texture; the right half transitions to "
            "visibly smooth, soft skin after treatment. A hand carefully applies thick "
            "white cream from a small sachet onto the heel. Bright beauty-studio key lighting "
            "on white seamless background. Studio-quality before-and-after cosmetic shot. "
            "No medical-cure claims."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# VEO API
# ─────────────────────────────────────────────────────────────────────────────

def generate_clip(scene: dict) -> str:
    """Submit a Veo generation job and return the operation name."""
    url = f"{BASE_URL}/models/{MODEL}:predictLongRunning?key={API_KEY}"
    payload = {
        "instances": [{"prompt": scene["prompt"]}],
        "parameters": {
            "aspectRatio": "9:16",
            "sampleCount": 1,
            "resolution": "1080p",
        },
    }
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    op_name = r.json()["name"]
    print(f"    operation: {op_name}")
    return op_name


def poll_until_done(op_name: str) -> bytes:
    """
    Poll the long-running operation until done.
    Returns the raw video bytes (MP4).
    """
    url = f"{BASE_URL}/{op_name}?key={API_KEY}"
    start = time.time()
    while True:
        elapsed = int(time.time() - start)
        if elapsed > POLL_TIMEOUT:
            raise TimeoutError(f"Veo operation timed out after {POLL_TIMEOUT}s")

        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()

        if not data.get("done"):
            print(f"    … still generating ({elapsed}s elapsed)")
            time.sleep(POLL_INTERVAL)
            continue

        print(f"    done in {elapsed}s")

        # Navigate the response — handle multiple possible shapes
        resp = data.get("response", {})

        # Unwrap PredictLongRunningResponse envelope if present
        inner = resp.get("generateVideoResponse", resp)

        # generatedSamples[].video.{uri | bytesBase64Encoded}
        samples = inner.get("generatedSamples", [])
        if samples:
            video_obj = samples[0].get("video", {})
            b64 = video_obj.get("bytesBase64Encoded")
            if b64:
                return base64.b64decode(b64)
            uri = video_obj.get("uri")
            if uri:
                # Append API key for authenticated download
                sep = "&" if "?" in uri else "?"
                dl = requests.get(f"{uri}{sep}key={API_KEY}", timeout=180)
                dl.raise_for_status()
                return dl.content

        # Fallback: videos[].bytesBase64Encoded
        videos = resp.get("videos", [])
        if videos:
            b64 = videos[0].get("bytesBase64Encoded")
            if b64:
                return base64.b64decode(b64)

        # Unknown shape — dump for diagnosis
        print("    WARNING: unexpected response structure:")
        print(json.dumps(data, indent=2)[:1000])
        raise RuntimeError("Could not extract video bytes from Veo response.")


# ─────────────────────────────────────────────────────────────────────────────
# FFMPEG HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_FFMPEG = (
    r"C:\Users\bhara\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
)

def _ffmpeg(*args: str) -> None:
    cmd = [_FFMPEG, "-y"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg stderr:\n{result.stderr[-1500:]}")
        raise subprocess.CalledProcessError(result.returncode, cmd)


def trim_clip(raw: Path, out: Path, duration: int = SCENE_DUR) -> None:
    """Trim to `duration` seconds and scale to exactly 1080×1920 (Veo outputs 720×1280)."""
    _ffmpeg(
        "-i", str(raw),
        "-t", str(duration),
        "-vf", f"scale={W}:{H}",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    )


def overlay_png(video_in: Path, png: Path, video_out: Path) -> None:
    """Composite a full-frame RGBA PNG over a video clip using ffmpeg."""
    _ffmpeg(
        "-i", str(video_in),
        "-i", str(png),
        "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        str(video_out),
    )


def concat_clips(clips: List[Path], out: Path) -> None:
    """Concatenate clips (must share codec / resolution) using the concat demuxer."""
    list_file = OUTPUT_DIR / "concat_list.txt"
    lines = "\n".join(f"file '{p.resolve().as_posix()}'" for p in clips)
    list_file.write_text(lines, encoding="utf-8")
    _ffmpeg(
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(out),
    )
    list_file.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# TEXT OVERLAY  (PIL → transparent RGBA PNG)
# ─────────────────────────────────────────────────────────────────────────────

def _pill(
    draw: ImageDraw.ImageDraw,
    text: str,
    y_mid: int,
    font_size: int,
) -> None:
    """
    Draw a semi-transparent rounded pill with white text,
    horizontally centred inside the safe zone.
    """
    font = _font(font_size)
    pad_x, pad_y, radius = 52, 24, 24

    # Measure text block (position (0,0) gives us the size)
    bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center")
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Pill rectangle (clamped to safe zone horizontally)
    rx0 = max((W - tw) // 2 - pad_x, SAFE_LEFT)
    ry0 = y_mid - th // 2 - pad_y
    rx1 = min((W + tw) // 2 + pad_x, SAFE_RIGHT)
    ry1 = y_mid + th // 2 + pad_y

    draw.rounded_rectangle([rx0, ry0, rx1, ry1], radius=radius, fill=(0, 0, 0, 168))

    # Text — centred horizontally, vertically around y_mid
    tx = (W - tw) // 2
    ty = y_mid - th // 2
    draw.multiline_text(
        (tx, ty), text, font=font,
        fill=(255, 255, 255, 255), align="center",
    )


def make_overlay(scene: dict) -> Path:
    """
    Render all text pills for one scene onto a transparent 1080×1920 canvas.
    Saves to a temp PNG and returns its path.
    """
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Hook headline  (top of safe zone, below platform UI) ──
    _pill(draw, scene["hook"],    y_mid=285,  font_size=88)

    # ── Product name  (bottom of message-safe band) ──────────
    _pill(draw, scene["product"], y_mid=1185, font_size=68)

    # ── Price  (just above caption area) ─────────────────────
    _pill(draw, scene["price"],   y_mid=1272, font_size=50)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name, format="PNG")
    tmp.close()
    return Path(tmp.name)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"ALKAME Reel Generator — {len(SCENES)} scenes × {SCENE_DUR}s = {len(SCENES)*SCENE_DUR}s reel\n")

    final_clips: List[Path] = []

    for scene in SCENES:
        sid = scene["id"]
        tag = f"[Scene {sid}/{len(SCENES)}]"
        print(f"{tag} {scene['product']}")

        raw_path   = OUTPUT_DIR / f"raw_scene_{sid}.mp4"
        trim_path  = OUTPUT_DIR / f"trim_scene_{sid}.mp4"
        scene_path = OUTPUT_DIR / f"scene_{sid}.mp4"

        # ── Step 1: Generate with Veo 3.1 ────────────────────────────────────
        if raw_path.exists():
            print(f"  [skip] raw clip already present")
        else:
            print("  Generating with Veo 3.1 fast…")
            op = generate_clip(scene)
            print("  Polling for completion…")
            video_bytes = poll_until_done(op)
            raw_path.write_bytes(video_bytes)
            print(f"  Saved {len(video_bytes)//1024} KB → {raw_path.name}")

        # ── Step 2: Trim to 3 s ──────────────────────────────────────────────
        if trim_path.exists():
            print(f"  [skip] trimmed clip already present")
        else:
            print(f"  Trimming to {SCENE_DUR}s…")
            trim_clip(raw_path, trim_path)

        # ── Step 3: Burn text overlay ─────────────────────────────────────────
        if scene_path.exists():
            print(f"  [skip] text overlay already applied")
        else:
            print("  Rendering text overlay…")
            png = make_overlay(scene)
            overlay_png(trim_path, png, scene_path)
            png.unlink()

        final_clips.append(scene_path)
        print(f"  ✓ {scene_path.name}\n")

    # ── Step 4: Concatenate all scenes ────────────────────────────────────────
    final = OUTPUT_DIR / "final_reel.mp4"
    print(f"[Concat] Joining {len(final_clips)} scenes…")
    concat_clips(final_clips, final)

    print(f"\n{'='*55}")
    print(f"  OUTPUT : {final.resolve()}")
    print(f"  SIZE   : {W}×{H}  (9:16 vertical)")
    print(f"  LENGTH : {len(SCENES) * SCENE_DUR}s  ({len(SCENES)} scenes × {SCENE_DUR}s)")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
