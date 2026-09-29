"""Evidence-first research pipeline with 3 LLM stages + code-only search, verification, and visualization."""

import os
import re
import json
import time
from typing import List, Dict, Any, Optional, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from models import PageRecord, ClaimRecord, ClaimGroup, ResearchResult
from evidence_tools import search_and_read, verify_quote, format_citations
from visualizer import generate_all_visuals


# ── Extensibility Hooks for Future Planner / Critic Agents ──
class PipelineHook:
    """Clear extension points to re-attach Planner or Critic agents in the future."""
    def on_query_planned(self, question: str, variants: List[str]) -> None:
        pass

    def on_claims_extracted(self, claims: List[ClaimRecord]) -> None:
        pass

    def on_report_written(self, report: str, groups: List[ClaimGroup]) -> None:
        pass


def _get_llm(model_env_var: str, default_model: str, max_tokens: int = 2000) -> ChatOpenAI:
    """Instantiate an OpenRouter LLM client with specific model selection."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("Missing OPENROUTER_API_KEY. Please set it in your .env file.")

    model = os.getenv(model_env_var, default_model)
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        temperature=0.0,
        max_tokens=max_tokens,
    )


# Low-token lightweight model for extraction & clustering (Steps 2 and 3)
def get_cheap_llm() -> ChatOpenAI:
    return _get_llm("OPENROUTER_CHEAP_MODEL", "google/gemini-2.5-flash", max_tokens=600)


# Low-token efficient model for final synthesis (Step 4)
def get_strong_llm() -> ChatOpenAI:
    return _get_llm("OPENROUTER_STRONG_MODEL", "openai/gpt-4o-mini", max_tokens=1000)


def extract_claims(pages: List[PageRecord], cheap_llm: Optional[ChatOpenAI] = None) -> List[ClaimRecord]:
    """Step 2: Extract factual claims per page using a cheap model, then verify quotes in code.
    Drop any claim whose quote is not found in the raw page text."""
    if cheap_llm is None:
        cheap_llm = get_cheap_llm()

    extraction_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a concise evidence extraction engine. Read the webpage text and extract 2 to 3 specific, "
         "factual claims.\n"
         "CRITICAL RULE: Each claim must include an exact, verbatim quote copied directly from the text.\n"
         "Return ONLY a valid JSON array of objects with keys 'text' and 'quote'.\n"
         "Example:\n"
         '[{"text": "Fusion test reached 100M degrees", "quote": "the reactor achieved a core temperature of 100 million degrees Celsius"}]\n'
         "Do not output markdown code blocks or any other commentary, only the raw JSON array."),
        ("human", "Webpage Title: {title}\nURL: {url}\n\nWebpage Text:\n{text}")
    ])

    extraction_chain = extraction_prompt | cheap_llm | StrOutputParser()
    verified_claims: List[ClaimRecord] = []
    claim_counter = 1

    for page in pages:
        if len(page.trimmed_text.strip()) < 50:
            continue

        try:
            raw_response = extraction_chain.invoke({
                "title": page.source_name,
                "url": page.url,
                "text": page.trimmed_text[:2500]
            })

            # Clean JSON response
            cleaned_json = raw_response.strip()
            if cleaned_json.startswith("```json"):
                cleaned_json = cleaned_json[7:]
            if cleaned_json.startswith("```"):
                cleaned_json = cleaned_json[3:]
            if cleaned_json.endswith("```"):
                cleaned_json = cleaned_json[:-3]
            cleaned_json = cleaned_json.strip()

            parsed = json.loads(cleaned_json)
            if not isinstance(parsed, list):
                continue

            for item in parsed:
                text = str(item.get("text", "")).strip()
                quote = str(item.get("quote", "")).strip()

                if not text or not quote:
                    continue

                # Strict code verification: quote MUST exist in page raw text
                if not verify_quote(quote, page.raw_text):
                    # Quote hallucinated or not in source text -> DROP CLAIM
                    continue

                # All provenance set by code, never by the LLM
                claim = ClaimRecord(
                    id=f"c{claim_counter}",
                    text=text,
                    quote=quote,
                    source_id=page.source_id,
                    source_name=page.source_name,
                    url=page.url,
                    published=page.published,
                    credibility=page.credibility,
                    status="verified"
                )
                verified_claims.append(claim)
                claim_counter += 1

        except Exception:
            # Continue processing remaining pages on parsing errors
            continue

    return verified_claims


def analyze_claims(claims: List[ClaimRecord], cheap_llm: Optional[ChatOpenAI] = None) -> List[ClaimGroup]:
    """Step 3: One LLM call groups claims about the same fact and labels each group
    AGREE, DISPUTED, or SINGLE_SOURCE. Returns claim IDs only (no new facts)."""
    if not claims:
        return []

    if cheap_llm is None:
        cheap_llm = get_cheap_llm()

    claims_input = [
        {"id": c.id, "text": c.text, "source_id": c.source_id}
        for c in claims
    ]

    analysis_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a factual claim analyzer. Group the provided claims by the underlying fact or question "
         "they address.\n"
         "Assign each group one consensus label:\n"
         "- 'AGREE': Multiple independent sources state or corroborate this fact.\n"
         "- 'DISPUTED': Different sources contradict each other or make conflicting assertions.\n"
         "- 'SINGLE_SOURCE': Only one source reports this assertion.\n\n"
         "STRICT RULES:\n"
         "1. Return ONLY claim IDs. Do NOT create or add any new facts or text.\n"
         "2. Return ONLY a valid JSON array of objects with keys: 'topic', 'consensus', 'claim_ids'.\n"
         "Example:\n"
         '[{"topic": "Commercial fusion timeline", "consensus": "DISPUTED", "claim_ids": ["c1", "c3"]}]\n'
         "No markdown code blocks or surrounding text."),
        ("human", "Claims to cluster:\n{claims_json}")
    ])

    analysis_chain = analysis_prompt | cheap_llm | StrOutputParser()

    try:
        raw = analysis_chain.invoke({"claims_json": json.dumps(claims_input, indent=2)})
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        parsed = json.loads(cleaned)
        groups: List[ClaimGroup] = []
        valid_claim_ids = {c.id for c in claims}

        for i, item in enumerate(parsed, 1):
            consensus = str(item.get("consensus", "SINGLE_SOURCE")).upper()
            if consensus not in ("AGREE", "DISPUTED", "SINGLE_SOURCE"):
                consensus = "SINGLE_SOURCE"

            c_ids = [cid for cid in item.get("claim_ids", []) if cid in valid_claim_ids]
            if c_ids:
                groups.append(ClaimGroup(
                    group_id=f"g{i}",
                    topic=str(item.get("topic", f"Finding {i}")),
                    consensus=consensus,
                    claim_ids=c_ids
                ))
        return groups
    except Exception:
        # Fallback grouping: treat each claim as single source
        return [
            ClaimGroup(group_id=f"g{i}", topic=c.text[:50], consensus="SINGLE_SOURCE", claim_ids=[c.id])
            for i, c in enumerate(claims, 1)
        ]


def write_report(
    question: str,
    groups: List[ClaimGroup],
    claims_by_id: Dict[str, ClaimRecord],
    sources_by_id: Dict[str, PageRecord],
    strong_llm: Optional[ChatOpenAI] = None
) -> Tuple[str, str, List[str]]:
    """Step 4: Strong model drafts structured report using only the supplied claims.
    Every sentence must conclude with [source_id] markers.
    Code verifies markers against source registry and converts to clickable links."""
    if strong_llm is None:
        strong_llm = get_strong_llm()

    # Prepare evidence context for the writer
    context_blocks = []
    for g in groups:
        cluster_claims = [claims_by_id[cid] for cid in g.claim_ids if cid in claims_by_id]
        if not cluster_claims:
            continue
        claims_text = "\n".join([
            f"  - [{c.source_id}] {c.text} (Quote: \"{c.quote}\")"
            for c in cluster_claims
        ])
        context_blocks.append(f"Topic: {g.topic} [Consensus: {g.consensus}]\n{claims_text}")

    evidence_context = "\n\n".join(context_blocks)

    writer_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a rigorous scientific research synthesizer. Write a comprehensive research report "
         "based SOLELY on the supplied claims and sources below. Do not assume or invent facts.\n\n"
         "MANDATORY CITATION RULE:\n"
         "Every single statement must end with its exact source marker in brackets, like [s1] or [s2]. "
         "Never introduce any source markers that are not in the provided evidence.\n\n"
         "FORMAT YOUR REPORT IN THESE 4 EXACT SECTIONS (use markdown ## headers):\n"
         "## Summary\n"
         "(High-level synthesis answering the research question)\n\n"
         "## Well Supported\n"
         "(Facts corroborated across multiple independent sources labeled AGREE)\n\n"
         "## Disputed\n"
         "(Direct contradictions or unresolved claims labeled DISPUTED)\n\n"
         "## Weak Evidence\n"
         "(Single-source assertions or lower-confidence evidence)\n\n"
         "Be detailed, factual, and strictly objective."),
        ("human", "Research Question: {question}\n\nEvidence Base:\n{evidence}")
    ])

    writer_chain = writer_prompt | strong_llm | StrOutputParser()

    raw_report = writer_chain.invoke({
        "question": question,
        "evidence": evidence_context
    })

    # Code post-processor: reject ungrounded markers and convert valid markers to links
    formatted_report, rejected_markers = format_citations(raw_report, sources_by_id)
    return formatted_report, raw_report, rejected_markers


def run_evidence_pipeline(
    question: str,
    *,
    on_step: Optional[Callable[[str, str], None]] = None,
    hook: Optional[PipelineHook] = None
) -> Dict[str, Any]:
    """Orchestrates the 5-step evidence-first research pipeline:
    1. search_and_read (Code only)
    2. extract_claims (Cheap LLM + Code quote check)
    3. analyze_claims (Cheap LLM clustering)
    4. write_report (Strong LLM synthesis) [Parallel with 5]
    5. visualize (Code only) [Parallel with 4]
    """
    if on_step is None:
        on_step = lambda stage, status: None

    start_time = time.time()
    hook = hook or PipelineHook()

    # ── Stage 1: search_and_read ──
    on_step("search_and_read", "running")
    pages = search_and_read(question, max_sources=6)
    sources_by_id = {p.source_id: p for p in pages}
    on_step("search_and_read", "done")

    # ── Stage 2: extract_claims ──
    on_step("extract_claims", "running")
    claims = extract_claims(pages)
    claims_by_id = {c.id: c for c in claims}
    hook.on_claims_extracted(claims)
    on_step("extract_claims", "done")

    # ── Stage 3: analyze_claims ──
    on_step("analyze_claims", "running")
    groups = analyze_claims(claims)
    on_step("analyze_claims", "done")

    # ── Stages 4 & 5 in Parallel: write_report and visualize ──
    on_step("synthesize_and_visualize", "running")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_report = executor.submit(write_report, question, groups, claims_by_id, sources_by_id)
        future_visuals = executor.submit(generate_all_visuals, groups, claims_by_id, pages)

        formatted_report, raw_report, rejected_markers = future_report.result()
        visuals = future_visuals.result()

    hook.on_report_written(formatted_report, groups)
    on_step("synthesize_and_visualize", "done")

    total_time = round(time.time() - start_time, 2)

    # ── Assemble Output Records ──
    sources_data = [p.to_dict() for p in pages]
    claims_data = [c.to_dict() for c in claims]
    groups_data = [g.to_dict() for g in groups]

    result = ResearchResult(
        topic=question,
        report_markdown=formatted_report,
        report_raw=raw_report,
        sources=sources_data,
        claims=claims_data,
        groups=groups_data,
        visuals=visuals,
        stats={
            "duration_seconds": total_time,
            "sources_count": len(pages),
            "claims_count": len(claims),
            "groups_count": len(groups),
            "rejected_markers": rejected_markers,
        }
    )

    return result.to_dict()


if __name__ == "__main__":
    q = input("\nEnter research question: ")
    res = run_evidence_pipeline(q)
    print("\n" + "=" * 50)
    print("REPORT:\n", res["report_markdown"])
    print("\n" + "=" * 50)
    print("SOURCES:\n", json.dumps(res["sources"], indent=2))
