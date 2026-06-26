from pypdf import PdfReader

file=r"C:/Users/Lenovo/Desktop/ZIPAI_proj/FormFormats/1041/f1041sk1.pdf"
import pymupdf4llm

md_text = pymupdf4llm.to_markdown(file).__str__()

with open("output.md", "w", encoding="utf-8") as f:
    f.write(md_text)