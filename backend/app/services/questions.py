from __future__ import annotations

from typing import Any

from app.adapters.items import ItemsAdapter
from app.adapters.questions import QuestionsAdapter
from app.clients.mercadolibre import MercadoLibreClient
from app.core.account_store import AccountStore
from app.core.exceptions import BadRequestError
from app.schemas.questions import (
    QuestionAnswer,
    QuestionDetail,
    QuestionItemRef,
    QuestionListResponse,
    QuestionSummary,
)


def _parse_questions_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    for key in ("questions", "results", "data"):
        if isinstance(payload.get(key), list):
            total = int(
                payload.get("total")
                or payload.get("paging", {}).get("total")
                or len(payload[key])
            )
            return payload[key], total
    return [], 0


class QuestionsService:
    def __init__(
        self,
        account_store: AccountStore,
        client: MercadoLibreClient,
        questions_adapter: QuestionsAdapter,
        items_adapter: ItemsAdapter,
    ) -> None:
        self._account_store = account_store
        self._client = client
        self._questions_adapter = questions_adapter
        self._items_adapter = items_adapter

    async def _resolve_user_id(self, account_key: str) -> int:
        account = self._account_store.get_account(account_key)
        if account.user_id:
            return account.user_id

        me = await self._client.get_me(account_key)
        user_id = int(me["id"])
        self._account_store.update_account_tokens(
            account_key,
            access_token=account.access_token,
            refresh_token=account.refresh_token,
            scope=account.scope,
            user_id=user_id,
        )
        return user_id

    @staticmethod
    def _answer_limitation(raw: dict[str, Any], account_user_id: int) -> str | None:
        status = str(raw.get("status") or "").upper()
        if raw.get("answer"):
            return "La pregunta ya fue respondida."
        if status == "ANSWERED":
            return "La pregunta ya fue respondida."
        if status == "CLOSED_UNANSWERED":
            return "La publicacion se cerro y la pregunta ya no puede responderse."
        if status == "UNDER_REVIEW":
            return "La pregunta esta bajo revision y no puede responderse por API."
        if status in {"BANNED", "DELETED", "DISABLED"}:
            return f"La pregunta tiene estado {status} y no puede responderse."
        if status and status != "UNANSWERED":
            return f"La pregunta esta en estado {status} y Mercado Libre no la expone como respondible por API."
        if bool(raw.get("hold")):
            return "La pregunta esta en hold y no puede responderse por ahora."
        if bool(raw.get("deleted_from_listing")):
            return "La publicacion asociada ya no esta disponible para responder esta pregunta."
        seller_id = raw.get("seller_id")
        if seller_id and int(seller_id) != account_user_id:
            return "La cuenta seleccionada no corresponde al vendedor de esta pregunta."
        return None

    @staticmethod
    def _serialize_question(raw: dict[str, Any], item_map: dict[str, dict[str, Any]]) -> QuestionSummary:
        item_id = raw.get("item_id")
        raw_item = item_map.get(str(item_id), {}) if item_id else {}
        answer_payload = raw.get("answer") or None

        item = None
        if item_id:
            item = QuestionItemRef(
                id=str(item_id),
                title=raw_item.get("title"),
                permalink=raw_item.get("permalink"),
                status=raw_item.get("status"),
            )

        answer = None
        if isinstance(answer_payload, dict):
            answer = QuestionAnswer(
                text=answer_payload.get("text"),
                status=answer_payload.get("status"),
                date_created=answer_payload.get("date_created"),
            )

        from_payload = raw.get("from") or {}
        return QuestionSummary(
            id=int(raw["id"]),
            text=str(raw.get("text") or ""),
            status=raw.get("status"),
            date_created=raw.get("date_created"),
            hold=bool(raw.get("hold") or False),
            deleted_from_listing=bool(raw.get("deleted_from_listing") or False),
            from_user_id=int(from_payload["id"]) if from_payload.get("id") else None,
            item=item,
            answer=answer,
            has_answer=bool(answer and answer.text),
        )

    async def list_questions(self, account_key: str, *, limit: int, offset: int) -> QuestionListResponse:
        seller_id = await self._resolve_user_id(account_key)
        payload = await self._questions_adapter.list_questions(
            account_key,
            seller_id=seller_id,
            limit=limit,
            offset=offset,
        )
        raw_questions, total = _parse_questions_payload(payload)
        item_ids = [str(question.get("item_id")) for question in raw_questions if question.get("item_id")]
        item_details = await self._items_adapter.get_items(account_key, list(dict.fromkeys(item_ids)))
        item_map = {
            str(entry["body"]["id"]): entry["body"]
            for entry in item_details
            if isinstance(entry, dict) and entry.get("code") == 200 and isinstance(entry.get("body"), dict)
        }
        items = [self._serialize_question(question, item_map) for question in raw_questions]
        return QuestionListResponse(items=items, total=total, offset=offset, limit=limit)

    async def get_question(self, account_key: str, question_id: int) -> QuestionDetail:
        raw = await self._questions_adapter.get_question(account_key, question_id)
        account_user_id = await self._resolve_user_id(account_key)
        item_map: dict[str, dict[str, Any]] = {}
        if raw.get("item_id"):
            item_details = await self._items_adapter.get_items(account_key, [str(raw["item_id"])])
            for entry in item_details:
                if isinstance(entry, dict) and entry.get("code") == 200 and isinstance(entry.get("body"), dict):
                    item_map[str(entry["body"]["id"])] = entry["body"]

        question = self._serialize_question(raw, item_map)
        answer_limitations = self._answer_limitation(raw, account_user_id)
        return QuestionDetail(
            **question.model_dump(),
            seller_id=raw.get("seller_id"),
            can_answer=answer_limitations is None,
            answer_limitations=answer_limitations,
        )

    async def answer_question(self, account_key: str, question_id: int, text: str) -> QuestionDetail:
        raw_question = await self._questions_adapter.get_question(account_key, question_id)
        account_user_id = await self._resolve_user_id(account_key)
        answer_limitations = self._answer_limitation(raw_question, account_user_id)
        if answer_limitations is not None:
            raise BadRequestError(answer_limitations)
        await self._questions_adapter.answer_question(account_key, question_id, text)
        return await self.get_question(account_key, question_id)
