import fitz  # PyMuPDF
import json
import os
import tempfile
from PIL import Image as PILImage


def process_pdfs(pdf_paths, config_path, platform="Amazon", output_path="output.pdf", progress_callback=None):
    """
    Process a list of PDFs and combine them into a single A4 PDF.
    All layout settings (quadrant positions, split ratio, page mapping) come from config.
    """
    with open(config_path, "r") as f:
        config = json.load(f)

    platform_config = config.get("platforms", {}).get(platform, {})

    # A4 Dimensions in points
    A4_WIDTH = 595.28
    A4_HEIGHT = 841.89

    # Split ratio: how much of the width goes to the LEFT side (Q1/Q3)
    # Default 0.5 = equal halves. Use 0.35 to give 35% left, 65% right.
    split_ratio = platform_config.get("split_ratio", 0.5)

    left_w = A4_WIDTH * split_ratio
    right_w = A4_WIDTH - left_w
    half_h = A4_HEIGHT / 2

    def get_quad_rect(quadrant_num):
        if quadrant_num == 1:  # Top-Left
            return fitz.Rect(0, 0, left_w, half_h)
        elif quadrant_num == 2:  # Top-Right
            return fitz.Rect(left_w, 0, A4_WIDTH, half_h)
        elif quadrant_num == 3:  # Bottom-Left
            return fitz.Rect(0, half_h, left_w, A4_HEIGHT)
        elif quadrant_num == 4:  # Bottom-Right
            return fitz.Rect(left_w, half_h, A4_WIDTH, A4_HEIGHT)

    # Quadrant assignment from config (defaults: challan=left, invoice=right)
    default_challan_q_single = platform_config.get("challan_quadrant_single", 1)
    default_invoice_q_single = platform_config.get("invoice_quadrant_single", 2)
    default_challan_q_pair = platform_config.get("challan_quadrant_pair", [1, 3])
    default_invoice_q_pair = platform_config.get("invoice_quadrant_pair", [2, 4])

    # Page index mapping from config (defaults: page 0=challan, page 1=invoice)
    challan_page_idx = platform_config.get("challan_page_index", 0)
    invoice_page_idx = platform_config.get("invoice_page_index", 1)

    doc_out = fitz.open()
    total_pdfs = len(pdf_paths)
    current_out_page = None

    for i, path in enumerate(pdf_paths):
        if i % 2 == 0:
            current_out_page = doc_out.new_page(width=A4_WIDTH, height=A4_HEIGHT)

        doc_in = fitz.open(path)
        order_idx = i % 2  # 0 or 1 on this page

        base_i = i - order_idx
        orders_on_this_page = min(2, total_pdfs - base_i)

        if orders_on_this_page == 2:
            quad_challan = default_challan_q_pair[order_idx]
            quad_invoice = default_invoice_q_pair[order_idx]
        else:
            quad_challan = default_challan_q_single
            quad_invoice = default_invoice_q_single

        # Draw Challan
        if doc_in.page_count > challan_page_idx:
            c_config = platform_config.get("page_challan", platform_config.get("page1_challan", {}))
            c_rect = get_quad_rect(quad_challan)
            print(f"[DEBUG] Drawing CHALLAN: page_idx={challan_page_idx}, quadrant={quad_challan}, rect={c_rect}")
            _draw_page(current_out_page, doc_in, challan_page_idx, c_rect, c_config)

        # Draw Invoice
        if doc_in.page_count > invoice_page_idx:
            i_config = platform_config.get("page_invoice", platform_config.get("page2_invoice", {}))
            i_rect = get_quad_rect(quad_invoice)
            print(f"[DEBUG] Drawing INVOICE: page_idx={invoice_page_idx}, quadrant={quad_invoice}, rect={i_rect}")
            _draw_page(current_out_page, doc_in, invoice_page_idx, i_rect, i_config)

        doc_in.close()

        if progress_callback:
            progress_callback(i + 1, total_pdfs)

    doc_out.save(output_path)
    doc_out.close()
    return output_path


