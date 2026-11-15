import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const ACTIONS = [
  { value: "approved", label: "Approve claim", tone: "success" },
  { value: "documents_requested", label: "Request documents", tone: "neutral" },
  { value: "rejected", label: "Reject claim", tone: "danger" }
];

const formatMoney = (value) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2
  }).format(Number(value || 0));

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem("claimpilot_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new Error(
      "Backend is unavailable. Start FastAPI on http://127.0.0.1:8000."
    );
  }
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : {};
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

async function openProtectedDocument(path) {
  const popup = window.open("about:blank", "_blank");
  if (!popup) throw new Error("Allow pop-ups to open claim documents.");
  const token = localStorage.getItem("claimpilot_token");
  const response = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {}
  });
  if (!response.ok) {
    popup.close();
    throw new Error(`Unable to open document (${response.status})`);
  }
  const url = URL.createObjectURL(await response.blob());
  popup.location = url;
}

function App() {
  const [session, setSession] = useState(null);
  const [signup, setSignup] = useState(false);
  const [restoringSession, setRestoringSession] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("claimpilot_token");
    if (!token) {
      setRestoringSession(false);
      return;
    }
    api("/api/me")
      .then((user) => {
        setSession({
          role: user.role,
          userId: user.user_id,
          mustChangePassword: false
        });
      })
      .catch(() => {
        localStorage.removeItem("claimpilot_token");
      })
      .finally(() => setRestoringSession(false));
  }, []);

  if (restoringSession) return <LoadingState />;

  if (!session) {
    return signup ? (
      <SignupPage onBack={() => setSignup(false)} onLogin={setSession} />
    ) : (
      <LoginPage onLogin={setSession} onCreateAccount={() => setSignup(true)} />
    );
  }
  if (session.mustChangePassword) {
    return (
      <PasswordSetup
        role={session.role}
        onComplete={() => setSession({ ...session, mustChangePassword: false })}
        onLogout={() => {
          localStorage.removeItem("claimpilot_token");
          setSession(null);
        }}
      />
    );
  }
  return session.role === "employee" ? (
    <EmployeeDashboard onLogout={() => { localStorage.removeItem("claimpilot_token"); setSession(null); }} />
  ) : (
    <UserPortal userId={session.userId} onLogout={() => { localStorage.removeItem("claimpilot_token"); setSession(null); }} />
  );
}

function LoginPage({ onLogin, onCreateAccount }) {
  const [role, setRole] = useState("employee");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    if (!identifier.trim() || !password) {
      setError("Enter your ID and password to continue.");
      return;
    }
    try {
      const session = await api("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier, password })
      });
      localStorage.setItem("claimpilot_token", session.access_token);
      onLogin({
        role: session.role,
        userId: session.user_id,
        mustChangePassword: session.must_change_password
      });
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <div className="login-page">
      <div className="login-decoration"><div className="deco-orb orb-one" /><div className="deco-orb orb-two" /></div>
      <main className="login-card">
        <div className="brand login-brand"><div className="brand-mark">CP</div><div><strong>ClaimPilot</strong><span>Insurance claims platform</span></div></div>
        <div className="login-copy"><span className="eyebrow blue-eyebrow">WELCOME BACK</span><h1>Sign in to continue</h1><p>Choose how you want to use ClaimPilot today.</p></div>
        <form onSubmit={submit}>
          <div className="role-options">
            <button type="button" className={`role-option ${role === "employee" ? "selected" : ""}`} onClick={() => { setRole("employee"); setError(""); }}>
              <span className="role-icon">♙</span><span><strong>Employee</strong><small>Review and manage claims</small></span><i>✓</i>
            </button>
            <button type="button" className={`role-option ${role === "user" ? "selected" : ""}`} onClick={() => { setRole("user"); setError(""); }}>
              <span className="role-icon">♡</span><span><strong>Member</strong><small>View your claim and policy</small></span><i>✓</i>
            </button>
          </div>
          {role === "employee" ? (
            <label className="field-label login-field">Employee ID<input value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder="e.g. employee-001" autoFocus /></label>
          ) : (
            <label className="field-label login-field">Member ID or user ID<input value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder="e.g. user_001 or MRN-1039485" /></label>
          )}
          <label className="field-label login-field">Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" /></label>
          {error && <div className="login-error">{error}</div>}
          <button className="login-button">{role === "employee" ? "Open employee dashboard" : "Open member portal"} <span>→</span></button>
        </form>
        <button type="button" className="link-button" onClick={onCreateAccount}>New member? Create an account</button>
        <p className="login-note">Protected workspace · Your information is handled securely</p>
      </main>
    </div>
  );
}

