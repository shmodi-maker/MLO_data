import uvicorn
import tempfile, uuid
import shutil
import os
import time
import sys, gc
from ratelimit import limits
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from Form1099.main_1099 import extract_1099_data
from FormW2.w2_extraction_final import extract_w2
from Form1041.K1_1041_extraction import extract_1041
from Form1040.main_1040 import extract_1040_data
from database.operations import Database
from database.s3 import upload_pdf
from credit_report.credit_api import get_credit_report
from paystub.paystub_ext import extract_paystub

# add ratelimits for APIs

sys.path.append(str(Path(__file__).resolve().parent.parent))
print("Current Working Directory:", os.getcwd())
app = FastAPI(debug=True)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "MLO_data"}

# ----- insertion APIs ----- 

# for 1099
@app.post("/v1/extract-1099")
async def upload_file_1099(
    user_id: str = Form(...), 
    file: UploadFile=File(...)
    ):
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)
   await file.close()
   db = Database()
   try:
        s3_key = upload_pdf(temp_path, "1099")
        form1099_data, subtype = extract_1099_data(temp_path)
        document_id = db.insert_json(
            table_name="form_1099",
            user_id=user_id,
            json_data=form1099_data,
            s3_key=s3_key,
            subtype=subtype
        )
        return {
            "document_id": document_id,
            "user_id": user_id,
            "form_subtype": subtype,
            "data": form1099_data
        }
   finally: 
        db.close()
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)

# for w2
@app.post("/v1/extract_w2")
async def upload_file_w2(
    user_id: str = Form(...), 
    file: UploadFile=File(...)
    ):
   
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)

   await file.close()
   db = Database()
   try:
        s3_key = upload_pdf(temp_path, "w2")
        w2_data = extract_w2(temp_path)
        document_id = db.insert_json(
            table_name="form_w2",
            user_id=user_id,
            json_data=w2_data,
            s3_key=s3_key
        )
        return {
            "document_id": document_id,
            "user_id": user_id,
            "data": w2_data
        }
   
   finally: 
        db.close()
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)

# for 1041
@app.post("/v1/extract_1041")
async def upload_file_1041(
    user_id: str = Form(...), 
    file: UploadFile=File(...)
    ):
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)
   await file.close()
   db = Database()
   try:
       s3_key = upload_pdf(temp_path, "1041")
       form1041_data = extract_1041(temp_path)
       document_id = db.insert_json(
            table_name="form_1041",
            user_id=user_id,
            json_data=form1041_data,
            s3_key=s3_key
        )
       return {
            "document_id": document_id,
            "user_id": user_id,
            "data": form1041_data
        }
   finally: 
        db.close()
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)


# for 1040
@app.post("/v1/extract_1040")
async def upload_file_1040(
    user_id: str = Form(...), 
    file: UploadFile=File(...)
    ):
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)
   await file.close()
   db = Database()
   try:
        s3_key = upload_pdf(temp_path, "1040")
        form1040_data, form_year = extract_1040_data(temp_path)
        document_id = db.insert_json(
            table_name="form_1040",
            user_id=user_id,
            json_data=form1040_data,
            s3_key=s3_key,
            form_year=form_year
        )
        return {
            "document_id": document_id,
            "user_id": user_id,
            "form_year": form_year,
            "data": form1040_data
        }

   finally: 
        db.close()
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)


@app.post("/v1/credit-report")
async def fetch_credit_report(request: Request):

    try:
        body = await request.body()
        xml_request = body.decode("utf-8")

        if not xml_request.strip():
            raise HTTPException(
                status_code=400,
                detail="XML request body is required"
            )

        xml_response = get_credit_report(xml_request)

        return {
            "status": "success",
            "data": xml_response
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Credit API request failed: {str(e)}"
        )

@app.post("/v1/extract_paystub")
async def upload_file_paystub(
    user_id: str = Form(...), 
    file: UploadFile=File(...)
    ):
   temp_dir = tempfile.gettempdir()
   temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

   with open(temp_path, "wb") as buffer:
       shutil.copyfileobj(file.file, buffer)
   await file.close()
   db = Database()
   try:
        s3_key = upload_pdf(temp_path, "paystub")
        paystub_data = extract_paystub(temp_path)
        if not paystub_data:
            raise HTTPException(
                status_code=500,
                detail="Failed to extract paystub data"
            )
        document_id = db.insert_json(
            table_name="paystub",
            user_id=user_id,
            json_data=paystub_data,
            s3_key=s3_key
        )
        return {
            "document_id": document_id,
            "user_id": user_id,
            "data": paystub_data
        }

   finally: 
        db.close()
        if os.path.exists(temp_path):
            gc.collect()
            # time.sleep(1)
            os.remove(temp_path)

