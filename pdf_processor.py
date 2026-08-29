import fitz  # PyMuPDF
import json
import os
import tempfile
from PIL import Image as PILImage


def process_pdfs(pdf_paths, config_path, platform="Amazon", output_path="output.pdf", progress_callback=None):
    """
    Process a list of PDFs and combine them into a single A4 PDF.
    All layout settings (quadrant positions, split ratio, page mapping) come from config.

    Two input modes are supported (controlled by platform config):
      - Standard mode  : each PDF file = one order (Amazon, JioMart, Meesho)
      - Multi-page mode: one PDF file contains N pages, each page = one order (Flipkart)
    """
    with open(config_path, "r") as f:
        config = json.load(f)

    platform_config = config.get("platforms", {}).get(platform, {})

    # A4 Dimensions in points
    A4_WIDTH = 595.28
    A4_HEIGHT = 841.89

    # Split ratio: how much of the width goes to the LEFT side (Q1/Q3)
    split_ratio  = platform_config.get("split_ratio", 0.5)
    # page_margin_*: blank space (pt) at each paper edge
    margin_left   = platform_config.get("page_margin_left", 0)
    margin_right  = platform_config.get("page_margin_right", 0)
    margin_top    = platform_config.get("page_margin_top", 0)
    margin_bottom = platform_config.get("page_margin_bottom", 0)
    # page_gutter_v: vertical gap (points) between top and bottom row of quadrants
    gutter_v      = platform_config.get("page_gutter_v", 0)

    usable_w = A4_WIDTH - margin_left - margin_right
    left_w   = usable_w * split_ratio
    right_w  = usable_w - left_w
    
    usable_h = A4_HEIGHT - margin_top - margin_bottom
    half_h   = (usable_h - gutter_v) / 2
    gutter_start = margin_top + half_h
    gutter_end   = gutter_start + gutter_v

    def get_quad_rect(quadrant_num):
        """Return the fitz.Rect for the given quadrant (1-4) on an A4 page."""
        x0_left  = margin_left
        x1_left  = margin_left + left_w
        x0_right = margin_left + left_w
        x1_right = A4_WIDTH - margin_right
        if quadrant_num == 1:   # Top-Left
            return fitz.Rect(x0_left,  margin_top,  x1_left,  gutter_start)
        elif quadrant_num == 2: # Top-Right
            return fitz.Rect(x0_right, margin_top,  x1_right, gutter_start)
        elif quadrant_num == 3: # Bottom-Left
            return fitz.Rect(x0_left,  gutter_end,  x1_left,  A4_HEIGHT - margin_bottom)
        elif quadrant_num == 4: # Bottom-Right
            return fitz.Rect(x0_right, gutter_end,  x1_right, A4_HEIGHT - margin_bottom)

    # Quadrant assignment from config
    default_challan_q_single = platform_config.get("challan_quadrant_single", 1)
    default_invoice_q_single = platform_config.get("invoice_quadrant_single", 2)
    default_challan_q_pair   = platform_config.get("challan_quadrant_pair", [1, 3])
    default_invoice_q_pair   = platform_config.get("invoice_quadrant_pair", [2, 4])

    c_config = platform_config.get("page_challan", platform_config.get("page1_challan", {}))
    i_config = platform_config.get("page_invoice", platform_config.get("page2_invoice", {}))

    multi_page_input = platform_config.get("multi_page_input", False)

    # Build a flat list of (doc, source_page_index) tuples — one entry per order
    order_sources = _collect_order_sources(pdf_paths, multi_page_input)

    total_orders = len(order_sources)
    if total_orders == 0:
        raise ValueError("No valid order pages found in the provided PDF files.")

    doc_out = fitz.open()
    current_out_page = None

    for order_idx, (doc_in, src_page_idx) in enumerate(order_sources):
        # Every two orders share one output A4 page
        slot = order_idx % 2
        if slot == 0:
            current_out_page = doc_out.new_page(width=A4_WIDTH, height=A4_HEIGHT)

        orders_remaining = total_orders - (order_idx - slot)
        orders_on_this_page = min(2, orders_remaining)

        if orders_on_this_page == 2:
            quad_challan = default_challan_q_pair[slot]
            quad_invoice = default_invoice_q_pair[slot]
        else:
            quad_challan = default_challan_q_single
            quad_invoice = default_invoice_q_single

        if multi_page_input:
            # Both challan and invoice come from the SAME source page
            _draw_page(current_out_page, doc_in, src_page_idx, get_quad_rect(quad_challan), c_config, slot=slot)
            _draw_page(current_out_page, doc_in, src_page_idx, get_quad_rect(quad_invoice), i_config, slot=slot)
        else:
            # Challan and invoice are on separate pages within each order PDF
            challan_page_idx = platform_config.get("challan_page_index", 0)
            invoice_page_idx = platform_config.get("invoice_page_index", 1)

            if doc_in.page_count > challan_page_idx:
                print(f"[DEBUG] Drawing CHALLAN: src_page={challan_page_idx}, quadrant={quad_challan}")
                _draw_page(current_out_page, doc_in, challan_page_idx, get_quad_rect(quad_challan), c_config, slot=slot)

            if doc_in.page_count > invoice_page_idx:
                print(f"[DEBUG] Drawing INVOICE: src_page={invoice_page_idx}, quadrant={quad_invoice}")
                _draw_page(current_out_page, doc_in, invoice_page_idx, get_quad_rect(quad_invoice), i_config, slot=slot)

        if progress_callback:
            progress_callback(order_idx + 1, total_orders)

    # Close all opened source documents
    _close_order_sources(order_sources)

    doc_out.save(output_path)
    doc_out.close()
    return output_path


