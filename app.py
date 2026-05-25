"""
Fact-Check Agent — A Truth Layer for Marketing PDFs
====================================================
Upload a PDF → Extract claims → Verify against live web → Flag inaccuracies.

Stack:
- Streamlit (UI)
- PyMuPDF (PDF text extraction)
- Google Gemini (LLM for claim extraction + verdict reasoning)
- Tavily (live web search)
"""

import os
import json
import time
from typing import List, Dict, Any

import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
from tavily import TavilyClient


# ---------- CONFIG ----------
st.set_page_config(
    page_title="Fact-Check Agent",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------- API KEY LOADING ----------
def get_secret(name: str) -> str:
    """Load from Streamlit secrets first, fall back to env vars (for local dev)."""
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return os.environ.get(name, "")


GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
TAVILY_API_KEY = get_secret("TAVILY_API_KEY")


# ---------- PDF EXTRACTION ----------
def extract_text_from_pdf(pdf_file) -> str:
    """Extract all text from an uploaded PDF using PyMuPDF."""
    pdf_bytes = pdf_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_chunks = []
    for page in doc:
        text_chunks.append(page.get_text())
    doc.close()
    return "\n".join(text_chunks)


# ---------- CLAIM EXTRACTION (LLM) ----------
CLAIM_EXTRACTION_PROMPT = """You are an expert fact-checker. Read the document below and extract every \
verifiable factual claim — focusing on:
- Statistics and percentages (e.g., "73% of marketers...")
- Dates and years (e.g., "founded in 2019")
- Financial figures (revenue, valuations, funding rounds, market size)
- Technical figures (user counts, growth rates, market share)
- Named-entity factual statements (e.g., "X is the CEO of Y", "Z acquired W in 2024")

For each claim, return ONLY a JSON array (no prose, no markdown fences). Each item must have:
- "claim": the exact factual statement (short, self-contained, max ~25 words)
- "category": one of "statistic", "date", "financial", "technical", "entity"
- "search_query": a concise web search query (5-10 words) to verify it

Skip opinions, predictions, marketing fluff, and unverifiable subjective statements.
Extract at most 15 of the most consequential, fact-checkable claims.

DOCUMENT:
{document}

Return ONLY valid JSON. Example format:
[
  {{"claim": "ChatGPT has 200 million weekly active users", "category": "statistic", "search_query": "ChatGPT weekly active users 2026"}}
]
"""


def extract_claims(document_text: str, model) -> List[Dict[str, str]]:
    """Use Gemini to pull verifiable claims out of the document."""
    # Truncate very long docs to stay within token limits
    truncated = document_text[:25000]
    prompt = CLAIM_EXTRACTION_PROMPT.format(document=truncated)
    response = model.generate_content(prompt)
    raw = response.text.strip()

    # Strip markdown fences if Gemini added them
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()

    try:
        claims = json.loads(raw)
        if isinstance(claims, list):
            return claims
        return []
    except json.JSONDecodeError:
        # Last-ditch: try to find a JSON array in the response
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
        return []


# ---------- WEB VERIFICATION ----------
def search_web(query: str, tavily_client: TavilyClient) -> List[Dict[str, Any]]:
    """Query Tavily and return top results with snippets."""
    try:
        result = tavily_client.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_answer=True,
        )
        return {
            "answer": result.get("answer", ""),
            "results": result.get("results", []),
        }
    except Exception as e:
        return {"answer": "", "results": [], "error": str(e)}


# ---------- VERDICT REASONING (LLM) ----------
VERDICT_PROMPT = """You are a meticulous fact-checker. Given a CLAIM and live WEB EVIDENCE, decide one verdict:

- "VERIFIED" — Evidence clearly supports the claim (numbers match within ~5%, facts align).
- "INACCURATE" — Evidence contradicts the claim with a better/updated number or detail \
(e.g., claim says 50% but real data shows 73%, claim says 2019 but actually 2021).
- "FALSE" — No credible evidence exists for the claim, OR evidence flatly refutes it.
- "UNVERIFIABLE" — Web evidence is insufficient or ambiguous to judge.

CLAIM: {claim}

WEB EVIDENCE:
Tavily synthesized answer: {tavily_answer}

Top search results:
{snippets}

Return ONLY a JSON object (no prose, no markdown fences):
{{
  "verdict": "VERIFIED" | "INACCURATE" | "FALSE" | "UNVERIFIABLE",
  "correct_fact": "The real fact in one sentence (or 'N/A' if verdict is VERIFIED)",
  "reasoning": "One short sentence explaining the verdict",
  "source": "URL of the most relevant source, or empty string"
}}"""


