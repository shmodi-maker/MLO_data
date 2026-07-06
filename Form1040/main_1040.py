import logging
import boto3
from botocore.exceptions import ClientError
import io
import json
import fitz
from PIL import Image
from io import BytesIO
from pdf2image import convert_from_path
from Form1040.f1040_2024_vision import extract_1040_2024
from Form1040.f1040_2025_vision import extract_1040_2025


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("1040_extractor")

AWS_REGION = "us-east-1"
TEXTRACT_CLIENT = boto3.client("textract", region_name=AWS_REGION)

# img_path = r"C:\Users\Lenovo\Desktop\ZIPAI_proj\ZipData\MLO-EXTRACTION\Form1040\Form1040_images\output_images_2024\page_1.png"
pdf_path = r"C:/Users/Lenovo/Desktop/ZIPAI_proj/FormFormats/1040/f1040_2024.pdf"


# logic for converting pdf to image. Save images in a list to pass into detect_formyear() and extract_1040_data()

def pdftoimage(file_path): 
    # pages= []
    # pages = convert_from_path(file_path, dpi=300)
    # # just make sure poppler installed on that server's OS. If it's a Linux server and if poppler error accours, run sudo apt-get install poppler-utils once during setup 
    # debug_dir = "debug_images_2025"
    # os.makedirs(debug_dir, exist_ok=True)
    # for i, page in enumerate(pages, start=1):
    #     save_path = os.path.join(debug_dir, f"page_{i}.png")
    #     page.save(save_path, "PNG")
    #     print(f"Saved: {save_path}")

    pages = []
    doc = fitz.open(file_path)
    print(type(doc))
    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        pages.append(img)
    doc.close()

    return pages #should return pdf pages converted to image as list

# for checking form_year, first page is required. To pass as arg in extract_1040_2024(), image list is req. 
def detect_formyear(image_list): #pass image_list as arg after adding logic for pdf to image 
    image = image_list[0]
    buffer = BytesIO()

    image.save(buffer, format="PNG")
    document_bytes = buffer.getvalue()

    # with open(image_list[0], "rb") as f: # with open(image_list[0], "rb") as f:
    #     document_bytes = f.read()
    try:      
        response = TEXTRACT_CLIENT.analyze_document(
            FeatureTypes=['TABLES', 'FORMS', 'LAYOUT'],
            Document={"Bytes": document_bytes}
        )
    except ClientError as e:
        logger.error("Textract API error: %s", e)
        raise

    # Improve this logic to remove hardcoded years
    form_year = "" 
    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE":
            continue

        text = block.get("Text", "").strip()
        if text in ("2024", "2025"):
            print(f"Form year detected: {text}")
            return text
        

    print("The form is either incorrect or older than 2 years")
    return None


# Call detect_formyear() here to detect year
def extract_1040_data(file_path): #pass image_list as arg after adding logic
    image_list = pdftoimage(file_path)
    year = detect_formyear(image_list) #pass image_list as arg after adding logic

    match year:
        case "2024":
            year = "2024"
            extracted_data=extract_1040_2024(image_list)
            return extracted_data
        case "2025":
            year = "2025"
            extracted_data=extract_1040_2025(image_list)
            return extracted_data
            
# extract_1040_data(pdf_path)