function SignupPage({ onBack, onLogin }) {
  const [options, setOptions] = useState([]);
  const [form, setForm] = useState({
    patient_name: "",
    member_id: "",
    hospital: "",
    policy_template: "",
    claimed_amount: "",
    password: ""
  });
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api("/api/auth/signup-options")
      .then((data) => {
        setOptions(data);
        setForm((current) => ({ ...current, policy_template: current.policy_template || data[0]?.template || "" }));
      })
      .catch((requestError) => setError(requestError.message));
  }, []);

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    if (form.password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const session = await api("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form)
      });
      localStorage.setItem("claimpilot_token", session.access_token);
      onLogin({ role: session.role, userId: session.user_id, mustChangePassword: false });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="login-page">
      <main className="login-card">
        <div className="brand login-brand"><div className="brand-mark">CP</div><div><strong>ClaimPilot</strong><span>New member registration</span></div></div>
        <div className="login-copy"><span className="eyebrow blue-eyebrow">GET STARTED</span><h1>Create your member account</h1><p>After registration, upload your bill and discharge summary from the member portal.</p></div>
        <form onSubmit={submit}>
          <label className="field-label login-field">Full name<input value={form.patient_name} onChange={(event) => update("patient_name", event.target.value)} required /></label>
          <label className="field-label login-field">Member ID<input value={form.member_id} onChange={(event) => update("member_id", event.target.value)} placeholder="e.g. MRN-7001001" required /></label>
          <label className="field-label login-field">Hospital<input value={form.hospital} onChange={(event) => update("hospital", event.target.value)} required /></label>
          <label className="field-label login-field">Policy<select value={form.policy_template} onChange={(event) => update("policy_template", event.target.value)} required>{options.map((option) => <option value={option.template} key={option.template}>{option.label}</option>)}</select></label>
          <label className="field-label login-field">Claimed amount<input type="number" min="0.01" step="0.01" value={form.claimed_amount} onChange={(event) => update("claimed_amount", event.target.value)} placeholder="Amount on your bill" required /></label>
          <label className="field-label login-field">Password<input type="password" minLength="12" value={form.password} onChange={(event) => update("password", event.target.value)} placeholder="At least 12 characters" required /></label>
          <label className="field-label login-field">Confirm password<input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required /></label>
          {error && <div className="login-error">{error}</div>}
          <button className="login-button" disabled={saving}>{saving ? "Creating account..." : "Create account"} <span>→</span></button>
        </form>
        <button type="button" className="link-button" onClick={onBack}>Back to sign in</button>
      </main>
    </div>
  );
}

function PasswordSetup({ role, onComplete, onLogout }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (newPassword !== confirmation) {
      setError("New passwords do not match.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword
        })
      });
      onComplete();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="login-page">
      <main className="login-card">
        <div className="brand login-brand"><div className="brand-mark">CP</div><div><strong>ClaimPilot</strong><span>Secure account setup</span></div></div>
        <div className="login-copy"><span className="eyebrow blue-eyebrow">FIRST LOGIN</span><h1>Create your password</h1><p>Your temporary {role} password must be replaced before continuing.</p></div>
        <form onSubmit={submit}>
          <label className="field-label login-field">Current password<input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoFocus /></label>
          <label className="field-label login-field">New password<input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="At least 12 characters" /></label>
          <label className="field-label login-field">Confirm new password<input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
          {error && <div className="login-error">{error}</div>}
          <button className="login-button" disabled={saving}>{saving ? "Saving..." : "Set password"} <span>→</span></button>
        </form>
        <button className="secondary-button full-width" onClick={onLogout}>Sign out</button>
      </main>
    </div>
  );
}