# ----- retrieval APIs ----- 
# --- using user_id: returns all specified forms for given user 

# retrieval for w2 BY SPECIFIC USER
@app.get("/v1/w2/user/{user_id}")
async def get_w2_by_user(user_id: str):
    db = Database()
    try:
        records = db.get_json_by_user(
            table_name="form_w2",
            user_id=user_id
        )

        if not records:
            raise HTTPException(
                status_code=404,
                detail="No W-2 records found"
            )

        return {
            "user_id": user_id,
            "total_records": len(records),
            "records": records
        }

    finally:
        db.close()

# retrieval for 1099 BY SPECIFIC USER
@app.get("/v1/1099/user/{user_id}")
async def get_1099_by_user(
    user_id: str
):
    db = Database()

    try:
        records = db.get_json_by_user(
            table_name="form_1099",
            user_id=user_id
        )

        if not records:
            raise HTTPException(
                status_code=404,
                detail="No 1099 records found"
            )

        return {
            "user_id": user_id,
            "total_records": len(records),
            "records": records
        }

    finally:
        db.close()

# retrieval for 1040 BY SPECIFIC USER
@app.get("/v1/1040/user/{user_id}")
async def get_1040_by_user(
    user_id: str
):
    db = Database()

    try:
        records = db.get_json_by_user(
            table_name="form_1040",
            user_id=user_id
        )

        if not records:
            raise HTTPException(
                status_code=404,
                detail="No 1040 records found"
            )

        return {
            "user_id": user_id,
            "total_records": len(records),
            "records": records
        }

    finally:
        db.close()

# retrieval for 1041 BY SPECIFIC USER
@app.get("/v1/1041/user/{user_id}")
async def get_1041_by_user(user_id: str):
    db = Database()

    try:
        records = db.get_json_by_user(
            table_name="form_1041",
            user_id=user_id
        )

        if not records:
            raise HTTPException(
                status_code=404,
                detail="No 1041 records found"
            )

        return {
            "user_id": user_id,
            "total_records": len(records),
            "records": records
        }

    finally:
        db.close()

# retrieval for paystub BY SPECIFIC USER
@app.get("/v1/paystub/user/{user_id}")
async def get_paystub_by_user(user_id: str):
    db = Database()

    try:
        records = db.get_json_by_user(
            table_name="paystub",
            user_id=user_id
        )

        if not records:
            raise HTTPException(
                status_code=404,
                detail="No paystub records found"
            )

        return {
            "user_id": user_id,
            "total_records": len(records),
            "records": records
        }

    finally:
        db.close()

# --- using document_id: returns single specified form

# w2 retrieval USING SPECIFIC DOCUMENT 
@app.get("/v1/w2/document/{document_id}")
async def get_w2_by_document(document_id: str):
    db = Database()

    try:
        record = db.get_json_by_document(
            table_name="form_w2",
            document_id=document_id
        )

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="W-2 document not found"
            )

        return record

    finally:
        db.close()

# 1099 retrieval USING SPECIFIC DOCUMENT
@app.get("/v1/1099/document/{document_id}")
async def get_1099_by_document(document_id: str):
    db = Database()

    try:
        record = db.get_json_by_document(
            table_name="form_1099",
            document_id=document_id
        )

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="1099 document not found"
            )

        return record

    finally:
        db.close()

# 1040 retrieval USING SPECIFIC DOCUMENT
@app.get("/v1/1040/document/{document_id}")
async def get_1040_by_document(document_id: str):
    db = Database()

    try:
        record = db.get_json_by_document(
            table_name="form_1040",
            document_id=document_id
        )

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="1040 document not found"
            )

        return record

    finally:
        db.close()

# 1041 retrieval USING SPECIFIC DOCUMENT
@app.get("/v1/1041/document/{document_id}")
async def get_1041_by_document(document_id: str):
    db = Database()

    try:
        record = db.get_json_by_document(
            table_name="form_1041",
            document_id=document_id
        )

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="1041 document not found"
            )

        return record

    finally:
        db.close()

# paystub retrieval USING SPECIFIC DOCUMENT
@app.get("/v1/paystub/document/{document_id}")
async def get_paystub_by_document(document_id: str):
    db = Database()

    try:
        record = db.get_json_by_document(
            table_name="paystub",
            document_id=document_id
        )

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Paystub document not found"
            )

        return record

    finally:
        db.close()

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
