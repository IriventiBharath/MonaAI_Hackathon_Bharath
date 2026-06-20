#!/usr/bin/env python3
"""
ALKAME Studio Reel Generator
=============================
Produces a 15-second (5 scenes × 3 s) vertical reel at 1080×1920 (9:16).

Pipeline per scene:
  1. Veo 3.1  →  raw clip with text baked in by the AI
  2. ffmpeg trim  →  3-second clip
  3. ffmpeg concat  →  final_reel.mp4

Text is described in each Veo prompt — bold italic, white, placed within
TikTok/Instagram safe zones. No post-processing overlay needed.

HWG compliance: sensation language only; no therapeutic or medical-cure claims.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List

import requests
from dotenv import load_dotenv

# ── Environment ───────────────────────────────────────────────────────────────
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not API_KEY:
    sys.exit("ERROR: GEMINI_API_KEY not found in .env")

# ── Veo config ────────────────────────────────────────────────────────────────
BASE_URL      = "https://generativelanguage.googleapis.com/v1beta"
MODEL         = "veo-3.1-generate-preview"
POLL_INTERVAL = 15    # seconds between status checks
POLL_TIMEOUT  = 600   # max 10 min per clip

# ── Output ────────────────────────────────────────────────────────────────────
W, H       = 1080, 1920
SCENE_DUR  = 3
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Text-in-prompt spec (injected into every scene prompt) ───────────────────
TEXT_SPEC = (
    "The video must display bold italic white sans-serif text directly on screen — "
    "generated as part of the video, not added in post. "
    "Follow these safe-zone rules strictly: "
    "keep all text at least 140 px from the top edge, 600 px from the bottom edge, "
    "180 px from the right edge, and 40 px from the left edge. "
    "Place a large bold italic hook headline near the top of the frame (below 140 px). "
    "Place the product name and price in bold italic near the bottom of the frame "
    "(above the 600 px caption zone). "
    "All text must be white, bold italic, clearly legible against the background, "
    "with a subtle semi-transparent dark shadow or pill behind each text block."
)


def _build_prompt(scene: dict) -> str:
    """Combine the cinematic scene description with explicit text instructions."""
    return (
        f"{scene['visual']}\n\n"
        f"TEXT TO DISPLAY ON SCREEN:\n"
        f"  Hook headline (top safe zone): \"{scene['hook']}\"\n"
        f"  Product name (bottom safe zone): \"{scene['product']}\"\n"
        f"  Price / size (below product name): \"{scene['price']}\"\n\n"
        f"{TEXT_SPEC}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# STORYBOARD  (5 scenes, 4-5 hero SKUs)
# ─────────────────────────────────────────────────────────────────────────────
SCENES = [
    {
        "id": 1,
        "product": "5in1 Beinlotion",
        "price":   "€ 9,95  ·  200 ml",
        "hook":    "Schwere Beine nach der Schicht?",
        "visual": (
            "Cinematic vertical 9:16 beauty shot at 1080×1920. "
            "A woman sits on the edge of a bathtub after a long workday, "
            "gently massaging white lotion into her bare calves. "
            "Warm golden-hour light, soft background bokeh. "
            "The lotion bottle rests on the tiled edge. Slow, relaxing motion. "
            "Studio-quality beauty cinematography. Cosmetic wellness product only."
        ),
    },
    {
        "id": 2,
        "product": "Mobil Eisspray akut",
        "price":   "€ 9,40  ·  150 ml",
        "hook":    "Sofortige Kühlung.",
        "visual": (
            "Cinematic vertical 9:16 sports shot at 1080×1920. "
            "Athlete in dark sportswear sprays an aerosol can onto their calf muscle "
            "immediately after a sprint finish on a running track. "
            "Visible icy-white mist cloud captured in slow motion. "
            "High-contrast stadium lighting. Dynamic, powerful energy. "
            "Studio-quality sports cinematography. Cosmetic product only."
        ),
    },
    {
        "id": 3,
        "product": "Mobil Gel",
        "price":   "€ 5,83  ·  100 ml",
        "hook":    "Täglich. Mobil.",
        "visual": (
            "Cinematic vertical 9:16 macro close-up at 1080×1920. "
            "Hands gently massaging clear, slightly blue-tinted gel into a knee joint. "
            "The gel glistens under soft diffused white studio lighting. "
            "A product tube rests on white marble beside the hands. "
            "Calm, confident, precise motion. Beauty macro cinematography. "
            "Cosmetic product only."
        ),
    },
    {
        "id": 4,
        "product": "Sole Fußbad + Fuß Butter",
        "price":   "€ 6,49 + € 7,71",
        "hook":    "Das Ritual.",
        "visual": (
            "Cinematic vertical 9:16 ASMR-style close-up at 1080×1920. "
            "Bare, clean feet lowered slowly into a white ceramic bowl filled with "
            "steaming, slightly milky foot-bath water. Himalayan salt crystals dissolving. "
            "Warm candlelight. A jar of foot butter and a kraft-paper pack of foot-bath "
            "salts sit on a wooden bamboo tray beside the bowl. "
            "Ultra-relaxing Nordic spa atmosphere. Studio-quality wellness cinematography. "
            "Cosmetic product only."
        ),
    },
    {
        "id": 5,
        "product": "Hornhaut Entferner Maske",
        "price":   "€ 8,49  ·  2×20 ml",
        "hook":    "Sichtbar glatter.",
        "visual": (
            "Cinematic vertical 9:16 beauty reveal at 1080×1920. "
            "Extreme close-up of a heel: the left half shows dry, rough skin texture; "
            "the right half transitions to visibly smooth, soft skin after treatment. "
            "A hand carefully applies thick white cream from a small sachet onto the heel. "
            "Bright beauty-studio key lighting on white seamless background. "
            "Studio-quality before-and-after cosmetic shot. No medical-cure claims."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# VEO API
# ─────────────────────────────────────────────────────────────────────────────

def generate_clip(scene: dict) -> str:
    """Submit a Veo 3.1 generation job and return the operation name."""
    url = f"{BASE_URL}/models/{MODEL}:predictLongRunning?key={API_KEY}"
    payload = {
        "instances": [{"prompt": _build_prompt(scene)}],
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
    """Poll the long-running operation until done. Returns raw MP4 bytes."""
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

        resp  = data.get("response", {})
        inner = resp.get("generateVideoResponse", resp)

        samples = inner.get("generatedSamples", [])
        if samples:
            video_obj = samples[0].get("video", {})
            b64 = video_obj.get("bytesBase64Encoded")
            if b64:
                return base64.b64decode(b64)
            uri = video_obj.get("uri")
            if uri:
                sep = "&" if "?" in uri else "?"
                dl = requests.get(f"{uri}{sep}key={API_KEY}", timeout=180)
                dl.raise_for_status()
                return dl.content

        videos = resp.get("videos", [])
        if videos:
            b64 = videos[0].get("bytesBase64Encoded")
            if b64:
                return base64.b64decode(b64)

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
    """Trim to `duration` seconds; scale to 1080×1920 as safety net."""
    _ffmpeg(
        "-i", str(raw),
        "-t", str(duration),
        "-vf", f"scale={W}:{H}",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    )


def concat_clips(clips: List[Path], out: Path) -> None:
    """Concatenate clips via the ffmpeg concat demuxer."""
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
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"ALKAME Reel Generator — {len(SCENES)} scenes × {SCENE_DUR}s = {len(SCENES)*SCENE_DUR}s reel\n")

    final_clips: List[Path] = []

    for scene in SCENES:
        sid = scene["id"]
        print(f"[Scene {sid}/{len(SCENES)}] {scene['product']}")

        raw_path  = OUTPUT_DIR / f"raw_scene_{sid}.mp4"
        out_path  = OUTPUT_DIR / f"scene_{sid}.mp4"

        # ── Step 1: Generate with Veo 3.1 ────────────────────────────────────
        if raw_path.exists():
            print(f"  [skip] raw clip already present")
        else:
            print("  Generating with Veo 3.1…")
            op = generate_clip(scene)
            print("  Polling for completion…")
            video_bytes = poll_until_done(op)
            raw_path.write_bytes(video_bytes)
            print(f"  Saved {len(video_bytes)//1024} KB → {raw_path.name}")

        # ── Step 2: Trim to 3 s ──────────────────────────────────────────────
        if out_path.exists():
            print(f"  [skip] trimmed clip already present")
        else:
            print(f"  Trimming to {SCENE_DUR}s…")
            trim_clip(raw_path, out_path)

        final_clips.append(out_path)
        print(f"  ✓ {out_path.name}\n")

    # ── Step 3: Concatenate all scenes ───────────────────────────────────────
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