function EmployeeDashboard({ onLogout }) {
  const [claims, setClaims] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [details, setDetails] = useState(null);
  const [loadingClaims, setLoadingClaims] = useState(true);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  const visibleClaims = useMemo(
    () =>
      claims.filter((claim) =>
        `${claim.claim_id} ${claim.patient_name} ${claim.hospital}`
          .toLowerCase()
          .includes(query.toLowerCase())
      ),
    [claims, query]
  );

  async function loadClaims() {
    setLoadingClaims(true);
    setError("");
    try {
      const data = await api("/api/claims");
      setClaims(data);
      setSelectedId((current) => current || data[0]?.claim_id || "");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoadingClaims(false);
    }
  }

  async function loadClaim(claimId) {
    if (!claimId) return;
    setSelectedId(claimId);
    setLoadingDetails(true);
    setError("");
    try {
      const [decision, risk, audit] = await Promise.all([
        api(`/api/claims/${encodeURIComponent(claimId)}/decision`),
        api(`/api/claims/${encodeURIComponent(claimId)}/risk`),
        api(`/api/claims/${encodeURIComponent(claimId)}/review-actions`)
      ]);
      const documents = await api(`/api/claims/${encodeURIComponent(claimId)}/documents`);
      setDetails({ decision, risk, audit, documents });
    } catch (requestError) {
      setError(requestError.message);
      setDetails(null);
    } finally {
      setLoadingDetails(false);
    }
  }

  useEffect(() => {
    loadClaims();
  }, []);

  useEffect(() => {
    if (selectedId) loadClaim(selectedId);
  }, [selectedId]);

  return (
    <div className="app-shell">
      <Sidebar
        claims={visibleClaims}
        selectedId={selectedId}
        query={query}
        setQuery={setQuery}
        onSelect={setSelectedId}
        loading={loadingClaims}
      />
      <main className="main-content">
        <Topbar onRefresh={() => loadClaim(selectedId)} onLogout={onLogout} />
        {error && <div className="alert alert-error">{error}</div>}
        {loadingDetails ? (
          <LoadingState />
        ) : details ? (
          <ClaimWorkspace details={details} onAction={() => loadClaim(selectedId)} />
        ) : (
          <EmptyState />
        )}
      </main>
    </div>
  );
}

function Sidebar({ claims, selectedId, query, setQuery, onSelect, loading }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">CP</div>
        <div>
          <strong>ClaimPilot</strong>
          <span>Operations console</span>
        </div>
      </div>
      <nav className="nav">
        <a className="nav-item active" href="#claims"><span>▦</span> Claims queue</a>
        <a className="nav-item" href="#policies"><span>◇</span> Policy library</a>
        <a className="nav-item" href="#reports"><span>▥</span> Reports</a>
      </nav>
      <div className="queue-heading">
        <div>
          <span className="eyebrow">WORK QUEUE</span>
          <h2>Claims</h2>
        </div>
        <span className="count-badge">{claims.length}</span>
      </div>
      <label className="search-box">
        <span>⌕</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search claims"
        />
      </label>
      <div className="claim-list">
        {loading ? (
          <p className="muted">Loading queue...</p>
        ) : claims.length ? (
          claims.map((claim) => (
            <button
              className={`claim-row ${selectedId === claim.claim_id ? "selected" : ""}`}
              key={claim.claim_id}
              onClick={() => onSelect(claim.claim_id)}
            >
              <span className="claim-avatar">{claim.patient_name?.charAt(0) || "C"}</span>
              <span className="claim-row-copy">
                <strong>{claim.claim_id}</strong>
                <span>{claim.patient_name}</span>
                <small>{claim.hospital}</small>
              </span>
              <span className="chevron">›</span>
            </button>
          ))
        ) : (
          <p className="muted">No claims match your search.</p>
        )}
      </div>
      <div className="sidebar-footer">
        <div className="user-avatar">M</div>
        <div><strong>Claims officer</strong><span>Employee workspace</span></div>
      </div>
    </aside>
  );
}

function Topbar({ onRefresh, onLogout }) {
  return (
    <header className="topbar">
      <div>
        <span className="eyebrow">CLAIMS OPERATIONS</span>
        <h1>Review workspace</h1>
      </div>
      <div className="topbar-actions">
        <button className="icon-button" title="Refresh queue" onClick={onRefresh}>↻</button>
        <button className="secondary-button" onClick={onLogout}>Sign out</button>
        <div className="notification">●<span /></div>
        <div className="topbar-user"><div className="user-avatar">M</div><span>Manasa</span><b>⌄</b></div>
      </div>
    </header>
  );
}

