"""
dev_app.py — Gradio-based web dev environment for ecom-print.

Run:
    python dev_app.py

Opens at http://localhost:7860 with hot-reload on file changes.
This file lives only on the `web-dev` branch and is never merged to main/dev.
"""

import os
import sys
import json
import tempfile
import traceback

import gradio as gr
import fitz  # PyMuPDF
from PIL import Image
import io
import importlib

# ── Resolve paths relative to this file so it works from any cwd ─────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")

# Import the real processing engine as a MODULE (not just the function) so
# importlib.reload() can hot-swap it on every Generate click.
sys.path.insert(0, _BASE_DIR)
import pdf_processor


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_platforms() -> list[str]:
    """Read platform names from config.json."""
    try:
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
        platforms = list(config.get("platforms", {}).keys())
        if platforms:
            return platforms
    except Exception as e:
        print(f"[WARN] Could not load platforms from config: {e}")
    return ["Amazon", "Flipkart", "JioMart", "Meesho"]


def _pdf_to_page_images(pdf_path: str, dpi: int = 150) -> list[Image.Image]:
    """Render every page of a PDF to a PIL Image list."""
    images = []
    try:
        doc = fitz.open(pdf_path)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            images.append(img)
        doc.close()
    except Exception as e:
        print(f"[ERROR] PDF render failed: {e}")
    return images


# ── Core processing function (called by Gradio) ───────────────────────────────

def run_processing(uploaded_files, platform: str, progress=gr.Progress()):
    """
    Process uploaded PDFs with the real pdf_processor engine.
    Reloads pdf_processor module on every call so code changes are live
    without restarting the server.

    Args:
        uploaded_files: list of file paths from gr.File
        platform: selected platform string
        progress: Gradio progress tracker

    Returns:
        Tuple of (output_pdf_path, gallery_images, status_message)
    """
    # ── Hot-reload pdf_processor so .py edits are picked up immediately ───────
    importlib.reload(pdf_processor)
    process_pdfs = pdf_processor.process_pdfs

    # ── Validate inputs ───────────────────────────────────────────────────────
    if not uploaded_files:
        return None, [], gr.update(value="⚠️ Please upload at least one PDF file.", visible=True)

    if not platform:
        return None, [], gr.update(value="⚠️ Please select a platform.", visible=True)

    if not os.path.exists(CONFIG_PATH):
        return None, [], gr.update(value=f"❌ config.json not found at: {CONFIG_PATH}", visible=True)

    # Gradio gives us a list of file paths
    pdf_paths = [f.name if hasattr(f, "name") else f for f in uploaded_files]

    # Validate all are PDFs
    invalid = [p for p in pdf_paths if not p.lower().endswith(".pdf")]
    if invalid:
        names = ", ".join(os.path.basename(p) for p in invalid)
        return None, [], gr.update(value=f"❌ Non-PDF file(s) detected: {names}", visible=True)

    # ── Run processing ────────────────────────────────────────────────────────
    output_path = os.path.join(tempfile.gettempdir(), "ecom_print_web_output.pdf")

    def _progress_cb(current, total):
        progress(current / total, desc=f"Processing order {current} of {total}…")

    try:
        progress(0, desc="Starting…")
        process_pdfs(
            pdf_paths=pdf_paths,
            config_path=CONFIG_PATH,
            platform=platform,
            output_path=output_path,
            progress_callback=_progress_cb,
        )
        progress(1, desc="Done!")
    except ValueError as e:
        return None, [], gr.update(value=f"❌ Processing error: {e}", visible=True)
    except Exception as e:
        traceback.print_exc()
        return None, [], gr.update(value=f"❌ Unexpected error: {e}", visible=True)

    if not os.path.exists(output_path):
        return None, [], gr.update(value="❌ Processing finished but output file was not created.", visible=True)

    # ── Render preview images ─────────────────────────────────────────────────
    preview_images = _pdf_to_page_images(output_path, dpi=150)
    if not preview_images:
        return output_path, [], gr.update(value="⚠️ Output created but preview rendering failed.", visible=True)

    page_count = len(preview_images)
    status_msg = f"✅ Done! {len(pdf_paths)} file(s) processed → {page_count} output page(s)."
    return output_path, preview_images, gr.update(value=status_msg, visible=True)


# ── Build the Gradio UI ───────────────────────────────────────────────────────

_THEME = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="slate",
    neutral_hue="gray",
)

_CSS = """
#title { text-align: center; }
#status-box { border-radius: 8px; font-weight: 600; }
.gradio-container { max-width: 1100px; margin: auto; }
"""


def build_ui() -> gr.Blocks:
    platforms = _load_platforms()

    with gr.Blocks(title="ecom-print — Dev Server") as demo:

        # ── Header ────────────────────────────────────────────────────────────
        gr.Markdown(
            "# 🖨️ E-commerce Invoice & Challan Printer\n"
            "> **Dev environment** — `config.json` changes and `pdf_processor.py` "
            "code changes are both picked up on every run (hot-reload via importlib).",
            elem_id="title",
        )

        # ── Main layout ───────────────────────────────────────────────────────
        with gr.Row():
            # Left column — controls
            with gr.Column(scale=1, min_width=300):
                platform_radio = gr.Radio(
                    choices=platforms,
                    value=platforms[0],
                    label="Platform",
                    info="Select the e-commerce platform for the uploaded invoices.",
                )

                file_upload = gr.File(
                    label="Upload PDF Invoice(s)",
                    file_types=[".pdf"],
                    file_count="multiple",
                    height=200,
                )

                process_btn = gr.Button(
                    "⚙️ Generate Output PDF",
                    variant="primary",
                    size="lg",
                )

                status_box = gr.Textbox(
                    label="Status",
                    interactive=False,
                    visible=False,
                    elem_id="status-box",
                    lines=2,
                )

                download_btn = gr.File(
                    label="⬇️ Download Output PDF",
                    visible=False,
                    interactive=False,
                )

            # Right column — preview
            with gr.Column(scale=2):
                gr.Markdown("### 📄 Output Preview")
                gallery = gr.Gallery(
                    label="Output pages",
                    show_label=False,
                    columns=2,
                    height=600,
                    object_fit="contain",
                    preview=True,
                )

        # ── Config inspector (collapsible) ────────────────────────────────────
        with gr.Accordion("🔧 Active config.json", open=False):
            try:
                with open(CONFIG_PATH) as f:
                    raw_config = f.read()
            except Exception:
                raw_config = "Could not read config.json"

            config_box = gr.Code(
                value=raw_config,
                language="json",
                label="config.json (read-only here — edit the file directly)",
                interactive=False,
            )

        # ── Wiring ────────────────────────────────────────────────────────────
        def on_process(files, platform):
            pdf_out, images, status = run_processing(files, platform)
            download_visible = pdf_out is not None and os.path.exists(str(pdf_out))
            return (
                images,
                status,
                gr.update(value=pdf_out, visible=download_visible),
            )

        process_btn.click(
            fn=on_process,
            inputs=[file_upload, platform_radio],
            outputs=[gallery, status_box, download_btn],
            show_progress=True,
        )

        # Reset status when files change
        file_upload.change(
            fn=lambda _: gr.update(value="", visible=False),
            inputs=[file_upload],
            outputs=[status_box],
        )

    return demo


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    demo = build_ui()
    demo.launch(
        server_name="0.0.0.0",  # accessible on local network too
        server_port=7860,
        share=False,
        show_error=True,
        theme=_THEME,
        css=_CSS,
    )
