from fastapi import FastAPI
import uvicorn
import tempfile, uuid
import shutil
import os
import time
import sys, gc
from ratelimit import limits
from pathlib import Path
from fastapi import FastAPI, File, UploadFile
from Form1099.main_1099 import extract_1099_data
from FormW2.w2_extraction_final import extract_w2
from Form1041.K1_1041_extraction import extract_1041
from Form1040.main_1040 import extract_1040_data
from database.operations import Database
from database.s3 import upload_pdf

# add ratelimits for APIs

sys.path.append(str(Path(__file__).resolve().parent.parent))
print("Current Working Directory:", os.getcwd())
app = FastAPI(debug=True)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "MLO_data"}

@app.post("/v1/extract-1099")
async def upload_file_1099(file: UploadFile=File(...)):
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)
   await file.close()
   db = Database()
   try:
        s3_key = upload_pdf(temp_path, "1099")
        form1099_data, subtype = extract_1099_data(temp_path)
        db.insert_json(
            table_name="form_1099",
            json_data=form1099_data,
            s3_key=s3_key,
            subtype=subtype
        )
        return form1099_data
   finally: 
        db.close()
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
   db = Database()
   try:
        s3_key = upload_pdf(temp_path, "w2")
        w2_data = extract_w2(temp_path)
        db.insert_json(
            table_name="form_w2",
            json_data=w2_data,
            s3_key=s3_key
        )
        return w2_data
   finally: 
        db.close()
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
   db = Database()
   try:
       s3_key = upload_pdf(temp_path, "1041")
       form1041_data = extract_1041(temp_path)
       db.insert_json(
            table_name="form_1041",
            json_data=form1041_data,
            s3_key=s3_key
        )
       return form1041_data
        # return extract_1041(temp_path)
   finally: 
        db.close()
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)


@app.post("/v1/extract_1040")
async def upload_file_1040(file: UploadFile=File(...)):
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)
   await file.close()
   db = Database()
   try:
        s3_key = upload_pdf(temp_path, "1040")
        form1040_data, form_year = extract_1040_data(temp_path)
        db.insert_json(
            table_name="form_1040",
            json_data=form1040_data,
            s3_key=s3_key,
            form_year=form_year
        )
        return form1040_data
   finally: 
        db.close()
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)
           
if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