function UserPortal({ userId, onLogout }) {
  const [user, setUser] = useState(null);
  const [claim, setClaim] = useState(null);
  const [review, setReview] = useState(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const [uploadType, setUploadType] = useState("hospital_bill");
  const [uploadFile, setUploadFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/me")
      .then(setUser)
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!user) return;
    setReview(null);
    if (user.claim_id) {
      api(`/api/users/${encodeURIComponent(user.user_id)}/claim`)
        .then(setClaim)
        .catch((requestError) => setError(requestError.message));
      return;
    }
    api(`/api/users/${encodeURIComponent(user.user_id)}/review`)
      .then(setReview)
      .catch((requestError) => setError(requestError.message));
  }, [user]);

  async function askQuestion(event) {
    event.preventDefault();
    if (!question.trim() || !user) return;
    setAsking(true);
    setError("");
    try {
      const data = await api("/api/policies/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          policy_file: user.policy_file,
          question,
          limit: 3
        })
      });
      setAnswer(data);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setAsking(false);
    }

  }

  async function uploadDocument(event) {
    event.preventDefault();
    if (!uploadFile || !user) return;
    setUploading(true);
    setError("");
    setUploadMessage("");
    try {
      const formData = new FormData();
      formData.append("document_type", uploadType);
      formData.append("document", uploadFile);
      await api(`/api/users/${encodeURIComponent(user.user_id)}/documents`, {
        method: "POST",
        body: formData
      });
      setUploadFile(null);
      event.target.reset();
      if (user.claim_id) {
        setClaim(await api(`/api/users/${encodeURIComponent(user.user_id)}/claim`));
      }
      setReview(await api(`/api/users/${encodeURIComponent(user.user_id)}/review`));
      setUploadMessage(`${uploadFile.name} uploaded successfully. Document verification has been refreshed.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setUploading(false);
    }
  }

  if (loading) return <div className="user-app"><LoadingState /></div>;

  return (
    <div className="user-app">
      <header className="user-header">
        <div className="brand light-brand">
          <div className="brand-mark">CP</div>
          <div><strong>ClaimPilot</strong><span>Member portal</span></div>
        </div>
        <div className="user-header-actions">
          <span className="secure-label">▣ Secure member access</span>
          <button className="secondary-button" onClick={onLogout}>Sign out</button>
        </div>
      </header>
      <main className="user-main">
        <section className="user-welcome">
          <div>
            <span className="eyebrow blue-eyebrow">MEMBER PORTAL</span>
            <h1>Good afternoon, {user?.patient_name?.split(" ")[0] || "member"}</h1>
            <p>Track your claim review and get clear answers from your policy documents.</p>
          </div>
          <div className="member-identity"><span>Signed in as</span><strong>{user?.patient_name || "Member"}</strong><small>{user?.member_id}</small></div>
        </section>
        {error && <div className="alert alert-error">{error}</div>}
        <section className="user-metric-grid">
          <Metric label="Claim status" value={claim?.status?.replaceAll("_", " ") || "Under review"} />
          {claim && <Metric label="Estimated payable" value={formatMoney(claim.payable_amount)} accent />}
          <Metric label="Member ID" value={user?.member_id || "—"} />
          <Metric label="Insurer" value={user?.insurer || "—"} />
        </section>
        <div className="user-grid">
          <div className="workspace-main">
            <Panel title="Your coverage" subtitle="Assigned policy information">
              <div className="coverage-card">
                <div className="policy-icon">◇</div>
                <div><strong>{user?.policy_name}</strong><p>{user?.insurer}</p><small>Policy wording document · PDF</small></div>
              </div>
              <div className="coverage-details">
                <span>Hospital on file<strong>{user?.hospital}</strong></span>
                <span>Verification status<strong className="text-success">{review ? "Documents received" : "Loading documents..."}</strong></span>
              </div>
            </Panel>
            <Panel title="Document verification" subtitle="Latest automated checks">
              {review ? (
                <>
                  <div className="verification-summary"><strong>{review.ocr_validation.passed}/{review.ocr_validation.total}</strong><span>important fields matched across your submitted documents</span></div>
                  <div className="verification-bar"><span style={{ width: `${(review.ocr_validation.passed / review.ocr_validation.total) * 100}%` }} /></div>
                  {review.issues.length ? review.issues.map((issue) => <div className="user-issue" key={issue}>! {issue}</div>) : <p className="text-success">✓ No document identity issues were detected.</p>}
                </>
              ) : <p className="muted">Checking your documents...</p>}
              <form className="upload-form" onSubmit={uploadDocument}>
                <strong>Submit a replacement document</strong>
                <p className="muted">Existing local files are used by default. Your upload replaces that document for the next review.</p>
                <div className="upload-row">
                  <select value={uploadType} onChange={(event) => setUploadType(event.target.value)}>
                    <option value="hospital_bill">Hospital bill</option>
                    <option value="discharge_summary">Discharge summary</option>
                  </select>
                  <input type="file" accept=".pdf,.txt,.png,.jpg,.jpeg" onChange={(event) => setUploadFile(event.target.files?.[0] || null)} />
                </div>
                {uploadMessage && <div className="form-message">{uploadMessage}</div>}
                <button className="secondary-button" disabled={uploading || !uploadFile}>{uploading ? "Uploading..." : "Upload document"}</button>
              </form>
            </Panel>
            {claim && (
              <Panel title="Estimated claim outcome" subtitle="Calculated from the selected policy; employee review is still required">
                <div className="breakdown">
                  <BreakdownRow label="Claimed amount" value={formatMoney(claim.claimed_amount)} />
                  <BreakdownRow label="Eligible before co-pay" value={formatMoney(claim.eligible_amount_before_copay)} />
                  <BreakdownRow label="Estimated payable amount" value={formatMoney(claim.payable_amount)} total />
                </div>
                <div className="reason-box">
                  <strong>Why this estimate?</strong>
                  <ul>{claim.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                </div>
              </Panel>
            )}
          </div>
          <div className="workspace-side">
            <Panel title="Ask your policy" subtitle="Answers use your assigned policy">
              <form onSubmit={askQuestion}>
                <label className="field-label">Your question<textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Example: What is my waiting period?" rows="4" /></label>
                <button className="ask-button" disabled={asking || !question.trim()}>{asking ? "Finding an answer..." : "Ask policy assistant →"}</button>
              </form>
              {answer && <div className="answer-card"><span className="answer-label">POLICY ANSWER</span><p>{answer.answer}</p><div className="citation-list">{answer.citations.map((citation) => <span key={`${citation.page_number}-${citation.section}`}>Page {citation.page_number} · {citation.section}</span>)}</div></div>}
            </Panel>
            <Panel title="Need help?" subtitle="We are here to support you">
              <p className="help-copy">For questions about an existing claim, keep your claim number and member ID ready when contacting support.</p>
              <button className="secondary-button full-width">Contact support</button>
            </Panel>
          </div>
        </div>
      </main>
    </div>
  );
}

function ClaimWorkspace({ details, onAction }) {
  const { decision, risk, audit, documents } = details;
  const [note, setNote] = useState("");
  const [reviewerId, setReviewerId] = useState("claims-officer");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");

  async function submitAction(action) {
    setSubmitting(true);
    setMessage("");
    try {
      await api(`/api/claims/${encodeURIComponent(decision.claim_id)}/review-actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reviewer_id: reviewerId, note })
      });
      setNote("");
      setMessage("Review action recorded.");
      onAction();
    } catch (requestError) {
      setMessage(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <section className="page-heading">
        <div>
          <div className="breadcrumb">Claims <span>/</span> {decision.claim_id}</div>
          <h2>{decision.claim_id} <span className="status-pill">{decision.decision.replace("_", " ")}</span></h2>
          <p>{decision.patient_name} · {decision.hospital}</p>
        </div>
        <button className="secondary-button" onClick={() => window.print()}>⇩ Export review</button>
      </section>
      <section className="metric-grid">
        <Metric label="Claimed amount" value={formatMoney(decision.claimed_amount)} />
        <Metric label="Eligible before co-pay" value={formatMoney(decision.eligible_amount_before_copay)} />
        <Metric label="Payable amount" value={formatMoney(decision.payable_amount)} accent />
        <Metric label="Risk level" value={risk.risk_level} risk={risk.risk_level} />
      </section>
      <div className="workspace-grid">
        <div className="workspace-main">
          <Panel title="Decision breakdown" subtitle="Deterministic policy calculation">
            <div className="breakdown">
              <BreakdownRow label="Claimed amount" value={formatMoney(decision.claimed_amount)} />
              <BreakdownRow label="Eligible before co-payment" value={formatMoney(decision.eligible_amount_before_copay)} />
              <BreakdownRow label="Co-payment" value={`− ${formatMoney(decision.copayment_amount)}`} negative />
              <BreakdownRow label="Deductible" value={`− ${formatMoney(decision.deductible_amount)}`} negative />
              <BreakdownRow label="Final payable amount" value={formatMoney(decision.payable_amount)} total />
            </div>
            <div className="reason-box">
              <strong>Policy reasoning</strong>
              <ul>{decision.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
            </div>
          </Panel>
          <Panel title="Risk screening" subtitle={`${risk.score}/100 screening score`}>
            {risk.findings.length ? risk.findings.map((finding) => (
              <div className={`finding ${finding.severity}`} key={finding.code}>
                <span className="finding-icon">!</span>
                <div><strong>{finding.code.replaceAll("_", " ")}</strong><p>{finding.message}</p></div>
                <span className="severity">{finding.severity}</span>
              </div>
            )) : <div className="success-empty">✓ No anomalies detected in configured checks.</div>}
          </Panel>
          <Panel title="Claim evidence" subtitle="Open the source documents used for review">
            <div className="document-list">
              {documents.length ? documents.map((document) => (
                <button
                  className="document-row"
                  key={document.path}
                  onClick={() => openProtectedDocument(`/api/claims/${encodeURIComponent(decision.claim_id)}/documents/${document.path.split("/").map(encodeURIComponent).join("/")}`).catch((error) => setMessage(error.message))}
                >
                  <span className="document-icon">▤</span>
                  <span><strong>{document.filename}</strong><small>{document.content_type.toUpperCase()} · {Math.ceil(document.size_bytes / 1024)} KB</small></span>
                  <span className="document-open">Open ↗</span>
                </button>
              )) : <p className="muted">No source documents registered.</p>}
            </div>
          </Panel>
        </div>
        <div className="workspace-side">
          <Panel title="Human review" subtitle="Record the final employee action">
            <label className="field-label">Reviewer ID<input value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} /></label>
            <label className="field-label">Review note<textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add context for this action..." rows="4" /></label>
            {message && <div className="form-message">{message}</div>}
            <div className="action-stack">
              {ACTIONS.map((action) => (
                <button
                  className={`action-button ${action.tone}`}
                  disabled={submitting || (action.value !== "approved" && !note.trim())}
                  key={action.value}
                  onClick={() => submitAction(action.value)}
                >{action.label}</button>
              ))}
            </div>
          </Panel>
          <Panel title="Audit history" subtitle={`${audit.actions.length} recorded action(s)`}>
            {audit.actions.length ? audit.actions.map((item) => (
              <div className="audit-row" key={`${item.created_at}-${item.action}`}>
                <span className="audit-dot" />
                <div><strong>{item.action.replaceAll("_", " ")}</strong><p>{item.reviewer_id} · {new Date(item.created_at).toLocaleString()}</p>{item.note && <small>{item.note}</small>}</div>
              </div>
            )) : <p className="muted">No review activity yet.</p>}
          </Panel>
        </div>
      </div>
    </>
  );
}

function Panel({ title, subtitle, children }) {
  return <section className="panel"><div className="panel-heading"><div><h3>{title}</h3><span>{subtitle}</span></div></div>{children}</section>;
}

function Metric({ label, value, accent, risk }) {
  return <div className={`metric-card ${accent ? "accent" : ""}`}><span>{label}</span><strong className={risk ? `risk-${risk}` : ""}>{value}</strong>{accent && <small>Based on policy rules</small>}</div>;
}

function BreakdownRow({ label, value, negative, total }) {
  return <div className={`breakdown-row ${total ? "total" : ""}`}><span>{label}</span><strong className={negative ? "negative" : ""}>{value}</strong></div>;
}

function LoadingState() { return <div className="loading-card"><div className="spinner" /><p>Loading claim review...</p></div>; }
function EmptyState() { return <div className="empty-state"><div>◈</div><h2>Select a claim</h2><p>Choose a claim from the queue to view its review workspace.</p></div>; }

createRoot(document.getElementById("root")).render(<App />);
