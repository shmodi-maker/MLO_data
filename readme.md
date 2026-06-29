# Project Scope

**Working for forms 1099(all four), 1041, W2.**

## Instructions for MLO Extraction Scripts

### Applicable to All Forms

-   **Input:** PDFs ONLY. A pdf will be uploaded as input.

-   **Output:** json data. Extracted data from the forms will be in json
    format. Including each field of the form in various sub sections, it
    will also have a "processing_report" (metadata, field density, hitl,
    empty fields) and "identification_fields" (form fields which can be
    used to identify the user)

APIs created for all the forms in the file 'main.py' which takes a PDF
as input.

## Tasks To Do

-   **Uploaded filetype check.** (Throw error if any other filetype is
    uploaded, for now)
-   **Alter 1040 pipeline according to requirement (Currently, image
    conversion is done separatly.** Changes: In main_1040, PDF will be
    converted to image, year will be detected, routed to extracted
    script for appropriate year).
-   **Multiple filetype compatibility.** (User will be able to upload
    pdf, jpeg, png)
-   **Add a ratelimit for calling APIs**
