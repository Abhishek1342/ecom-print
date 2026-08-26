import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES
import os
import platform
import shutil
import threading
from tkinter import filedialog
from pdf_processor import process_pdfs
import json
import sys
import fitz
from PIL import Image
import io

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import win32print
    import win32ui
    import win32con
    from PIL import ImageWin

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class App(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self.title("E-commerce Invoice & Challan Printer")
        self.geometry("900x600")
        
        self.pdf_files = []
        # Look for config.json bundled inside exe first, then alongside exe
        if getattr(sys, 'frozen', False):
            bundled = os.path.join(sys._MEIPASS, 'config.json')
            if os.path.exists(bundled):
                self.config_path = bundled
            else:
                self.config_path = os.path.join(os.path.dirname(sys.executable), 'config.json')
        else:
            self.config_path = os.path.abspath('config.json')
        
        # Output to temp directory so it works from any location
        import tempfile
        self.output_path = os.path.join(tempfile.gettempdir(), "InvoicePrinter_output.pdf")
        
        self.current_preview_image = None
        self.current_preview_page = 0
        self.total_preview_pages = 0
        self.manual_platform_override = False
        
        self.setup_ui()

    def load_platforms(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    config = json.load(f)
                platforms = list(config.get("platforms", {}).keys())
                if platforms:
                    return platforms
        except Exception as e:
            print(f"Config load error: {e}")
        return ["Amazon", "Flipkart", "JioMart", "Meesho"]

    def detect_platform_from_filename(self, filename):
        """Auto-detect platform from filename patterns in config."""
        basename = os.path.basename(filename)
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    config = json.load(f)
                platforms = config.get("platforms", {})
                for platform_name, platform_data in platforms.items():
                    patterns = platform_data.get("filename_patterns", [])
                    for pattern in patterns:
                        if pattern in basename:
                            return platform_name
        except Exception as e:
            print(f"Error detecting platform from filename: {e}")
        return None

    def on_platform_manual_select(self, value):
        """Called when user manually clicks a platform chip."""
        self.manual_platform_override = True
        self.platform_var.set(value)
        # Auto-regenerate if we have files loaded
        if len(self.pdf_files) > 0:
            self.start_processing()
        elif self.total_preview_pages > 0:
            self.show_generate_buttons()

    def setup_ui(self):
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Left Panel (Controls)
        self.left_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.left_panel.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.title_label = ctk.CTkLabel(self.left_panel, text="PDF Batch Processor", font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.pack(pady=(0, 20))
        
        # Platform Segmented Button (Chips)
        platforms = self.load_platforms()
        default_platform = platforms[0] if platforms else "Amazon"
        self.platform_var = ctk.StringVar(value=default_platform)
        
        self.platform_chips = ctk.CTkSegmentedButton(
            self.left_panel,
            values=platforms,
            variable=self.platform_var,
            command=self.on_platform_manual_select
        )
        self.platform_chips.pack(pady=10, fill="x")

        # Dropzone
        self.drop_frame = ctk.CTkFrame(self.left_panel, height=180, corner_radius=15, border_width=2, border_color="gray50")
        self.drop_frame.pack(pady=15, fill="x")
        self.drop_frame.pack_propagate(False)
        
        self.drop_icon = ctk.CTkLabel(self.drop_frame, text="📄", font=ctk.CTkFont(size=36))
        self.drop_icon.place(relx=0.5, rely=0.35, anchor="center")
        
        self.drop_label = ctk.CTkLabel(self.drop_frame, text="Drag & Drop PDF Files Here", font=ctk.CTkFont(size=14))
        self.drop_label.place(relx=0.5, rely=0.6, anchor="center")
        
        self.file_count_label = ctk.CTkLabel(self.drop_frame, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#28a745")
        self.file_count_label.place(relx=0.5, rely=0.8, anchor="center")
        
        # Enable drag & drop
        self.drop_frame.drop_target_register(DND_FILES)
        self.drop_frame.dnd_bind('<<Drop>>', self.on_drop)
        
        # Progress Bar
        self.progress = ctk.CTkProgressBar(self.left_panel)
        self.progress.set(0)
        self.progress.pack(pady=10, fill="x")
        
        # Action Buttons Frame
        self.btn_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.btn_frame.pack(pady=10)
        
        # Row 0: Clear + Generate/Print
        self.btn_row0 = ctk.CTkFrame(self.btn_frame, fg_color="transparent")
        self.btn_row0.pack(pady=5)
        
        self.clear_btn = ctk.CTkButton(self.btn_row0, text="Clear", command=self.clear_files, fg_color="#ff5555", hover_color="#ff3333", width=120, height=45, font=ctk.CTkFont(size=14, weight="bold"))
        self.clear_btn.pack(side="left", padx=8)
        
        self.process_btn = ctk.CTkButton(self.btn_row0, text="Generate", command=self.start_processing, width=120, height=45, font=ctk.CTkFont(size=14, weight="bold"))
        self.process_btn.pack(side="left", padx=8)

        self.print_btn = ctk.CTkButton(self.btn_row0, text="🖨 Print", command=self.print_pdf, fg_color="#28a745", hover_color="#218838", width=120, height=45, font=ctk.CTkFont(size=14, weight="bold"))
        if not IS_WINDOWS:
            self.print_btn.configure(state="disabled", text="🖨 Print (Windows only)")
        # Hidden initially
        
        # Row 1: Save as PDF
        self.btn_row1 = ctk.CTkFrame(self.btn_frame, fg_color="transparent")
        
        self.save_btn = ctk.CTkButton(self.btn_row1, text="💾 Save as PDF", command=self.save_pdf, fg_color="#17a2b8", hover_color="#138496", width=160, height=38, font=ctk.CTkFont(size=13))
        self.save_btn.pack(pady=2)
        # Hidden initially
        
        self.status_label = ctk.CTkLabel(self.left_panel, text="", text_color="red")
        self.status_label.pack(pady=10)
        
        # Right Panel (Preview)
        self.right_panel = ctk.CTkFrame(self, corner_radius=10)
        self.right_panel.grid(row=0, column=1, padx=(0, 20), pady=20, sticky="nsew")
        self.right_panel.pack_propagate(False)
        
        self.preview_title = ctk.CTkLabel(self.right_panel, text="Preview", font=ctk.CTkFont(size=16, weight="bold"))
        self.preview_title.pack(pady=5)
        
        self.preview_label = ctk.CTkLabel(self.right_panel, text="No preview available")
        self.preview_label.pack(expand=True, fill="both", padx=10, pady=5)
        
        # Preview Controls
        self.preview_controls = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.preview_controls.pack(pady=10)
        
        self.prev_btn = ctk.CTkButton(self.preview_controls, text="< Prev", command=self.prev_page, width=60, state="disabled")
        self.prev_btn.pack(side="left", padx=10)
        
        self.page_label = ctk.CTkLabel(self.preview_controls, text="Page 0 of 0")
        self.page_label.pack(side="left", padx=10)
        
        self.next_btn = ctk.CTkButton(self.preview_controls, text="Next >", command=self.next_page, width=60, state="disabled")
        self.next_btn.pack(side="left", padx=10)
        
        # Bind resize event to the right panel to dynamically resize the preview
        self.right_panel.bind("<Configure>", self.on_resize_preview)

    def show_generate_buttons(self):
        """Show Clear + Generate layout (default state)."""
        self.print_btn.pack_forget()
        self.btn_row1.pack_forget()
        self.process_btn.pack(side="left", padx=8)

    def show_print_buttons(self):
        """Show Clear + Print + Save layout (post-generation state)."""
        self.process_btn.pack_forget()
        self.print_btn.pack(side="left", padx=8)
        self.btn_row1.pack(pady=5)

    def on_drop(self, event):
        files = self.split_dnd_files(event.data)
        for f in files:
            if f.lower().endswith(".pdf") and f not in self.pdf_files:
                self.pdf_files.append(f)
                
                # Auto-detect platform from filename (only if user hasn't manually selected)
                if not self.manual_platform_override:
                    detected = self.detect_platform_from_filename(f)
                    if detected:
                        self.platform_var.set(detected)
        
        count = len(self.pdf_files)
        if count > 0:
            # Visual feedback: green border + updated text
            self.drop_frame.configure(border_color="#28a745")
            self.drop_icon.configure(text="✅")
            self.drop_label.configure(text=f"{count} PDF{'s' if count > 1 else ''} ready")
            self.file_count_label.configure(text=f"Drop more or click Generate")

    def split_dnd_files(self, data):
        if "{" in data:
            import re
            return re.findall(r'\{(.*?)\}', data)
        return data.split()

    def clear_files(self):
        self.pdf_files = []
        self.progress.set(0)
        self.process_btn.configure(state="normal")
        self.manual_platform_override = False
        self.current_preview_image = None
        self.current_preview_page = 0
        self.total_preview_pages = 0
        self.update_preview_controls()
        self.preview_label.configure(image="", text="No preview available")
        self.status_label.configure(text="")
        # Reset drop zone appearance
        self.drop_frame.configure(border_color="gray50")
        self.drop_icon.configure(text="📄")
        self.drop_label.configure(text="Drag & Drop PDF Files Here")
        self.file_count_label.configure(text="")
        self.show_generate_buttons()

    def start_processing(self):
        if not self.pdf_files:
            return
            
        self.process_btn.configure(state="disabled")
        self.clear_btn.configure(state="disabled")
        self.progress.set(0)
        self.status_label.configure(text="")
        
        self.current_preview_image = None
        self.current_preview_page = 0
        self.total_preview_pages = 0
        self.update_preview_controls()
        
        self.preview_label.configure(image="", text="Processing...")
        
        # Run in a separate thread so UI doesn't freeze
        t = threading.Thread(target=self.process_pdfs_thread)
        t.start()

    def update_progress(self, current, total):
        self.after(0, self._do_update_progress, current, total)
        
    def _do_update_progress(self, current, total):
        self.progress.set(current / total)

    def process_pdfs_thread(self):
        platform = self.platform_var.get()
        try:
            process_pdfs(self.pdf_files, self.config_path, platform, self.output_path, self.update_progress)
            self.after(0, self.processing_complete)
        except Exception as e:
            print(f"Error: {e}")
            self.after(0, self.processing_error)
            
    def processing_complete(self):
        self.file_count_label.configure(text="Processing complete!", text_color="green")
        self.clear_btn.configure(state="normal")
        
        # Swap buttons: Generate -> Print + Save
        self.show_print_buttons()
        
        # Initialize preview
        if os.path.exists(self.output_path):
            doc = fitz.open(self.output_path)
            self.total_preview_pages = doc.page_count
            doc.close()
            
            if self.total_preview_pages > 0:
                self.current_preview_page = 0
                self.render_preview(self.current_preview_page)
                self.update_preview_controls()

    def prev_page(self):
        if self.current_preview_page > 0:
            self.current_preview_page -= 1
            self.render_preview(self.current_preview_page)
            self.update_preview_controls()

    def next_page(self):
        if self.current_preview_page < self.total_preview_pages - 1:
            self.current_preview_page += 1
            self.render_preview(self.current_preview_page)
            self.update_preview_controls()

    def update_preview_controls(self):
        if self.total_preview_pages == 0:
            self.page_label.configure(text="Page 0 of 0")
            self.prev_btn.configure(state="disabled")
            self.next_btn.configure(state="disabled")
            return
            
        self.page_label.configure(text=f"Page {self.current_preview_page + 1} of {self.total_preview_pages}")
        
        self.prev_btn.configure(state="normal" if self.current_preview_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if self.current_preview_page < self.total_preview_pages - 1 else "disabled")

    def render_preview(self, page_index):
        try:
            if not os.path.exists(self.output_path):
                return
                
            doc = fitz.open(self.output_path)
            if doc.page_count > page_index:
                page = doc[page_index]
                # Render to pixmap with slight scaling for preview quality
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                # Convert pixmap to PIL Image
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                self.current_preview_image = img
                self.on_resize_preview(None)
                
            doc.close()
        except Exception as e:
            print("Preview generation failed:", e)
            self.preview_label.configure(text="Preview generation failed")
            
    def on_resize_preview(self, event):
        if not self.current_preview_image:
            return
            
        # Safely get available dimensions
        available_w = self.right_panel.winfo_width() - 40 # padding
        available_h = self.right_panel.winfo_height() - 100 # title + controls + padding
        
        if available_w < 50 or available_h < 50:
            return
            
        img_w, img_h = self.current_preview_image.size
        img_ratio = img_w / img_h
        avail_ratio = available_w / available_h
        
        if img_ratio > avail_ratio:
            # Fit to width
            target_w = available_w
            target_h = int(target_w / img_ratio)
        else:
            # Fit to height
            target_h = available_h
            target_w = int(target_h * img_ratio)
            
        # Protect against 0 sizing
        target_w = max(10, target_w)
        target_h = max(10, target_h)
            
        ctk_img = ctk.CTkImage(light_image=self.current_preview_image, dark_image=self.current_preview_image, size=(target_w, target_h))
        self.preview_label.configure(image=ctk_img, text="")

    def processing_error(self):
        self.file_count_label.configure(text="Error during processing!", text_color="red")
        self.process_btn.configure(state="normal")
        self.clear_btn.configure(state="normal")

    def save_pdf(self):
        if not os.path.exists(self.output_path):
            return
            
        default_name = "Invoice_Challan_Combined.pdf"
        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            initialfile=default_name,
            title="Save PDF As",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")]
        )
        
        if filepath:
            try:
                shutil.copy2(self.output_path, filepath)
                self.status_label.configure(text="✓ PDF Saved Successfully!", text_color="green")
            except Exception as e:
                self.status_label.configure(text=f"Failed to save: {e}", text_color="red")

    def print_pdf(self):
        if not IS_WINDOWS:
            self.status_label.configure(text="Direct printing is only supported on Windows.", text_color="red")
            return
        if not os.path.exists(self.output_path):
            return
        
        # Run print in background thread to keep UI responsive
        self.print_btn.configure(state="disabled")
        self.status_label.configure(text="Sending to printer...", text_color="gray")
        t = threading.Thread(target=self._print_thread)
        t.daemon = True
        t.start()

    def _print_thread(self):
        try:
            printer_name = win32print.GetDefaultPrinter()
            doc = fitz.open(self.output_path)

            hprinter = win32print.OpenPrinter(printer_name)
            printer_info = win32print.GetPrinter(hprinter, 2)
            devmode = printer_info['pDevMode']
            # Set to portrait, A4
            devmode.PaperSize = win32con.DMPAPER_A4
            devmode.Orientation = win32con.DMORIENT_PORTRAIT
            win32print.ClosePrinter(hprinter)

            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)

            # Get physical printer dimensions in pixels
            printer_w = hdc.GetDeviceCaps(win32con.PHYSICALWIDTH)
            printer_h = hdc.GetDeviceCaps(win32con.PHYSICALHEIGHT)
            # Get the unprintable offset margins
            offset_x = hdc.GetDeviceCaps(win32con.PHYSICALOFFSETX)
            offset_y = hdc.GetDeviceCaps(win32con.PHYSICALOFFSETY)
            # Printable area
            printable_w = hdc.GetDeviceCaps(win32con.HORZRES)
            printable_h = hdc.GetDeviceCaps(win32con.VERTRES)

            hdc.StartDoc(self.output_path)

            for page_num in range(doc.page_count):
                page = doc[page_num]
                # Render page at high DPI matching printer resolution
                dpi = hdc.GetDeviceCaps(win32con.LOGPIXELSX)
                zoom = dpi / 72.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)

                img_data = pix.tobytes("png")
                # Convert to grayscale then back to RGB (ImageWin.Dib requires RGB)
                img = Image.open(io.BytesIO(img_data)).convert("L").convert("RGB")

                # Scale image to fit printable area while keeping aspect ratio
                img_ratio = img.width / img.height
                area_ratio = printable_w / printable_h
                if img_ratio > area_ratio:
                    draw_w = printable_w
                    draw_h = int(printable_w / img_ratio)
                else:
                    draw_h = printable_h
                    draw_w = int(printable_h * img_ratio)

                hdc.StartPage()
                dib = ImageWin.Dib(img)
                # Center on printable area
                x_offset = (printable_w - draw_w) // 2
                y_offset = (printable_h - draw_h) // 2
                dib.draw(hdc.GetHandleOutput(),
                         (x_offset, y_offset, x_offset + draw_w, y_offset + draw_h))
                hdc.EndPage()

            hdc.EndDoc()
            hdc.DeleteDC()
            doc.close()

            self.after(0, lambda: [
                self.status_label.configure(text=f"✓ Sent {doc.page_count} page(s) to printer!", text_color="green"),
                self.print_btn.configure(state="normal")
            ])
        except Exception as e:
            print(f"Direct print failed: {e}")
            self.after(0, lambda err=str(e): [
                self.status_label.configure(text=f"Print error: {err}", text_color="red"),
                self.print_btn.configure(state="normal")
            ])

if __name__ == "__main__":
    app = App()
    app.mainloop()
