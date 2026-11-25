# ClaimPilot — AI-Powered Insurance Claim Intelligence Platform

ClaimPilot automates insurance claim verification. It reads hospital bills and
discharge summaries with OCR, loads the assigned policy PDF, validates key
identity fields, and gives a claims officer a review-ready result.

## ✅ Current capabilities (Phase 1 + Phase 2 MVP)

- **Landing page** at `/` — public marketing site
- **Member portal** at `/app` — claim submission, document upload, OCR verification, policy Q&A
- **Employee dashboard** at `/app` — claim queue with search & status filters, decision breakdown,
  risk findings, claim timeline, review actions, audit history
- **Analytics overview** — approval rate, processing time, monthly volume, top hospitals
- **Policy Q&A** — grounded answers from policy PDFs with Gemini/OpenAI + TF-IDF retrieval
- **OCR verification** — Tesseract extracts and cross-checks identity fields across documents
- **Deterministic financials** — eligible amount, co-payment, deductible, payable
- **Risk screening** — explainable anomaly findings per claim
- **JWT auth** with PBKDF2 passwords, role-based access, immutable audit trail
- **Email notification stubs** — ready for SMTP/SendGrid wiring
- **SQLite + local storage** MVP; PostgreSQL/S3 migration-ready

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
- Persist curated member profiles and policy assignments in SQLite
- Persist claim metadata, document hashes, calculated decisions, and claim status history in SQLite
- Let members upload replacement bills or discharge summaries while retaining curated local defaults
- Let new members select a policy, create an account, submit a claim amount, and track an estimated payable amount
- Authenticate employees and members with JWT access tokens and PBKDF2 password hashes
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

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.web:app --reload
```

Open `http://127.0.0.1:8000` after building the React frontend, or run the
frontend development server at `http://127.0.0.1:5173`.

Build and run the React frontend:

```powershell
# Terminal 1: start the FastAPI backend from the repository root
.\.venv\Scripts\python.exe -m uvicorn app.web:app --reload

# Terminal 2: start the React development server
cd .\frontend
npm install
npm run dev
```

For a production-style build, run `npm run build`; FastAPI serves the generated
`frontend/dist` dashboard automatically.

To enable LLM-backed policy answers, configure an OpenAI-compatible provider before
starting the server:

```powershell
$env:LLM_API_KEY = "your-provider-key"
$env:LLM_API_URL = "https://api.openai.com/v1/chat/completions"
$env:LLM_MODEL = "gpt-4o-mini"
```

Google Gemini can be used directly with a Google AI Studio key:

```powershell
Copy-Item .env.example .env
# Edit .env locally and replace the placeholder with your key.
# The current supported default model is gemini-3.8-flash.
```

When `GEMINI_API_KEY` is present, it takes priority over `LLM_API_KEY` and the
native Gemini `generateContent` API is used.

Authentication requires a local JWT secret:

```powershell
$env:APP_JWT_SECRET = "replace-with-a-long-random-secret"
```

For the local synthetic seed, use `employee-001` / `employee123` for the
employee dashboard, or `user_001` / `member123` for the member portal on first
login. The application forces each seeded account to create a new password of
at least 12 characters. Configure a strong secret before deployment.

`LLM_API_URL` can point to a compatible local server such as Ollama. The
`POST /api/policies/ask` endpoint returns an explicit error when the provider is
not configured or unavailable; it never substitutes an ungrounded answer.

The React app has two views:

- **Employee dashboard**: claim queue, deterministic decision breakdown, risk
  findings, review actions, and audit history.
- **Member portal**: member profile, assigned policy, OCR document verification,
  claim review status, and policy questions answered from the member's assigned
  policy with page citations.

The application starts with a role-selection screen. Employees and members
enter their identifier and password; the backend returns a JWT and enforces
role-specific access to the dashboard APIs.

The SQLite database is initialized at `data/insurance.sqlite3` from the curated
mapping and claim folders on first use. It currently contains **5 users** and
**3 synthetic claims**, with document metadata and SHA-256 hashes. Document
binaries remain in the local claim storage folders; decisions and claim status
history are persisted in SQLite. The seed is idempotent, so updated curated
records can be synchronized without creating duplicates.

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

Members can upload a replacement document through:

```text
POST /api/users/{user_id}/documents
```

Choose `hospital_bill` or `discharge_summary` as `document_type` and send the
file as multipart form data. If no upload exists, the curated local document is
used automatically.

New members can use the **Create an account** link on the sign-in screen. They
select a seeded policy template, enter the amount shown on their bill, and then
upload the hospital bill and discharge summary from the member portal. The
generated claim appears in the employee queue with a `documents_pending` status,
and the member sees an estimated payable amount until employee review is
complete.

## Deployment shape

The current application should not be deployed entirely to Vercel yet. Vercel
is suitable for the React frontend, but the FastAPI backend currently depends
on persistent SQLite and local document files. Vercel serverless storage is not
reliable for those runtime files, and the current OCR flow requires a
Tesseract executable.

For a practical deployment:

1. Deploy the React frontend to Vercel.
2. Deploy the FastAPI backend to Render, Railway, Fly.io, or a similar
   persistent service.
3. Move SQLite data to PostgreSQL.
4. Move uploaded documents to S3-compatible object storage or Supabase
   Storage.
5. Configure the frontend API base URL and backend CORS for the Vercel domain.
6. Configure `APP_JWT_SECRET`, database, storage, and LLM settings as platform
   secrets rather than committing them.

After those changes, the frontend can remain on Vercel while the API, database,
OCR worker, and document storage run on services designed for persistent
workloads.

## Run the complete application with Docker

The included Docker image keeps the current architecture together: FastAPI,
the built React dashboard, SQLite, local claim files, and Tesseract OCR.

```powershell
docker build -t claimpilot .
docker run --rm -p 8000:8000 `
  -e APP_JWT_SECRET="replace-with-a-long-random-secret" `
  -e GEMINI_API_KEY="your-key-if-needed" `
  -v claimpilot-data:/app/data `
  claimpilot
```

Open `http://localhost:8000`. The `/app/data` volume is required so uploaded
documents, SQLite databases, and review history survive container restarts.
For deployment, use a Docker-capable service with a persistent volume, such as
Railway, Render with a persistent disk, or Fly.io with a volume. This is the
closest way to deploy the current application without changing its storage
architecture.

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
