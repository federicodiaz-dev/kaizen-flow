from __future__ import annotations

import logging
import re

from app.agents.config import AgentSettings, get_agent_settings
from app.agents.prompts import DESCRIPTION_ENHANCER_PROMPT, LISTING_COPYWRITER_PROMPT
from app.core.ai_usage_reporting import create_chat_groq, llm_run_config
from app.schemas.copywriter import (
    CopywriterGenerateRequest,
    CopywriterGenerateResponse,
    DescriptionEnhanceRequest,
    DescriptionEnhanceResponse,
)

logger = logging.getLogger("kaizen-flow.copywriter")


class CopywriterService:
    """Standalone AI service for generating listing titles/descriptions."""

    def __init__(self, settings: AgentSettings | None = None) -> None:
        self._settings = settings or get_agent_settings()
        self._llm = None

    def _get_llm(self):
        if self._llm is not None:
            return self._llm

        self._settings.validate_runtime()
        self._llm = create_chat_groq(
            self._settings,
            model=self._settings.groq_model,
            temperature=0.7,
            feature="copywriter",
            max_retries=2,
        )
        return self._llm

    async def generate_listing(self, request: CopywriterGenerateRequest) -> CopywriterGenerateResponse:
        llm = self._get_llm()

        user_data = f"Producto: {request.product}"
        if request.brand:
            user_data += f"\nMarca: {request.brand}"
        user_data += f"\nPaís objetivo: {request.country}"
        if request.confirmed_data:
            user_data += f"\nDatos confirmados del producto: {request.confirmed_data}"
        if request.commercial_objective:
            user_data += f"\nObjetivo comercial: {request.commercial_objective}"

        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=LISTING_COPYWRITER_PROMPT),
            HumanMessage(content=user_data),
        ]

        response = await llm.ainvoke(
            messages,
            config=llm_run_config("copywriter.generate_listing"),
        )
        raw_text = response.content if isinstance(response.content, str) else str(response.content)

        titles, description = self._parse_generate_output(raw_text)

        return CopywriterGenerateResponse(titles=titles, description=description)

    async def enhance_description(self, request: DescriptionEnhanceRequest) -> DescriptionEnhanceResponse:
        llm = self._get_llm()

        context_parts = [f"Título del producto: {request.product_title}"]
        if request.brand:
            context_parts.append(f"Marca: {request.brand}")
        if request.category:
            context_parts.append(f"Categoría: {request.category}")
        if request.price is not None and request.currency:
            context_parts.append(f"Precio: {request.price} {request.currency}")
        if request.condition:
            context_parts.append(f"Condición: {request.condition}")
        if request.attributes:
            attrs = ", ".join(
                f"{a.get('name', 'N/D')}: {a.get('value_name', a.get('value', 'N/D'))}"
                for a in request.attributes[:20]
            )
            context_parts.append(f"Atributos: {attrs}")
        if request.improvement_notes:
            context_parts.append(f"Notas de mejora priorizadas: {request.improvement_notes}")
        if request.current_description:
            context_parts.append(f"\nDescripción actual:\n{request.current_description}")
        else:
            context_parts.append("\nDescripción actual: (vacía)")

        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=DESCRIPTION_ENHANCER_PROMPT),
            HumanMessage(content="\n".join(context_parts)),
        ]

        response = await llm.ainvoke(
            messages,
            config=llm_run_config("copywriter.enhance_description"),
        )
        raw_text = response.content if isinstance(response.content, str) else str(response.content)

        return DescriptionEnhanceResponse(enhanced_description=raw_text.strip())

    @staticmethod
    def _parse_generate_output(raw: str) -> tuple[list[str], str]:
        titles: list[str] = []
        description = ""

        # Try to split by the description marker
        desc_markers = [
            "DESCRIPCIÓN PARA MERCADO LIBRE",
            "DESCRIPCION PARA MERCADO LIBRE",
            "## DESCRIPCIÓN",
            "## DESCRIPCION",
        ]
        desc_start_idx = -1
        for marker in desc_markers:
            idx = raw.upper().find(marker.upper())
            if idx != -1:
                desc_start_idx = idx
                break

        if desc_start_idx != -1:
            titles_section = raw[:desc_start_idx]
            desc_section = raw[desc_start_idx:]
            # Remove the header from description
            for marker in desc_markers:
                desc_section = re.sub(
                    re.escape(marker), "", desc_section, count=1, flags=re.IGNORECASE
                )
            description = desc_section.strip().lstrip("#").strip()
        else:
            titles_section = raw
            description = ""

        # Parse numbered titles: 1. ... 2. ... etc.
        title_matches = re.findall(r"^\d+[\.\)]\s*(.+)$", titles_section, re.MULTILINE)
        titles = [t.strip() for t in title_matches if t.strip()][:10]

        return titles, description
