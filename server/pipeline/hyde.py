"""
Curalink Pipeline — Stage 1: HyDE Expansion
Calls Groq LLaMA 3.1 70B to generate a hypothetical ideal abstract
and extract 4 semantically diverse query variants.
"""

import os
from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential
from models.schemas import HyDEExpansion, HYDE_XML_PROMPT
from models.xml_parser import parse_hyde_response
from observability.langsmith import traced
from observability.logger import get_logger

log = get_logger("curalink.pipeline.hyde")
client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))


@traced(name="HyDE Expansion", metadata={"stage": 1, "call": "groq_llama_70b"})
async def run_hyde_expansion(
    query:      str,
    disease:    str,
    is_followup: bool = False,
    prior_context: str = ""
) -> HyDEExpansion:
    """
    Call 1 — Generate HyDE expansion.
    Builds synonym-rich query variants to maximize retrieval recall.
    """

    context_block = ""
    if is_followup and prior_context:
        context_block = f"Prior conversation context: {prior_context}\nThis is a follow-up query — incorporate the above context."

    prompt = HYDE_XML_PROMPT.format(
        query=query,
        disease=disease,
        context_block=context_block,
    )

    raw = await _call_groq(prompt)
    expansion = parse_hyde_response(raw, query, disease)
    expansion.is_followup = is_followup
    expansion.injected_context = prior_context or None

    log.info(f"HyDE generated {len(expansion.query_variants)} variants | followup={is_followup}")
    for i, v in enumerate(expansion.query_variants, 1):
        log.debug(f"  Variant {i}: {v}")

    return expansion


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def _call_groq(prompt: str) -> str:
    response = await client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a medical research expert. "
                    "Always respond with valid XML only. "
                    "No preamble, no markdown, no explanation outside the XML tags."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=1000,
    )
    return response.choices[0].message.content