def verify_claim(claim_obj: Dict[str, str], tavily_client: TavilyClient, model) -> Dict[str, Any]:
    """Search the web for a claim, then ask the LLM to judge it."""
    query = claim_obj.get("search_query") or claim_obj["claim"]
    search_data = search_web(query, tavily_client)

    if search_data.get("error"):
        return {
            **claim_obj,
            "verdict": "UNVERIFIABLE",
            "correct_fact": "N/A",
            "reasoning": f"Search failed: {search_data['error']}",
            "source": "",
        }

    snippets = "\n".join(
        f"- [{r.get('title', 'Source')}]({r.get('url', '')}): {r.get('content', '')[:300]}"
        for r in search_data["results"][:5]
    )

    prompt = VERDICT_PROMPT.format(
        claim=claim_obj["claim"],
        tavily_answer=search_data["answer"] or "(none)",
        snippets=snippets or "(no results)",
    )

    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        verdict_data = json.loads(raw)
    except Exception as e:
        verdict_data = {
            "verdict": "UNVERIFIABLE",
            "correct_fact": "N/A",
            "reasoning": f"Verdict parsing failed: {str(e)[:100]}",
            "source": "",
        }

    return {**claim_obj, **verdict_data}


# ---------- UI ----------
def render_verdict_card(result: Dict[str, Any], idx: int):
    """Render one claim result as a styled card."""
    verdict = result.get("verdict", "UNVERIFIABLE")
    colors = {
        "VERIFIED": ("#16a34a", "✅", "Verified"),
        "INACCURATE": ("#ea580c", "⚠️", "Inaccurate"),
        "FALSE": ("#dc2626", "❌", "False"),
        "UNVERIFIABLE": ("#64748b", "❓", "Unverifiable"),
    }
    color, emoji, label = colors.get(verdict, colors["UNVERIFIABLE"])

    with st.container(border=True):
        col1, col2 = st.columns([1, 5])
        with col1:
            st.markdown(
                f"<div style='background:{color};color:white;padding:10px;"
                f"border-radius:8px;text-align:center;font-weight:600;'>"
                f"{emoji}<br>{label}</div>",
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(f"**Claim #{idx + 1}:** _{result['claim']}_")
            st.caption(f"Category: {result.get('category', 'n/a').title()}")

            if verdict != "VERIFIED" and result.get("correct_fact") not in ("N/A", "", None):
                st.markdown(f"**🎯 Real fact:** {result['correct_fact']}")

            st.markdown(f"**Reasoning:** {result.get('reasoning', 'n/a')}")

            source = result.get("source", "")
            if source:
                st.markdown(f"**Source:** [{source[:80]}...]({source})")


def main():
    # ---------- HEADER ----------
    st.title("🔍 Fact-Check Agent")
    st.markdown(
        "**The Truth Layer for Marketing PDFs** — Upload a document, "
        "and this tool extracts factual claims, verifies them against live web data, "
        "and flags inaccuracies in real-time."
    )

    # ---------- SIDEBAR ----------
    with st.sidebar:
        st.header("⚙️ How It Works")
        st.markdown(
            """
            1. **Upload** a marketing PDF
            2. **Extract** — Gemini pulls verifiable claims (stats, dates, figures)
            3. **Verify** — Tavily searches the live web for each claim
            4. **Report** — Each claim is flagged:
               - ✅ Verified
               - ⚠️ Inaccurate (with correction)
               - ❌ False (no evidence)
               - ❓ Unverifiable
            """
        )
        st.divider()
        st.caption("Built for the CogCulture PM Trainee Assessment.")

        # API key status
        st.divider()
        st.subheader("🔑 API Status")
        if GEMINI_API_KEY:
            st.success("Gemini API: Connected")
        else:
            st.error("Gemini API: Missing")
        if TAVILY_API_KEY:
            st.success("Tavily API: Connected")
        else:
            st.error("Tavily API: Missing")

    # ---------- KEY CHECK ----------
    if not GEMINI_API_KEY or not TAVILY_API_KEY:
        st.error(
            "❌ API keys missing. Add `GEMINI_API_KEY` and `TAVILY_API_KEY` "
            "to `.streamlit/secrets.toml` (local) or to Streamlit Cloud secrets."
        )
        st.stop()

    # ---------- INIT CLIENTS ----------
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")
    tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

    # ---------- UPLOAD ----------
    uploaded_file = st.file_uploader(
        "📄 Upload a PDF to fact-check",
        type=["pdf"],
        help="Marketing decks, reports, whitepapers — anything with factual claims.",
    )

    if uploaded_file is None:
        st.info("👆 Upload a PDF above to start. Try a marketing report or competitive analysis.")
        with st.expander("💡 What does this tool catch?"):
            st.markdown(
                """
                - **Outdated stats** — "ChatGPT has 100M users" → real number is much higher now
                - **Wrong dates** — "Profound was founded in 2020" → actually 2024
                - **Fabricated figures** — "Perplexity is valued at $50B" → real valuation differs
                - **Hallucinated facts** — entities or events with no real-world evidence
                """
            )
        return

    # ---------- PROCESS ----------
    with st.spinner("📖 Extracting text from PDF..."):
        document_text = extract_text_from_pdf(uploaded_file)

    if not document_text.strip():
        st.error("❌ Could not extract any text. Is the PDF scanned/image-only?")
        return

    st.success(f"✅ Extracted {len(document_text):,} characters from the PDF.")

    with st.expander("📄 Preview extracted text"):
        st.text_area("Document text", document_text[:3000] + ("..." if len(document_text) > 3000 else ""), height=200)

    # ---------- CLAIMS ----------
    with st.spinner("🧠 Identifying verifiable claims..."):
        claims = extract_claims(document_text, model)

    if not claims:
        st.warning("⚠️ No clearly verifiable claims were found in this document.")
        return

    st.subheader(f"📋 Found {len(claims)} verifiable claim(s)")

    # ---------- VERIFY ----------
    st.subheader("🔬 Verification in progress...")
    progress = st.progress(0.0)
    status = st.empty()

    results = []
    for i, claim in enumerate(claims):
        status.markdown(f"**Checking claim {i + 1} of {len(claims)}:** _{claim['claim'][:80]}..._")
        result = verify_claim(claim, tavily_client, model)
        results.append(result)
        progress.progress((i + 1) / len(claims))
        time.sleep(0.5)  # gentle rate-limit cushion for free-tier APIs

    status.empty()
    progress.empty()

    # ---------- SUMMARY ----------
    st.subheader("📊 Fact-Check Report")
    counts = {"VERIFIED": 0, "INACCURATE": 0, "FALSE": 0, "UNVERIFIABLE": 0}
    for r in results:
        counts[r.get("verdict", "UNVERIFIABLE")] = counts.get(r.get("verdict", "UNVERIFIABLE"), 0) + 1

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("✅ Verified", counts["VERIFIED"])
    c2.metric("⚠️ Inaccurate", counts["INACCURATE"])
    c3.metric("❌ False", counts["FALSE"])
    c4.metric("❓ Unverifiable", counts["UNVERIFIABLE"])

    # Trust score
    total = len(results)
    trust = (counts["VERIFIED"] / total * 100) if total else 0
    st.markdown(f"### 🎯 Document Trust Score: **{trust:.0f}%**")
    st.progress(trust / 100)

    st.divider()

    # ---------- DETAILED CARDS ----------
    st.subheader("📑 Claim-by-Claim Analysis")

    # Sort so problems show first
    priority = {"FALSE": 0, "INACCURATE": 1, "UNVERIFIABLE": 2, "VERIFIED": 3}
    sorted_results = sorted(results, key=lambda r: priority.get(r.get("verdict", "UNVERIFIABLE"), 4))

    for idx, result in enumerate(sorted_results):
        render_verdict_card(result, idx)

    # ---------- DOWNLOAD ----------
    st.divider()
    report_json = json.dumps(results, indent=2)
    st.download_button(
        "⬇️ Download Full Report (JSON)",
        report_json,
        file_name="factcheck_report.json",
        mime="application/json",
    )


if __name__ == "__main__":
    main()
