import os
from pdf2image import convert_from_path

# Path to your PDF file
# pdf_path = r"C:/Users/Lenovo/Desktop/ZIPAI_proj/FormFormats/1040/f1040married_flat.pdf"
# output_img=r"Form1040_images/output_images_2025"

pdf_path = r"C:/Users/Lenovo/Desktop/ZIPAI_proj/FormFormats/1040/f1040_2024.pdf"
output_img=r"Form1040_images/output_images_2024"
# Convert PDF pages to images (Set DPI for higher quality)
poppler_path = r"C:\Users\Lenovo\Downloads\Release-25.12.0-0\poppler-25.12.0\Library\bin"
if not os.path.exists(poppler_path):
    poppler_path = None

pages = convert_from_path(pdf_path, dpi=300, poppler_path=poppler_path)

# Save each page as a PNG image
if output_img and not os.path.exists(output_img):
    os.makedirs(output_img)

try:
    for index, page in enumerate(pages):
        page.save(f"{output_img}/page_{index + 1}.png", "PNG")
    print(f"{len(pages)} images saved at: {output_img}")
    
except Exception as e:
    print(f"Failed to save images: {e}")
