import logging
import boto3
from botocore.exceptions import ClientError
import os
import json
import fitz
from pdf2image import convert_from_path
from f1040_2024_vision import extract_1040_2024
from f1040_2025_vision import extract_1040_2025


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
    pages= []
    # poppler_path = r"C:\Users\Lenovo\Downloads\Release-25.12.0-0\poppler-25.12.0\Library\bin"
    # if not os.path.exists(poppler_path):
    #     poppler_path = None
    # if poppler_path:
    #     pages = convert_from_path(file_path, dpi=300, poppler_path=poppler_path)

    # just make sure poppler installed on that server's OS. If it's a Linux server and if poppler error accours, run sudo apt-get install poppler-utils once during setup 

    pages = convert_from_path(file_path, dpi=300)
    return pages #should return pdf pages converted to image as list

# for checking form_year, first page is required. To pass as arg in extract_1040_2024(), image list is req. 
def detect_formyear(image_list): #pass image_list as arg after adding logic for pdf to image 

    with open(image_list[0], "rb") as f: # with open(image_list[0], "rb") as f:
        document_bytes = f.read()
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
            text = block.get("Text")
            match text:
                case "2024":
                    form_year = "2024"
                    return form_year
                case "2025":
                    form_year = "2025"
                    return form_year
                case _: #Should say that form is older than 2 years
                    print("The form is either incorrect or older than 2 years")
                    form_year=form_year.strip()
                    continue
    if form_year: 
        print("Form year detected: ", form_year) 
    if not form_year: 
        print("Form year not detected or uploaded form is older than 2 years: ", form_year) 


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

