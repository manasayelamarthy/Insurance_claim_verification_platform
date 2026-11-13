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
- Extract text from TXT, PDF, and image claim documents
- Accept claim document uploads with filename and size validation
- Split policy PDFs into page-aware searchable clauses
- Search policy clauses with TF-IDF cosine similarity scores
- Ask policy questions with grounded clause answers and page citations
- Generate policy answers with an OpenAI-compatible LLM using retrieved evidence only
- Screen claims for explainable anomalies and manual-review signals
- Record employee approval, rejection, and document-request actions with audit history
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

Open `http://127.0.0.1:8000`. The employee dashboard shows the claim queue,
decision calculation, policy reasons, and anomaly findings for the selected claim.

To enable LLM-backed policy answers, configure an OpenAI-compatible provider before
starting the server:

```powershell
$env:LLM_API_KEY = "your-provider-key"
$env:LLM_API_URL = "https://api.openai.com/v1/chat/completions"
$env:LLM_MODEL = "gpt-4o-mini"
```

`LLM_API_URL` can point to a compatible local server such as Ollama. The
`POST /api/policies/ask` endpoint returns an explicit error when the provider is
not configured or unavailable; it never substitutes an ungrounded answer.

The synthetic claim decision API is also available at:

```text
GET /api/claims
GET /api/claims/CLM-1001/decision
GET /api/claims/CLM-1001/risk
GET /api/claims/CLM-1001/review-actions
POST /api/claims/CLM-1001/review-actions
POST /api/claims/CLM-1001/documents
GET /api/policies/search?policy_file=policies/hdfc-ergo/energy-diabetes-hypertension__wordings.pdf&question=What%20is%20the%20room%20limit%3F
POST /api/policies/ask
```

The workflow is:

```text
Select claim
→ Upload or read claim form, bill, and policy
→ Extract text from each document
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
