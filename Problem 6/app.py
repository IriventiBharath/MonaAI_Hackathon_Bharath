#!/usr/bin/env python3
"""
ALKAME Reel Generator — Streamlit UI
Select 4–5 products → Veo 3.1 generates studio scenes → download your reel.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY       = os.getenv("GEMINI_API_KEY", "").strip()
BASE_URL      = "https://generativelanguage.googleapis.com/v1beta"
MODEL         = "veo-3.1-generate-preview"
POLL_INTERVAL = 15
POLL_TIMEOUT  = 600
W, H          = 1080, 1920
SCENE_DUR     = 3
OUTPUT_DIR    = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
MIN_SEL, MAX_SEL = 4, 5

_FFMPEG = (
    r"C:\Users\bhara\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
)

# ── Scene templates (hook + visual per SKU) ───────────────────────────────────
TEMPLATES = {
    "ALK-FB-01": {
        "hook": "Seidenweiches Gefühl.",
        "visual": (
            "Cinematic vertical 9:16 beauty close-up at 1080×1920. "
            "A woman's hands massaging rich foot butter into dry heels. "
            "Golden warm light, cosy autumn atmosphere, white ceramic bowl nearby. "
            "Studio-quality beauty shot. Cosmetic product only."
        ),
    },
    "ALK-FB-02": {
        "hook": "Das Fußbad-Ritual.",
        "visual": (
            "Cinematic vertical 9:16 ASMR close-up at 1080×1920. "
            "Bare feet lowered into a steaming white ceramic bowl of milky foot-bath water. "
            "Salt crystals dissolving, warm candlelight, wooden tray beside it. "
            "Nordic spa atmosphere. Cosmetic product only."
        ),
    },
    "ALK-FB-03": {
        "hook": "Sanft. Effektiv.",
        "visual": (
            "Cinematic vertical 9:16 beauty macro at 1080×1920. "
            "Cream gently applied to a heel, smooth circular motion. "
            "Soft diffused studio lighting on white background. "
            "Clean minimalist beauty aesthetic. Cosmetic product only."
        ),
    },
    "ALK-FB-04": {
        "hook": "Sichtbar glatter.",
        "visual": (
            "Cinematic vertical 9:16 beauty reveal at 1080×1920. "
            "Close-up of a heel: left half dry and rough, right half smooth and soft. "
            "A hand applies white mask cream from a sachet. Bright studio key lighting, white background. "
            "Before-and-after cosmetic shot. No medical claims."
        ),
    },
    "ALK-FB-05": {
        "hook": "Intensiv gepflegt.",
        "visual": (
            "Cinematic vertical 9:16 macro at 1080×1920. "
            "Rich cream massaged into a dry foot, warm soft studio light, clean white background. "
            "Cosmetic product only."
        ),
    },
    "ALK-FB-06": {
        "hook": "Frisch. Den ganzen Tag.",
        "visual": (
            "Cinematic vertical 9:16 at 1080×1920. "
            "Active person spraying foot deodorant before a workout, bright summer lighting. "
            "Dynamic, fresh energy. Cosmetic product only."
        ),
    },
    "ALK-LG-01": {
        "hook": "Schwere Beine nach der Schicht?",
        "visual": (
            "Cinematic vertical 9:16 beauty shot at 1080×1920. "
            "A woman massaging white lotion into her calves after a long workday. "
            "Warm golden-hour light, soft background bokeh. Slow relaxing motion. "
            "Studio-quality beauty cinematography. Cosmetic product only."
        ),
    },
    "ALK-LG-02": {
        "hook": "Leichtigkeit pur.",
        "visual": (
            "Cinematic vertical 9:16 at 1080×1920. "
            "Person applying cooling leg gel to calves. Fresh blue-tinted gel, "
            "light diffused summer lighting. Refreshing aesthetic. Cosmetic product only."
        ),
    },
    "ALK-LG-03": {
        "hook": "Sichtbar gepflegte Beine.",
        "visual": (
            "Cinematic vertical 9:16 beauty close-up at 1080×1920. "
            "Smooth legs massaged with balsam, spring sunlight through window. "
            "Elegant feminine aesthetic, soft-focus floral background. Cosmetic product only."
        ),
    },
    "ALK-MG-01": {
        "hook": "Täglich. Mobil.",
        "visual": (
            "Cinematic vertical 9:16 macro close-up at 1080×1920. "
            "Hands massaging clear blue-tinted gel into a knee joint. "
            "Soft diffused white studio lighting. Product tube on white marble. "
            "Calm, confident motion. Cosmetic product only."
        ),
    },
    "ALK-MG-02": {
        "hook": "Extra Stark. Extra Wirksam.",
        "visual": (
            "Cinematic vertical 9:16 sports shot at 1080×1920. "
            "Athlete rubbing liniment into a sore shoulder before training. "
            "High-contrast gym lighting. Powerful, intense energy. Cosmetic product only."
        ),
    },
    "ALK-MG-03": {
        "hook": "Sofortige Kühlung.",
        "visual": (
            "Cinematic vertical 9:16 sports shot at 1080×1920. "
            "Athlete sprays aerosol onto calf muscle after a sprint. "
            "Visible icy-white mist cloud in slow motion. High-contrast stadium lighting. "
            "Dynamic energy. Cosmetic product only."
        ),
    },
    "ALK-MG-04": {
        "hook": "Klassisch. Bewährt.",
        "visual": (
            "Cinematic vertical 9:16 at 1080×1920. "
            "Experienced hands applying traditional spirit rub to forearms. "
            "Warm amber tones, timeless aesthetic. Cosmetic product only."
        ),
    },
    "ALK-MG-05": {
        "hook": "Wärme, die entspannt.",
        "visual": (
            "Cinematic vertical 9:16 at 1080×1920. "
            "Person applying warming gel to their lower back, visible relaxation. "
            "Cosy winter interior, soft warm lighting. Cosmetic product only."
        ),
    },
}

TEXT_SPEC = (
    "The video must display bold italic white sans-serif text directly on screen — "
    "generated as part of the video, not added in post. "
    "Safe-zone rules: keep all text at least 140 px from top, 600 px from bottom, "
    "180 px from right, 40 px from left. "
    "Place the bold italic hook headline near the top (below 140 px). "
    "Place the product name and price bold italic near the bottom (above the 600 px caption zone). "
    "All text: white, bold italic, with a subtle semi-transparent dark shadow or pill behind each line."
)


# ── Core generation logic ─────────────────────────────────────────────────────

def _build_prompt(product: dict) -> str:
    sku   = product["sku"]
    tmpl  = TEMPLATES.get(sku, {})
    hook  = tmpl.get("hook", product["product"])
    visual = tmpl.get(
        "visual",
        f"Cinematic vertical 9:16 beauty shot at 1080×1920 featuring {product['product']}. "
        "Studio-quality lighting. Cosmetic product only."
    )
    price = f"€ {product['price_eur']:.2f}  ·  {product['pack']}"
    return (
        f"{visual}\n\n"
        f"TEXT TO DISPLAY ON SCREEN:\n"
        f"  Hook headline (top safe zone): \"{hook}\"\n"
        f"  Product name (bottom safe zone): \"{product['product']}\"\n"
        f"  Price / size (below product name): \"{price}\"\n\n"
        f"{TEXT_SPEC}"
    )


def _ffmpeg(*args: str) -> None:
    result = subprocess.run([_FFMPEG, "-y"] + list(args), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error:\n{result.stderr[-800:]}")


def _generate_clip(product: dict) -> str:
    url = f"{BASE_URL}/models/{MODEL}:predictLongRunning?key={API_KEY}"
    payload = {
        "instances": [{"prompt": _build_prompt(product)}],
        "parameters": {"aspectRatio": "9:16", "sampleCount": 1, "resolution": "1080p"},
    }
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["name"]


def _poll_until_done(op_name: str, status_placeholder) -> bytes:
    url   = f"{BASE_URL}/{op_name}?key={API_KEY}"
    start = time.time()
    while True:
        elapsed = int(time.time() - start)
        if elapsed > POLL_TIMEOUT:
            raise TimeoutError(f"Timed out after {POLL_TIMEOUT}s")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data.get("done"):
            status_placeholder.caption(f"⏳ Generating… {elapsed}s elapsed")
            time.sleep(POLL_INTERVAL)
            continue
        status_placeholder.caption(f"✅ Done in {elapsed}s")
        resp  = data.get("response", {})
        inner = resp.get("generateVideoResponse", resp)
        samples = inner.get("generatedSamples", [])
        if samples:
            vid = samples[0].get("video", {})
            if vid.get("bytesBase64Encoded"):
                return base64.b64decode(vid["bytesBase64Encoded"])
            if vid.get("uri"):
                uri = vid["uri"]
                sep = "&" if "?" in uri else "?"
                dl  = requests.get(f"{uri}{sep}key={API_KEY}", timeout=180)
                dl.raise_for_status()
                return dl.content
        raise RuntimeError(f"Unexpected response: {json.dumps(data)[:400]}")


def _trim(raw: Path, out: Path) -> None:
    _ffmpeg(
        "-i", str(raw), "-t", str(SCENE_DUR),
        "-vf", f"scale={W}:{H}",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    )


def _concat(clips: list[Path], out: Path) -> None:
    lst = OUTPUT_DIR / "concat_list.txt"
    lst.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in clips), encoding="utf-8")
    _ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))
    lst.unlink()


# ── Streamlit page ────────────────────────────────────────────────────────────

st.set_page_config(page_title="ALKAME Reel Generator", page_icon="🎬", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    div[data-testid="stCheckbox"] { margin-top: 4px; }
    .product-line { font-size: 0.78rem; font-weight: 600; letter-spacing: 0.04em;
                    padding: 2px 8px; border-radius: 20px; display: inline-block; }
    .line-feet   { background:#dbeafe; color:#1d4ed8; }
    .line-legs   { background:#dcfce7; color:#15803d; }
    .line-muscle { background:#ffedd5; color:#c2410c; }
    .price-tag   { font-size: 1.1rem; font-weight: 700; color: #111; }
    .meta-text   { font-size: 0.78rem; color: #666; }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_products() -> list[dict]:
    with open("productinfo.json", encoding="utf-8") as f:
        data = json.load(f)
    return [p for p in data if p["line"] != "Cough drops"]


def line_badge(line: str) -> str:
    cls = {"Feet": "line-feet", "Legs": "line-legs"}.get(line, "line-muscle")
    return f'<span class="product-line {cls}">{line}</span>'


# ── Header ────────────────────────────────────────────────────────────────────
st.title("🎬 ALKAME Reel Generator")
st.markdown("Select **4–5 products** below. Veo 3.1 will generate a studio-quality 15-second vertical reel for TikTok / Instagram.")
st.divider()

if not API_KEY:
    st.error("GEMINI_API_KEY not found in .env — please add it and restart.")
    st.stop()

products = load_products()

# ── Selection counter ─────────────────────────────────────────────────────────
selected_skus = [p["sku"] for p in products if st.session_state.get(f"sel_{p['sku']}", False)]
n_sel = len(selected_skus)

counter_col, _, hint_col = st.columns([1, 2, 3])
with counter_col:
    colour = "#16a34a" if MIN_SEL <= n_sel <= MAX_SEL else "#dc2626"
    st.markdown(
        f"<h3 style='color:{colour}; margin:0'>{n_sel} / {MAX_SEL} selected</h3>",
        unsafe_allow_html=True,
    )
with hint_col:
    if n_sel < MIN_SEL:
        st.info(f"Choose at least {MIN_SEL} products to unlock the Generate button.", icon="ℹ️")
    elif n_sel > MAX_SEL:
        st.warning("Maximum 5 products. Deselect one to continue.", icon="⚠️")
    else:
        st.success("Ready to generate!", icon="✅")

st.markdown("&nbsp;")

# ── Product grid ──────────────────────────────────────────────────────────────
cols = st.columns(3, gap="medium")

for i, product in enumerate(products):
    sku        = product["sku"]
    is_checked = st.session_state.get(f"sel_{sku}", False)
    disabled   = (not is_checked) and (n_sel >= MAX_SEL)

    with cols[i % 3]:
        with st.container(border=True):
            cb_col, info_col = st.columns([0.12, 0.88])
            with cb_col:
                st.checkbox("", key=f"sel_{sku}", disabled=disabled, label_visibility="collapsed")
            with info_col:
                st.markdown(
                    f"**{product['product']}** &nbsp; {line_badge(product['line'])}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<span class="price-tag">€ {product["price_eur"]:.2f}</span> '
                    f'<span class="meta-text">&nbsp;·&nbsp; {product["pack"]}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<span class="meta-text">📅 {product["peak_season"]} &nbsp;·&nbsp; '
                    f'👤 {product["target_segment"]}</span>',
                    unsafe_allow_html=True,
                )

st.divider()

# ── Selected summary ──────────────────────────────────────────────────────────
if selected_skus:
    sel_products = [p for p in products if p["sku"] in selected_skus]
    st.markdown("**Selected scenes:**")
    cols_sum = st.columns(len(sel_products))
    for j, p in enumerate(sel_products):
        with cols_sum[j]:
            tmpl = TEMPLATES.get(p["sku"], {})
            st.markdown(f"**{j+1}. {p['product']}**")
            st.caption(f'"{tmpl.get("hook", "—")}"')

    st.markdown("&nbsp;")

# ── Generate button ───────────────────────────────────────────────────────────
can_generate = MIN_SEL <= n_sel <= MAX_SEL
generate_btn = st.button(
    "🎬 Generate Reel",
    type="primary",
    disabled=not can_generate,
    use_container_width=True,
)

# ── Generation pipeline ───────────────────────────────────────────────────────
if generate_btn:
    sel_products = [p for p in products if p["sku"] in selected_skus]
    final_path   = OUTPUT_DIR / "final_reel.mp4"
    scene_clips  = []

    with st.status("Generating your reel…", expanded=True) as gen_status:
        for idx, product in enumerate(sel_products, 1):
            sku      = product["sku"]
            raw_path = OUTPUT_DIR / f"raw_{sku}.mp4"
            out_path = OUTPUT_DIR / f"scene_{sku}.mp4"

            st.write(f"**Scene {idx}/{len(sel_products)}: {product['product']}**")
            poll_placeholder = st.empty()

            if raw_path.exists():
                poll_placeholder.caption("⚡ Using cached raw clip")
            else:
                poll_placeholder.caption("🚀 Submitting to Veo 3.1…")
                try:
                    op = _generate_clip(product)
                    poll_placeholder.caption(f"🔄 Polling… (op: `{op.split('/')[-1]}`)")
                    video_bytes = _poll_until_done(op, poll_placeholder)
                    raw_path.write_bytes(video_bytes)
                    poll_placeholder.caption(f"✅ Clip received ({len(video_bytes)//1024} KB)")
                except Exception as e:
                    st.error(f"Scene {idx} failed: {e}")
                    gen_status.update(label="Generation failed", state="error")
                    st.stop()

            if not out_path.exists():
                with st.spinner(f"  Trimming scene {idx} to {SCENE_DUR}s…"):
                    try:
                        _trim(raw_path, out_path)
                    except Exception as e:
                        st.error(f"Trim failed: {e}")
                        gen_status.update(label="Trim failed", state="error")
                        st.stop()

            scene_clips.append(out_path)
            st.write(f"  ✅ Scene {idx} ready → `{out_path.name}`")

        st.write("**Concatenating scenes…**")
        try:
            _concat(scene_clips, final_path)
        except Exception as e:
            st.error(f"Concat failed: {e}")
            gen_status.update(label="Concat failed", state="error")
            st.stop()

        gen_status.update(label="✅ Reel ready!", state="complete", expanded=False)

    st.session_state["final_video"] = str(final_path)

# ── Video display ─────────────────────────────────────────────────────────────
if st.session_state.get("final_video") and Path(st.session_state["final_video"]).exists():
    fpath = Path(st.session_state["final_video"])
    st.divider()
    st.subheader("🎉 Your Reel")

    vid_col, meta_col = st.columns([1, 1], gap="large")
    with vid_col:
        st.video(str(fpath))
    with meta_col:
        size_mb = fpath.stat().st_size / (1024 * 1024)
        st.markdown("**Reel details**")
        st.markdown(f"- Format: `{W}×{H}` (9:16 vertical)")
        st.markdown(f"- Duration: `{len(selected_skus) * SCENE_DUR}s`")
        st.markdown(f"- File size: `{size_mb:.1f} MB`")
        st.markdown(f"- Scenes: `{len(selected_skus)}`")
        st.markdown(f"- Codec: `H.264 / AAC`")
        st.markdown("&nbsp;")
        with open(fpath, "rb") as f:
            st.download_button(
                label="⬇️ Download final_reel.mp4",
                data=f,
                file_name="alkame_reel.mp4",
                mime="video/mp4",
                use_container_width=True,
            )
