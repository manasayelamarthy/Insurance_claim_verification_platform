# Insurance Claim Verification Platform

This project verifies insurance claim documents. It reads hospital bills and
discharge summaries with OCR, loads the assigned policy PDF, validates key
identity fields, and gives a claims officer a review-ready result.

## Current capabilities

- Load and validate structured ground truth for five user claim bundles
- Model patients, hospitals, procedures, financials, and claim documents
- Extract text from hospital bill and discharge-summary images with Tesseract
- Read assigned policy PDFs
- Compare OCR identity fields with the reference ground truth
- Calculate eligible amount, co-payment, deductible, and payable amount
- Detect excluded treatment and network-hospital violations
- Return a human-review recommendation without making an automatic denial

## Run tests

```powershell
python -m unittest discover -s .\tests -v
```

## Run the application

Install dependencies:

```powershell
pip install -e .
```

Start the API and browser interface:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.web:app --reload
```

Open `http://127.0.0.1:8000`. Select one of the five users and click
**Review claim**.

The synthetic claim decision API is also available at:

```text
GET /api/claims
GET /api/claims/CLM-1001/decision
```

The workflow is:

```text
Select claim
→ Read claim form, bill, and policy
→ Apply exclusions, room limits, co-payment, and deductible
→ Calculate payable amount
→ Show decision reasons for human review
```

The curated external verification dataset is under `data/external/curated/`.
It contains five user bundles with hospital bills and discharge summaries, plus
five policy PDFs assigned through the user-policy mapping. See
`data/external/curated/README.md`, `data/external/curated/manifest.json`, and
`data/external/curated/user_policy_mapping.json` for its contents.

The insurance implementation is under `app/insurance/`. Tesseract OCR must be
installed separately on Windows; the expected executable location is
`C:\Program Files\Tesseract-OCR\tesseract.exe`.