def _collect_order_sources(pdf_paths, multi_page_input):
    """
    Build a flat ordered list of (fitz.Document, page_index) tuples.

    - multi_page_input=True  : open each file once and yield one entry per page.
    - multi_page_input=False : open each file once and yield a single entry (page 0
                               is used as the anchor; _draw_page selects the correct
                               page per challan/invoice).
    """
    order_sources = []
    opened_docs = {}  # path -> fitz.Document (keep open until we're done)

    for path in pdf_paths:
        if not os.path.isfile(path):
            print(f"[WARN] File not found, skipping: {path}")
            continue
        try:
            doc = fitz.open(path)
            opened_docs[path] = doc

            if multi_page_input:
                for page_idx in range(doc.page_count):
                    order_sources.append((doc, page_idx))
            else:
                order_sources.append((doc, 0))  # placeholder; real indices resolved later
        except Exception as e:
            print(f"[ERROR] Could not open {path}: {e}")

    return order_sources


def _close_order_sources(order_sources):
    """Close unique fitz.Document instances from the order source list."""
    closed = set()
    for doc, _ in order_sources:
        if id(doc) not in closed:
            doc.close()
            closed.add(id(doc))


def _draw_page(out_page, doc_in, page_num, target_rect, config, slot=0):
    """
    Render a single source page, apply crops/rotation, and insert it into
    the target rectangle on the output page.

    slot=0  → content is bottom-anchored (top half of page, pushes toward gutter)
    slot=1  → content is top-anchored    (bottom half of page, pushes toward gutter)
    This collapses dead space to the outer page edges instead of between orders.
    """
    page = doc_in[page_num]

    auto_crop           = config.get("auto_crop", True)
    crop_padding        = config.get("crop_padding", 5)
    rotate              = config.get("rotate_degrees", 0)
    suppress_dashed     = config.get("suppress_dashed_lines", False)

    # Render page to high-res image (needed for auto-crop and rotation)
    zoom = 3.0
    mat  = fitz.Matrix(zoom, zoom)
    pix  = page.get_pixmap(matrix=mat)

    tmp_src = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_src.close()
    pix.save(tmp_src.name)
    img = PILImage.open(tmp_src.name)

    print(f"[DEBUG] _draw_page: page={page_num}, size={img.size}, rotate={rotate}, auto_crop={auto_crop}")

    # --- STEP 0: Suppress dashed vector lines (e.g. Flipkart cut-marks) ------
    # These are vector paths baked into the render; we paint white over them
    # in pixel-space so they don't affect content bounding-box detection.
    if suppress_dashed:
        from PIL import ImageDraw
        drawings = page.get_drawings()
        draw_overlay = ImageDraw.Draw(img)
        for d in drawings:
            if d.get("dashes"):  # only dashed/dotted paths
                rect = d.get("rect")
                if rect is not None:  # NOTE: do NOT check is_empty — horizontal lines have y0==y1 (is_empty=True)
                    # Convert PDF points → pixels at current zoom, with ±3pt padding
                    pad_px = int(3 * zoom)
                    x0_px = max(0, int(rect.x0 * zoom) - pad_px)
                    y0_px = max(0, int(rect.y0 * zoom) - pad_px)
                    x1_px = min(img.width,  int(rect.x1 * zoom) + pad_px)
                    y1_px = min(img.height, int(rect.y1 * zoom) + pad_px)
                    if x1_px > x0_px and y1_px > y0_px:
                        draw_overlay.rectangle([x0_px, y0_px, x1_px, y1_px], fill=(255, 255, 255))
                        print(f"[DEBUG] Suppressed dashed path at PDF rect={rect}, px=({x0_px},{y0_px},{x1_px},{y1_px})")
        del draw_overlay

    # --- STEP 1a: Fixed margin crop ---
    crop    = config.get("crop_margin", {"top": 0, "bottom": 0, "left": 0, "right": 0})
    c_left  = int(crop.get("left",   0) * zoom)
    c_top   = int(crop.get("top",    0) * zoom)
    c_right = int(crop.get("right",  0) * zoom)
    c_bottom = int(crop.get("bottom", 0) * zoom)

    # Dynamic text-based cropping
    crop_bottom_text = config.get("crop_bottom_at_text")
    if crop_bottom_text:
        rects = page.search_for(crop_bottom_text)
        if rects:
            y0 = min(r.y0 for r in rects)
            c_bottom = int((page.rect.height - y0) * zoom) + int(crop.get("bottom", 0) * zoom)
            print(f"[DEBUG] '{crop_bottom_text}' found at y={y0}. bottom crop={c_bottom}")

    crop_after_text = config.get("crop_after_text")
    if crop_after_text:
        rects = page.search_for(crop_after_text)
        if rects:
            y1 = min(r.y1 for r in rects)
            c_bottom = int((page.rect.height - y1) * zoom) + int(crop.get("bottom", 0) * zoom)
            print(f"[DEBUG] '{crop_after_text}' found at y1={y1}. bottom crop={c_bottom}")

    crop_top_text = config.get("crop_top_at_text")
    if crop_top_text:
        rects = page.search_for(crop_top_text)
        if rects:
            y0 = min(r.y0 for r in rects)
            c_top = int((y0 - 2) * zoom) + int(crop.get("top", 0) * zoom)
            print(f"[DEBUG] '{crop_top_text}' found at y={y0}. top crop={c_top}")

    if c_left > 0 or c_top > 0 or c_right > 0 or c_bottom > 0:
        w, h  = img.size
        left  = max(0, c_left)
        upper = max(0, c_top)
        right = min(w, w - c_right)
        lower = min(h, h - c_bottom)
        if right > left and lower > upper:
            img = img.crop((left, upper, right, lower))
            print(f"[DEBUG] Margin/text crop applied: ({left},{upper},{right},{lower}), new_size={img.size}")

    # --- STEP 1b: Auto-content crop ---
    if auto_crop:
        from PIL import ImageOps
        gray     = img.convert("L")
        inverted = ImageOps.invert(gray)
        bbox     = inverted.getbbox()

        if bbox:
            pad_px = int(crop_padding * zoom)
            left   = max(0, bbox[0] - pad_px)
            upper  = max(0, bbox[1] - pad_px)
            right  = min(img.width,  bbox[2] + pad_px)
            lower  = min(img.height, bbox[3] + pad_px)
            img    = img.crop((left, upper, right, lower))
            print(f"[DEBUG] Auto-crop: bbox={bbox}, result=({left},{upper},{right},{lower}), size={img.size}")
        else:
            print("[DEBUG] Auto-crop: no content detected, skipping")

    # --- STEP 2: Rotate ---
    if rotate and rotate != 0:
        ccw_angle = (360 - rotate) % 360
        img = img.rotate(ccw_angle, expand=True)
        print(f"[DEBUG] Rotated {rotate}° CW, new_size={img.size}")

    # --- STEP 3: Scale and place into target rect ---
    tmp_out = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_out.close()

    img_w, img_h = img.size
    target_w = target_rect.width
    target_h = target_rect.height
    scale = min(target_w / img_w, target_h / img_h)
    new_w = img_w * scale
    new_h = img_h * scale

    # Horizontal: left-column (x0 < 200) anchors left, right-column anchors right.
    # This collapses horizontal dead space into the center fold, making outer margins strictly uniform.
    if target_rect.x0 < 200:
        x_offset = 0
    else:
        x_offset = target_w - new_w

    # Vertical: slot-0 → bottom-anchor (pushes toward gutter from above)
    #           slot-1 → top-anchor    (pushes toward gutter from below)
    y_offset = (target_h - new_h) if slot == 0 else 0

    img.save(tmp_out.name)

    centered_rect = fitz.Rect(
        target_rect.x0 + x_offset,
        target_rect.y0 + y_offset,
        target_rect.x0 + x_offset + new_w,
        target_rect.y0 + y_offset + new_h,
    )

    img.close()
    out_page.insert_image(centered_rect, filename=tmp_out.name, keep_proportion=False)
    print(f"[DEBUG] Inserted into rect={centered_rect}")

    # Cleanup temp files
    try:
        os.remove(tmp_src.name)
        os.remove(tmp_out.name)
    except OSError:
        pass


if __name__ == "__main__":
    pass
