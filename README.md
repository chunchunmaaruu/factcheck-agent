# 🔍 Fact-Check Agent

> **A Truth Layer for marketing PDFs.** Upload a document → the agent extracts factual claims → verifies them against the live web → flags inaccuracies with corrections.

Built for the CogCulture Product Management Trainee assessment (Part 2).

**🌐 Live App:** [your-streamlit-url-here.streamlit.app](https://your-streamlit-url-here.streamlit.app)

---

## ✨ What It Does

Marketing decks routinely ship with outdated stats, hallucinated figures, and dates that no longer hold. This agent automates fact-checking in three stages:

| Stage | What happens | Powered by |
|------|--------------|------------|
| **1. Extract** | Pulls verifiable claims (stats, dates, financial/technical figures) from any uploaded PDF | Google Gemini 1.5 Flash |
| **2. Verify** | Searches the live web for each claim and pulls top-ranked evidence | Tavily Search API |
| **3. Report** | Assigns one of four verdicts — *Verified, Inaccurate, False, Unverifiable* — with a correction and a source citation | Google Gemini 1.5 Flash |

Each claim is rendered as a color-coded card with the corrected fact and source URL, plus a document-level **Trust Score**.

---

## 🧠 Why This Architecture

| Decision | Reasoning |
|----------|-----------|
| **Gemini 1.5 Flash for the LLM** | Generous free tier (1,500 req/day), fast, strong at structured-JSON output. Lets the recruiter stress-test without API-cost worry. |
| **Tavily for search** | Returns clean ranked snippets purpose-built for AI agents, not raw HTML. Includes a synthesized answer that anchors the verdict. |
| **PyMuPDF for PDF parsing** | Faster and more reliable than PyPDF2 on multi-column marketing decks. |
| **Streamlit for the UI** | Native Python, deploys for free, no separate frontend codebase to maintain. |
| **Two-pass LLM design** | Pass 1 isolates the extraction task (no contamination from search results). Pass 2 is constrained to a fixed schema (verdict + correction + source) for predictable output. |

---

## 🚀 Run It Locally

```bash
# 1. Clone
git clone https://github.com/<your-username>/factcheck-agent.git
cd factcheck-agent

# 2. Install
pip install -r requirements.txt

# 3. Add your API keys
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Open .streamlit/secrets.toml and paste your real keys

# 4. Run
streamlit run app.py
```

App opens at `http://localhost:8501`.

### Get the keys (both free)

- **Gemini API key** → [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (free, no card)
- **Tavily API key** → [tavily.com](https://tavily.com) (1,000 searches/month free)

---

## ☁️ Deploy to Streamlit Community Cloud (Free)

1. Push this repo to GitHub (public).
2. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub.
3. **New app** → pick this repo → main branch → `app.py`.
4. Under **Advanced settings → Secrets**, paste:
   ```toml
   GEMINI_API_KEY = "your-key"
   TAVILY_API_KEY = "your-key"
   ```
5. Deploy. You get a public `*.streamlit.app` URL in ~2 minutes.

---

## 📁 Project Structure

```
factcheck-agent/
├── app.py                              # Streamlit app — extraction, verification, UI
├── requirements.txt                    # Pinned Python deps
├── README.md                           # This file
├── .gitignore                          # Keeps secrets and junk out of git
└── .streamlit/
    ├── config.toml                     # Theme + upload limits
    └── secrets.toml.example            # Template (real secrets.toml is gitignored)
```

---

## 🧪 How It Handles the "Trap Document" Test

The assessment notes that submissions will be tested against a document **containing intentional lies and outdated stats.** Design choices that protect against that:

1. **Strict JSON-only LLM prompts** — the model can't ramble or invent verdicts; output is parsed as structured data.
2. **Live web search per claim** — verdicts are anchored to evidence retrieved at query time, never relying on the LLM's stale training data.
3. **Four-verdict scale (not binary)** — distinguishes *outdated/wrong* (`INACCURATE`) from *fabricated* (`FALSE`) from *can't tell* (`UNVERIFIABLE`), which avoids false confidence.
4. **Returns the corrected fact** — the report doesn't just flag what's wrong; it provides the real number with a source URL.
5. **Results sorted by severity** — `FALSE` → `INACCURATE` → `UNVERIFIABLE` → `VERIFIED`, so problems surface first.

---

## ⚠️ Known Limitations & Honest Trade-offs

- **Scanned PDFs (image-only) won't work** — no OCR layer in this build. PyMuPDF would need a Tesseract integration. (Roadmap item.)
- **15-claim cap per document** — keeps free-tier API usage predictable for the demo. Easy to lift in production.
- **Verdicts depend on what Tavily surfaces** — if the web has stale data on a topic, the verdict reflects that. The `UNVERIFIABLE` bucket exists for exactly this reason.
- **Free-tier rate limits** — Gemini caps at 15 req/min. The app pauses 0.5s between claims as a buffer, but very large documents may need a paid tier.

---

## 📦 Tech Stack

- **Frontend / runtime** — Streamlit
- **PDF parsing** — PyMuPDF (`fitz`)
- **LLM** — Google Gemini 1.5 Flash via `google-generativeai`
- **Web search** — Tavily Search API
- **Hosting** — Streamlit Community Cloud

---

## 👤 Author

Built as a submission for the CogCulture PM Trainee assessment.

[GitHub](https://github.com/your-username) · [LinkedIn](https://linkedin.com/in/your-handle)
