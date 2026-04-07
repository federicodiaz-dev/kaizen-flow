from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.config import AgentSettings, get_agent_settings
from app.core.exceptions import AppError, BadRequestError
from app.schemas.claims import ClaimDetail
from app.schemas.items import ItemDetail
from app.schemas.post_sale_messages import PostSaleConversationDetail
from app.schemas.questions import QuestionDetail
from app.schemas.reply_assistant import (
    ClaimDraftRequest,
    ClaimDraftResponse,
    PostSaleDraftRequest,
    PostSaleDraftResponse,
    QuestionDraftRequest,
    QuestionDraftResponse,
)
from app.services.claims import ClaimsService
from app.services.items import ItemsService
from app.services.post_sale_messages import PostSaleMessagesService
from app.services.questions import QuestionsService
from app.services.reply_assistant_prompts import (
    CLAIM_REPLY_DRAFTER_PROMPT,
    MERCADO_LIBRE_POLICY_BASELINE_PROMPT,
    POST_SALE_REPLY_DRAFTER_PROMPT,
    QUESTION_REPLY_DRAFTER_PROMPT,
)

logger = logging.getLogger("kaizen-flow.reply-assistant")


def _truncate(value: str | None, limit: int) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _json_block(payload: Any, *, limit: int = 5000) -> str:
    if payload in (None, "", [], {}):
        return ""
    try:
        raw = json.dumps(payload, ensure_ascii=False)
    except TypeError:
        raw = str(payload)
    return _truncate(raw, limit)


