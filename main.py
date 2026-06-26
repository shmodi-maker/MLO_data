from fastapi import FastAPI
import uvicorn
import tempfile, uuid
import shutil
import os
import time
import sys, gc
from pathlib import Path
from fastapi import FastAPI, File, UploadFile
from Form1099.main_1099 import extract_1099_data
from FormW2.w2_extraction_final import extract_w2
from Form1041.K1_1041_extraction import extract_1041



sys.path.append(str(Path(__file__).resolve().parent.parent))
# from Form1099.main_1099 import extract_file_name

print("Current Working Directory:", os.getcwd())

app = FastAPI(debug=True)
# filename = r"C:\Users\Lenovo\Desktop\ZIPAI_proj\FormFormats\1099\1099_MISC_1.pdf"

# 2. FIXED: Changed from @app.router.post to @app.post
@app.post("/v1/extract-1099")
async def upload_file_1099(file: UploadFile=File(...)):
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)
   await file.close()

   try:
        return extract_1099_data(temp_path)
   finally: 
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)

@app.post("/v1/extract_w2")

async def upload_file_w2(file: UploadFile=File(...)):
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)
   await file.close()

   try:
        return extract_w2(temp_path)
   finally: 
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)

@app.post("/v1/extract_1041")

async def upload_file_1041(file: UploadFile=File(...)):
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)
   await file.close()

   try:
        return extract_1041(temp_path)
   finally: 
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)

# DECIDE APPROACHES FOR 1040 FORM, PROPOSE 3 APPROACHES

# @app.post("/v1/extract_1040")

# async def upload_file_1040(file: UploadFile=File(...)):
#    temp_dir = tempfile.gettempdir()
#    temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

#    with open(temp_path, "wb") as buffer:
#        shutil.copyfileobj(file.file, buffer)
#    await file.close()

#    try:
#         return extract_1041(temp_path)
#    finally: 
#         if os.path.exists(temp_path):
#             gc.collect()


#             # time.sleep(1)
#             os.remove(temp_path)
           
# comment

if __name__ == "__main__":
    # 3. FIXED: Changed app to "main:app" string so reload=True works perfectly
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