def _draw_page(out_page, doc_in, page_num, target_rect, config):
    page = doc_in[page_num]

    auto_crop = config.get("auto_crop", True)  # Default: auto-detect content
    crop_padding = config.get("crop_padding", 5)  # pts padding around detected content
    rotate = config.get("rotate_degrees", 0)

    # Render page to high-res image first (needed for both auto-crop and rotation)
    zoom = 3.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)

    # Save pixmap to temp file and open with Pillow
    tmp_src = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_src.close()
    pix.save(tmp_src.name)
    img = PILImage.open(tmp_src.name)

    print(f"[DEBUG] _draw_page: page={page_num}, size={img.size}, rotate={rotate}, auto_crop={auto_crop}")

    # --- STEP 1a: Fixed Crop (if defined) ---
    crop = config.get("crop_margin", {"top": 0, "bottom": 0, "left": 0, "right": 0})
    c_left = int(crop.get("left", 0) * zoom)
    c_top = int(crop.get("top", 0) * zoom)
    c_right = int(crop.get("right", 0) * zoom)
    c_bottom = int(crop.get("bottom", 0) * zoom)

    # Dynamic cropping based on text search
    crop_bottom_text = config.get("crop_bottom_at_text")
    if crop_bottom_text:
        rects = page.search_for(crop_bottom_text)
        if rects:
            # Find the highest occurrence (smallest y0) in case there are multiple
            y0 = min(r.y0 for r in rects)
            c_bottom = int((page.rect.height - y0) * zoom) + int(crop.get("bottom", 0) * zoom)
            print(f"[DEBUG] Found '{crop_bottom_text}' at y={y0}. Adaptive bottom crop={c_bottom}")
            
    crop_after_text = config.get("crop_after_text")
    if crop_after_text:
        rects = page.search_for(crop_after_text)
        if rects:
            # Find the highest occurrence (smallest y1) in case there are multiple
            y1 = min(r.y1 for r in rects)
            c_bottom = int((page.rect.height - y1) * zoom) + int(crop.get("bottom", 0) * zoom)
            print(f"[DEBUG] Found '{crop_after_text}' at y1={y1}. Adaptive bottom crop={c_bottom}")

    crop_top_text = config.get("crop_top_at_text")
    if crop_top_text:
        rects = page.search_for(crop_top_text)
        if rects:
            y0 = min(r.y0 for r in rects)
            c_top = int((y0 - 2) * zoom) + int(crop.get("top", 0) * zoom)
            print(f"[DEBUG] Found '{crop_top_text}' at y={y0}. Adaptive top crop={c_top}")

    if c_left > 0 or c_top > 0 or c_right > 0 or c_bottom > 0:
        w, h = img.size
        left = max(0, c_left)
        upper = max(0, c_top)
        right = min(w, w - c_right)
        lower = min(h, h - c_bottom)
        if right > left and lower > upper:
            img = img.crop((left, upper, right, lower))
            print(f"[DEBUG] Fixed/Adaptive crop applied: ({left},{upper},{right},{lower}), new_size={img.size}")

    # --- STEP 1b: Auto Crop ---
    if auto_crop:
        from PIL import ImageOps
        gray = img.convert("L")
        inverted = ImageOps.invert(gray)
        bbox = inverted.getbbox()

        if bbox:
            pad_px = int(crop_padding * zoom)
            left = max(0, bbox[0] - pad_px)
            upper = max(0, bbox[1] - pad_px)
            right = min(img.width, bbox[2] + pad_px)
            lower = min(img.height, bbox[3] + pad_px)
            img = img.crop((left, upper, right, lower))
            print(f"[DEBUG] Auto-cropped: bbox={bbox}, padded=({left},{upper},{right},{lower}), new_size={img.size}")
        else:
            print(f"[DEBUG] Auto-crop: no content detected")

    # --- STEP 2: Rotate ---
    if rotate and rotate != 0:
        # rotate() angle is counter-clockwise; config 90 = CW 90 = CCW 270
        ccw_angle = (360 - rotate) % 360
        img = img.rotate(ccw_angle, expand=True)
        print(f"[DEBUG] Rotated {rotate}° CW, new_size={img.size}")

    # --- STEP 3: Insert into PDF ---
    tmp_out = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_out.close()
    img.save(tmp_out.name)
    
    # Calculate centered bounding box
    img_w, img_h = img.size
    target_w = target_rect.width
    target_h = target_rect.height
    scale = min(target_w / img_w, target_h / img_h)
    new_w = img_w * scale
    new_h = img_h * scale
    
    x_offset = (target_w - new_w) / 2
    y_offset = (target_h - new_h) / 2
    
    centered_rect = fitz.Rect(
        target_rect.x0 + x_offset,
        target_rect.y0 + y_offset,
        target_rect.x0 + x_offset + new_w,
        target_rect.y0 + y_offset + new_h
    )
    
    img.close()

    out_page.insert_image(centered_rect, filename=tmp_out.name, keep_proportion=False)
    print(f"[DEBUG] Inserted into rect={centered_rect}")

    # Cleanup temp files
    try:
        os.remove(tmp_src.name)
        os.remove(tmp_out.name)
    except:
        pass


if __name__ == "__main__":
    pass

