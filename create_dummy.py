import fitz

def create_dummy_pdf(filename, text_p1, text_p2):
    doc = fitz.open()
    
    # Page 1 - Challan
    page1 = doc.new_page(width=300, height=400)
    page1.insert_text((50, 50), text_p1, fontsize=20)
    page1.draw_rect(page1.rect, color=(0, 0, 0), width=5)
    
    # Page 2 - Invoice
    page2 = doc.new_page(width=300, height=400)
    page2.insert_text((50, 50), text_p2, fontsize=20)
    page2.draw_rect(page2.rect, color=(0, 0, 0), width=5)
    
    doc.save(filename)
    doc.close()

if __name__ == "__main__":
    create_dummy_pdf("order1.pdf", "Order 1 - Challan", "Order 1 - Invoice")
    create_dummy_pdf("order2.pdf", "Order 2 - Challan", "Order 2 - Invoice")
    print("Dummy PDFs created.")
