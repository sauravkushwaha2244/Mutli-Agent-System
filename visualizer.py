"""Code-only visualization generator for agreement distribution, credibility scores, and conflict maps."""

from typing import List, Dict, Any, Optional
import json
import plotly.graph_objects as go

from models import ClaimGroup, ClaimRecord, PageRecord


def generate_agreement_chart(groups: List[ClaimGroup]) -> Optional[Dict[str, Any]]:
    """Generates a Plotly Donut Chart of claim consensus distribution.
    Returns None if no groups are available."""
    if not groups:
        return None

    counts = {"AGREE": 0, "DISPUTED": 0, "SINGLE_SOURCE": 0}
    for g in groups:
        if g.consensus in counts:
            counts[g.consensus] += 1

    labels = ["Well Supported (Agree)", "Disputed", "Single Source"]
    values = [counts["AGREE"], counts["DISPUTED"], counts["SINGLE_SOURCE"]]
    colors = ["#67d391", "#ff6b6b", "#ff8d3a"]

    # Don't render if completely empty
    if sum(values) == 0:
        return None

    fig = go.Figure(data=[
        go.Pie(
            labels=labels,
            values=values,
            hole=0.55,
            marker=dict(colors=colors, line=dict(color="#0b0c0d", width=2)),
            textinfo="label+value",
            hoverinfo="label+value+percent",
        )
    ])

    fig.update_layout(
        title=dict(text="Evidence Consensus Distribution", font=dict(color="#f2eee6", size=16)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#97918a", family="DM Sans, sans-serif"),
        showlegend=True,
        margin=dict(t=50, b=30, l=30, r=30),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
    )

    return json.loads(fig.to_json())


def generate_credibility_chart(sources: List[PageRecord]) -> Optional[Dict[str, Any]]:
    """Generates a horizontal Plotly bar chart ranking source credibility scores."""
    if not sources:
        return None

    # Sort sources by credibility score
    sorted_sources = sorted(sources, key=lambda s: s.credibility)
    labels = [f"[{s.source_id}] {s.source_name[:22]}" for s in sorted_sources]
    scores = [s.credibility for s in sorted_sources]
    urls = [s.url for s in sorted_sources]

    # Color code bars: green >= 0.75, amber 0.50 - 0.74, red < 0.50
    bar_colors = [
        "#67d391" if score >= 0.75 else ("#ffb15c" if score >= 0.50 else "#ff6b6b")
        for score in scores
    ]

    fig = go.Figure(data=[
        go.Bar(
            x=scores,
            y=labels,
            orientation="h",
            marker=dict(color=bar_colors),
            text=[f"{s:.2f}" for s in scores],
            textposition="auto",
            customdata=urls,
            hovertemplate="<b>%{y}</b><br>Credibility: %{x:.2f}<br>URL: %{customdata}<extra></extra>",
        )
    ])

    fig.update_layout(
        title=dict(text="Source Credibility Scores", font=dict(color="#f2eee6", size=16)),
        xaxis=dict(range=[0, 1.05], gridcolor="rgba(255,255,255,0.08)", tickfont=dict(color="#97918a")),
        yaxis=dict(tickfont=dict(color="#f2eee6")),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif"),
        margin=dict(t=50, b=30, l=140, r=30),
    )

    return json.loads(fig.to_json())


def generate_conflict_map(groups: List[ClaimGroup], claims_by_id: Dict[str, ClaimRecord]) -> Optional[str]:
    """Generates a Mermaid diagram for disputed claims.
    Returns None if there are NO disputed groups (hides visual if no data)."""
    disputed_groups = [g for g in groups if g.consensus == "DISPUTED"]
    if not disputed_groups:
        return None

    lines = ["flowchart TD"]
    for i, g in enumerate(disputed_groups, 1):
        topic_escaped = g.topic.replace('"', "'")
        cluster_id = f"Dispute_{i}"
        lines.append(f'    subgraph {cluster_id}["Disputed Fact: {topic_escaped}"]')
        for cid in g.claim_ids:
            claim = claims_by_id.get(cid)
            if claim:
                # Escape quotes and brackets
                claim_text = (claim.text[:80] + "...").replace('"', "'").replace("[", "(").replace("]", ")")
                src_label = f"[{claim.source_id}] {claim.source_name[:18]}"
                lines.append(f'        c_{claim.id}["<b>{src_label}</b><br/>{claim_text}"]')
        lines.append("    end")

    return "\n".join(lines)


def generate_all_visuals(
    groups: List[ClaimGroup],
    claims_by_id: Dict[str, ClaimRecord],
    sources: List[PageRecord]
) -> Dict[str, Any]:
    """Top-level visualizer assembling Plotly and Mermaid visuals, omitting empty data."""
    visuals: Dict[str, Any] = {}

    agreement_chart = generate_agreement_chart(groups)
    if agreement_chart:
        visuals["agreement_chart"] = agreement_chart

    credibility_chart = generate_credibility_chart(sources)
    if credibility_chart:
        visuals["credibility_chart"] = credibility_chart

    conflict_map = generate_conflict_map(groups, claims_by_id)
    if conflict_map:
        visuals["conflict_map"] = conflict_map

    return visuals