class ReplyAssistantService:
    def __init__(
        self,
        *,
        questions_service: QuestionsService,
        claims_service: ClaimsService,
        post_sale_messages_service: PostSaleMessagesService,
        items_service: ItemsService,
        settings: AgentSettings | None = None,
    ) -> None:
        self._questions_service = questions_service
        self._claims_service = claims_service
        self._post_sale_messages_service = post_sale_messages_service
        self._items_service = items_service
        self._settings = settings or get_agent_settings()
        self._llm = None

    def _get_llm(self):
        if self._llm is not None:
            return self._llm

        from langchain_groq import ChatGroq

        self._settings.validate_runtime()
        self._llm = ChatGroq(
            api_key=self._settings.groq_api_key,
            model=self._settings.groq_model,
            temperature=0.2,
            max_retries=2,
        )
        return self._llm

    async def suggest_question_answer(
        self,
        account_key: str,
        question_id: int,
        payload: QuestionDraftRequest,
    ) -> QuestionDraftResponse:
        question = await self._questions_service.get_question(account_key, question_id)
        if question.has_answer:
            raise BadRequestError("La pregunta ya fue respondida.")
        if not question.can_answer:
            raise BadRequestError(question.answer_limitations or "La pregunta no puede responderse por ahora.")

        item_detail = await self._load_item_context(account_key, question)
        prompt = self._build_question_prompt(question=question, item_detail=item_detail, payload=payload)
        draft = await self._invoke_plain_text(prompt, fallback=self._fallback_question_draft(question, item_detail))
        return QuestionDraftResponse(draft_answer=draft)

    async def suggest_claim_message(
        self,
        account_key: str,
        claim_id: int,
        payload: ClaimDraftRequest,
    ) -> ClaimDraftResponse:
        claim = await self._claims_service.get_claim(account_key, claim_id)
        if not claim.can_message:
            raise BadRequestError(
                claim.message_limitations or "El reclamo no admite mensajes en este momento."
            )

        receiver_role = self._resolve_receiver_role(claim, payload.receiver_role)
        prompt = self._build_claim_prompt(claim=claim, receiver_role=receiver_role, payload=payload)
        draft = await self._invoke_plain_text(
            prompt,
            fallback=self._fallback_claim_draft(claim, receiver_role),
        )
        return ClaimDraftResponse(draft_message=draft)

    async def suggest_post_sale_message(
        self,
        account_key: str,
        pack_id: str,
        payload: PostSaleDraftRequest,
    ) -> PostSaleDraftResponse:
        conversation = await self._post_sale_messages_service.get_conversation(
            account_key,
            pack_id,
            mark_as_read=False,
        )
        if not conversation.can_reply:
            raise BadRequestError(
                conversation.reply_limitations or "La conversación post venta no admite respuestas en este momento."
            )

        item_detail = await self._load_post_sale_item_context(account_key, conversation)
        prompt = self._build_post_sale_prompt(
            conversation=conversation,
            item_detail=item_detail,
            payload=payload,
        )
        draft = await self._invoke_plain_text(
            prompt,
            fallback=self._fallback_post_sale_draft(conversation, item_detail),
        )
        return PostSaleDraftResponse(draft_message=draft)

    async def _load_item_context(self, account_key: str, question: QuestionDetail) -> ItemDetail | None:
        item_id = question.item.id if question.item else None
        if not item_id:
            return None
        try:
            return await self._items_service.get_item(account_key, item_id)
        except AppError:
            return None
        except Exception:
            logger.warning("Could not load item context for question draft.", exc_info=True)
            return None

    async def _load_post_sale_item_context(
        self,
        account_key: str,
        conversation: PostSaleConversationDetail,
    ) -> ItemDetail | None:
        first_item_id = None
        for order in conversation.orders:
            for item in order.items:
                if item.item_id:
                    first_item_id = item.item_id
                    break
            if first_item_id:
                break

        if not first_item_id:
            return None
        try:
            return await self._items_service.get_item(account_key, first_item_id)
        except AppError:
            return None
        except Exception:
            logger.warning("Could not load item context for post-sale draft.", exc_info=True)
            return None

    def _build_question_prompt(
        self,
        *,
        question: QuestionDetail,
        item_detail: ItemDetail | None,
        payload: QuestionDraftRequest,
    ) -> list[SystemMessage | HumanMessage]:
        item_lines: list[str] = []
        if item_detail is not None:
            item_lines.extend(
                [
                    f"Titulo del producto: {item_detail.title}",
                    f"Estado de la publicacion: {item_detail.status or 'N/D'}",
                    f"Precio: {item_detail.price} {item_detail.currency_id or ''}".strip(),
                    f"Stock disponible: {item_detail.available_quantity if item_detail.available_quantity is not None else 'N/D'}",
                    f"Condicion: {item_detail.condition or 'N/D'}",
                ]
            )
            attrs = [
                {
                    "name": attr.get("name"),
                    "value_name": attr.get("value_name"),
                }
                for attr in item_detail.attributes[:12]
                if isinstance(attr, dict)
            ]
            if attrs:
                item_lines.append(f"Atributos: {_json_block(attrs, limit=1500)}")
            if item_detail.description:
                item_lines.append(f"Descripcion de la publicacion:\n{_truncate(item_detail.description, 2500)}")
        elif question.item is not None:
            item_lines.extend(
                [
                    f"Titulo del producto: {question.item.title or 'N/D'}",
                    f"Estado de la publicacion: {question.item.status or 'N/D'}",
                ]
            )

        current_draft = _truncate(payload.current_draft, 1800) if payload.current_draft else ""
        user_prompt = (
            f"Question id: {question.id}\n"
            f"Texto de la pregunta: {question.text}\n"
            f"Fecha: {question.date_created or 'N/D'}\n"
            f"Estado de la pregunta: {question.status or 'N/D'}\n"
            f"Usuario comprador: {question.from_user_id or 'N/D'}\n"
            f"Limitaciones para responder: {question.answer_limitations or 'ninguna'}\n\n"
            f"Contexto de la publicacion:\n{chr(10).join(item_lines) or 'Sin datos adicionales del item.'}\n\n"
            f"Borrador actual del vendedor:\n{current_draft or '(vacio)'}\n\n"
            "Genera una sola respuesta final lista para pegar en Mercado Libre."
        )
        return [
            SystemMessage(content=MERCADO_LIBRE_POLICY_BASELINE_PROMPT),
            SystemMessage(content=QUESTION_REPLY_DRAFTER_PROMPT),
            HumanMessage(content=user_prompt),
        ]

    def _build_claim_prompt(
        self,
        *,
        claim: ClaimDetail,
        receiver_role: str,
        payload: ClaimDraftRequest,
    ) -> list[SystemMessage | HumanMessage]:
        recent_messages = [
            {
                "sender_role": message.sender_role,
                "receiver_role": message.receiver_role,
                "stage": message.stage,
                "date_created": message.date_created,
                "message": _truncate(message.message, 700),
            }
            for message in claim.messages[-12:]
        ]
        recent_history = [
            {
                "stage": entry.stage,
                "status": entry.status,
                "date": entry.date,
                "change_by": entry.change_by,
            }
            for entry in claim.status_history[-8:]
        ]
        expected_resolutions = [
            {
                "player_role": entry.player_role,
                "expected_resolution": entry.expected_resolution,
                "status": entry.status,
            }
            for entry in claim.expected_resolutions[-8:]
        ]
        audience = "comprador" if receiver_role == "complainant" else "mediador de Mercado Libre"
        current_draft = _truncate(payload.current_draft, 3000) if payload.current_draft else ""

        user_prompt = (
            f"Claim id: {claim.id}\n"
            f"Destinatario del borrador: {audience}\n"
            f"receiver_role tecnico: {receiver_role}\n"
            f"Estado: {claim.status or 'N/D'}\n"
            f"Etapa: {claim.stage or 'N/D'}\n"
            f"Tipo: {claim.type or 'N/D'}\n"
            f"Motivo API: {claim.reason_id or 'N/D'}\n"
            f"Motivo legible: {claim.reason_detail.name if claim.reason_detail else 'N/D'}\n"
            f"Detalle del motivo: {claim.reason_detail.detail if claim.reason_detail else 'N/D'}\n"
            f"Roles habilitados para escribir: {', '.join(claim.allowed_receiver_roles) or 'ninguno'}\n"
            f"Limitaciones del caso: {claim.message_limitations or 'ninguna'}\n"
            f"Impacto reputacional: {_json_block(claim.reputation_impact.model_dump() if claim.reputation_impact else None, limit=1200) or 'N/D'}\n"
            f"Acciones disponibles: {_json_block([action.model_dump() for action in claim.available_actions], limit=1800) or 'N/D'}\n"
            f"Expected resolutions: {_json_block(expected_resolutions, limit=1600) or 'N/D'}\n"
            f"Historial reciente del estado: {_json_block(recent_history, limit=1800) or 'N/D'}\n"
            f"Mensajes recientes del reclamo: {_json_block(recent_messages, limit=3500) or 'N/D'}\n"
            f"Resolution payload: {_json_block(claim.resolution, limit=1500) or 'N/D'}\n\n"
            f"Borrador actual del vendedor:\n{current_draft or '(vacio)'}\n\n"
            "Genera un solo mensaje final listo para pegar en Mercado Libre."
        )
        return [
            SystemMessage(content=MERCADO_LIBRE_POLICY_BASELINE_PROMPT),
            SystemMessage(content=CLAIM_REPLY_DRAFTER_PROMPT),
            HumanMessage(content=user_prompt),
        ]

    def _build_post_sale_prompt(
        self,
        *,
        conversation: PostSaleConversationDetail,
        item_detail: ItemDetail | None,
        payload: PostSaleDraftRequest,
    ) -> list[SystemMessage | HumanMessage]:
        recent_messages = [
            {
                "from_user_id": message.from_user.user_id if message.from_user else None,
                "from_name": message.from_user.nickname if message.from_user else None,
                "date_created": message.date_created,
                "text": _truncate(message.text, 700),
                "is_from_seller": message.is_from_seller,
            }
            for message in conversation.messages[-12:]
        ]
        order_snapshot = [
            {
                "order_id": order.id,
                "status": order.status,
                "date_created": order.date_created,
                "total_amount": order.total_amount,
                "currency_id": order.currency_id,
                "items": [
                    {
                        "item_id": item.item_id,
                        "title": item.title,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                    }
                    for item in order.items
                ],
            }
            for order in conversation.orders[:6]
        ]

        item_lines: list[str] = []
        if item_detail is not None:
            item_lines.extend(
                [
                    f"Titulo principal del item: {item_detail.title}",
                    f"Estado de la publicacion: {item_detail.status or 'N/D'}",
                    f"Precio actual: {item_detail.price} {item_detail.currency_id or ''}".strip(),
                    f"Condicion: {item_detail.condition or 'N/D'}",
                ]
            )
            attrs = [
                {"name": attr.get("name"), "value_name": attr.get("value_name")}
                for attr in item_detail.attributes[:12]
                if isinstance(attr, dict)
            ]
            if attrs:
                item_lines.append(f"Atributos: {_json_block(attrs, limit=1500)}")
            if item_detail.description:
                item_lines.append(f"Descripcion de la publicacion:\n{_truncate(item_detail.description, 2500)}")
        elif conversation.primary_item_title:
            item_lines.append(f"Titulo principal del item: {conversation.primary_item_title}")

        current_draft = _truncate(payload.current_draft, 3000) if payload.current_draft else ""
        user_prompt = (
            f"Pack id: {conversation.pack_id}\n"
            f"Comprador: {conversation.buyer_name or conversation.buyer_nickname or conversation.buyer_user_id or 'N/D'}\n"
            f"Estado de la conversacion: {conversation.conversation_status or 'N/D'}\n"
            f"Subestado: {conversation.conversation_substatus or 'N/D'}\n"
            f"Cantidad de mensajes: {conversation.message_count}\n"
            f"Maximo para el vendedor: {conversation.seller_max_message_length or 'N/D'} caracteres\n"
            f"Limitaciones actuales: {conversation.reply_limitations or 'ninguna'}\n"
            f"Ordenes del pack: {_json_block(order_snapshot, limit=2500) or 'N/D'}\n"
            f"Mensajes recientes del pack: {_json_block(recent_messages, limit=3500) or 'N/D'}\n"
            f"Contexto adicional del item:\n{chr(10).join(item_lines) or 'Sin contexto adicional del item.'}\n\n"
            f"Borrador actual del vendedor:\n{current_draft or '(vacio)'}\n\n"
            "Genera un solo mensaje final listo para pegar en Mercado Libre."
        )
        return [
            SystemMessage(content=MERCADO_LIBRE_POLICY_BASELINE_PROMPT),
            SystemMessage(content=POST_SALE_REPLY_DRAFTER_PROMPT),
            HumanMessage(content=user_prompt),
        ]

    async def _invoke_plain_text(
        self,
        messages: list[SystemMessage | HumanMessage],
        *,
        fallback: str,
    ) -> str:
        llm = self._get_llm()
        try:
            response = await llm.ainvoke(messages)
            content = response.content if isinstance(response.content, str) else str(response.content)
            cleaned = self._clean_plain_text(content)
            return cleaned or fallback
        except Exception:
            logger.warning("Reply assistant generation failed. Using fallback draft.", exc_info=True)
            return fallback

    @staticmethod
    def _clean_plain_text(raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        text = text.replace("```text", "").replace("```", "").strip()
        lines = [line.rstrip() for line in text.splitlines()]
        cleaned_lines: list[str] = []
        for line in lines:
            stripped = line.lstrip("#").strip()
            cleaned_lines.append(stripped if stripped else "")
        return "\n".join(cleaned_lines).strip()

    @staticmethod
    def _fallback_question_draft(question: QuestionDetail, item_detail: ItemDetail | None) -> str:
        title = item_detail.title if item_detail is not None else (question.item.title if question.item else None)
        if title:
            return (
                f"Hola. Gracias por tu consulta sobre {title}. "
                "Estoy revisando tu duda con la informacion disponible de la publicacion para responderte con precision. "
                "Si queres, tambien puedo confirmarte el detalle puntual que necesitas."
            )
        return (
            "Hola. Gracias por tu consulta. "
            "Estoy revisando la informacion disponible de la publicacion para responderte con precision. "
            "Si queres, tambien puedo confirmarte el detalle puntual que necesitas."
        )

    @staticmethod
    def _resolve_receiver_role(claim: ClaimDetail, requested_role: str | None) -> str:
        if requested_role:
            normalized = requested_role.strip().lower()
            if normalized in claim.allowed_receiver_roles:
                return normalized

        if "complainant" in claim.allowed_receiver_roles:
            return "complainant"
        if claim.allowed_receiver_roles:
            return claim.allowed_receiver_roles[0]
        raise BadRequestError("El reclamo no tiene destinatarios habilitados para mensajeria.")

    @staticmethod
    def _fallback_claim_draft(claim: ClaimDetail, receiver_role: str) -> str:
        if receiver_role == "mediator":
            return (
                "Solicitamos revisar el caso con base en los hechos disponibles del reclamo. "
                "Necesitamos que la evaluacion considere la cronologia, la evidencia efectivamente aportada y cualquier punto que aun no se encuentre acreditado. "
                "Quedamos a disposicion para ampliar la informacion necesaria por esta misma via."
            )
        if claim.reason_detail and claim.reason_detail.name:
            return (
                f"Hola. Estamos revisando tu reclamo por {claim.reason_detail.name}. "
                "Queremos resolverlo correctamente, por eso necesitamos validar los hechos y la evidencia concreta del caso antes de avanzar con una definicion. "
                "Si corresponde, por favor envianos el detalle y respaldo adicional por este medio."
            )
        return (
            "Hola. Estamos revisando tu reclamo y queremos resolverlo correctamente. "
            "Para avanzar, necesitamos validar los hechos y la evidencia concreta del caso antes de tomar una definicion. "
            "Si corresponde, por favor envianos el detalle y respaldo adicional por este medio."
        )

    @staticmethod
    def _fallback_post_sale_draft(
        conversation: PostSaleConversationDetail,
        item_detail: ItemDetail | None,
    ) -> str:
        title = item_detail.title if item_detail is not None else conversation.primary_item_title
        if title:
            return (
                f"Hola. Gracias por escribirnos sobre tu compra de {title}. "
                "Estoy revisando el detalle del pack para responderte con precision y ayudarte por esta misma via. "
                "Si hace falta, indicanos puntualmente lo que necesitas y seguimos desde aca."
            )
        return (
            "Hola. Gracias por escribirnos. "
            "Estoy revisando el detalle de tu compra para responderte con precision y ayudarte por esta misma via. "
            "Si hace falta, indicanos puntualmente lo que necesitas y seguimos desde aca."
        )
