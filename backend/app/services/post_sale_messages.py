from __future__ import annotations

import asyncio
import re
from typing import Any

from app.adapters.post_sale_messages import PostSaleMessagesAdapter
from app.clients.mercadolibre import MercadoLibreClient
from app.core.account_store import AccountStore
from app.core.exceptions import AppError, BadRequestError
from app.schemas.post_sale_messages import (
    PostSaleConversationDetail,
    PostSaleConversationListResponse,
    PostSaleConversationParty,
    PostSaleConversationSummary,
    PostSaleMessage,
    PostSaleMessageAttachment,
    PostSaleMessageResult,
    PostSaleOrderItemRef,
    PostSaleOrderRef,
)


class PostSaleMessagesService:
    _ORDER_SCAN_LIMIT = 51
    _LIST_BATCH_SIZE = 10
    _MESSAGE_PAGE_SIZE = 50
    _MESSAGE_HARD_LIMIT = 250

    def __init__(
        self,
        account_store: AccountStore,
        client: MercadoLibreClient,
        adapter: PostSaleMessagesAdapter,
    ) -> None:
        self._account_store = account_store
        self._client = client
        self._adapter = adapter

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
    def _safe_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _resource_pack_id(resource: str | None) -> str | None:
        if not resource:
            return None
        match = re.search(r"/packs/([^/]+)", resource)
        return match.group(1) if match else None

    @classmethod
    def _build_unread_map(cls, payload: dict[str, Any]) -> dict[str, int]:
        unread_by_pack: dict[str, int] = {}
        raw_results = payload.get("results") if isinstance(payload.get("results"), list) else []
        for entry in raw_results:
            if not isinstance(entry, dict):
                continue
            pack_id = cls._resource_pack_id(str(entry.get("resource") or ""))
            if not pack_id:
                continue
            unread_by_pack[pack_id] = cls._safe_int(entry.get("count")) or 0
        return unread_by_pack

    @staticmethod
    def _normalize_text(raw: Any) -> str | None:
        if isinstance(raw, dict):
            for key in ("plain", "body", "translated", "text"):
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return None
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    @classmethod
    def _serialize_party(cls, raw: Any) -> PostSaleConversationParty | None:
        if not isinstance(raw, dict):
            return None
        user_id = cls._safe_int(raw.get("user_id") or raw.get("id"))
        name = str(raw.get("name") or "").strip() or None
        nickname = str(raw.get("nickname") or raw.get("name") or "").strip() or None
        if user_id is None and not name and not nickname:
            return None
        return PostSaleConversationParty(user_id=user_id, name=name, nickname=nickname)

    @classmethod
    def _serialize_attachments(cls, raw_message: dict[str, Any]) -> list[PostSaleMessageAttachment]:
        raw_attachments = (
            raw_message.get("attachments")
            if isinstance(raw_message.get("attachments"), list)
            else raw_message.get("message_attachments")
        )
        if not isinstance(raw_attachments, list):
            return []
        attachments: list[PostSaleMessageAttachment] = []
        for entry in raw_attachments:
            if not isinstance(entry, dict):
                continue
            attachments.append(
                PostSaleMessageAttachment(
                    filename=entry.get("filename"),
                    original_filename=entry.get("original_filename"),
                    size=cls._safe_int(entry.get("size")),
                    type=entry.get("type"),
                    date_created=entry.get("date_created") or entry.get("date"),
                    potential_security_threat=entry.get("potential_security_threat"),
                )
            )
        return attachments

    @classmethod
    def _serialize_message(cls, raw: dict[str, Any], seller_id: int) -> PostSaleMessage:
        message_dates = raw.get("message_date") if isinstance(raw.get("message_date"), dict) else {}
        moderation = raw.get("message_moderation") if isinstance(raw.get("message_moderation"), dict) else {}

        raw_to = raw.get("to") or raw.get("to_users") or []
        if isinstance(raw_to, dict):
            raw_to = [raw_to]

        from_user = cls._serialize_party(raw.get("from") or raw.get("from_user"))
        to_users = [party for party in (cls._serialize_party(entry) for entry in raw_to) if party is not None]

        text = (
            cls._normalize_text(raw.get("text"))
            or cls._normalize_text(raw.get("message"))
            or cls._normalize_text(raw.get("body"))
        )

        return PostSaleMessage(
            id=str(raw.get("id")) if raw.get("id") is not None else None,
            site_id=raw.get("site_id"),
            client_id=str(raw.get("client_id")) if raw.get("client_id") is not None else None,
            text=text,
            status=raw.get("status"),
            date_created=raw.get("date_created") or message_dates.get("created"),
            date_received=raw.get("date_received") or message_dates.get("received"),
            date_available=raw.get("date_available") or message_dates.get("available"),
            date_notified=raw.get("date_notified") or message_dates.get("notified"),
            date_read=raw.get("date_read") or message_dates.get("read"),
            from_user=from_user,
            to_users=to_users,
            attachments=cls._serialize_attachments(raw),
            moderation_status=moderation.get("status") or raw.get("moderation_status"),
            moderation_substatus=moderation.get("substatus") or raw.get("moderation_substatus"),
            moderation_source=moderation.get("source") or raw.get("moderation_source"),
            moderation_date=moderation.get("date_created") or raw.get("moderation_date"),
            conversation_first_message=raw.get("conversation_first_message"),
            is_from_seller=bool(from_user and from_user.user_id == seller_id),
        )

    @staticmethod
    def _message_sort_key(message: PostSaleMessage) -> tuple[str, str]:
        return (
            str(message.date_created or message.date_available or message.date_received or ""),
            str(message.id or ""),
        )

    @staticmethod
    def _extract_message_count(payload: dict[str, Any]) -> int:
        paging = payload.get("paging") if isinstance(payload.get("paging"), dict) else {}
        total = paging.get("total")
        if total is not None:
            try:
                return int(total)
            except (TypeError, ValueError):
                pass
        raw_messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        return len(raw_messages)

    @staticmethod
    def _blocked_reason(substatus: str | None) -> str:
        normalized = str(substatus or "").strip().lower()
        reasons = {
            "blocked_by_time": "La conversación superó la ventana permitida por Mercado Libre y solo volverá a abrirse si el comprador escribe nuevamente.",
            "blocked_by_buyer": "El comprador bloqueó la recepción de mensajes post venta.",
            "bloqued_by_mediation": "Hay una mediación en curso y el canal post venta quedó bloqueado.",
            "blocked_by_mediation": "Hay una mediación en curso y el canal post venta quedó bloqueado.",
            "blocked_by_fulfillment": "Al ser una venta Fulfillment, los mensajes se habilitan una vez que el envío figure como entregado.",
            "blocked_by_payment": "Mercado Libre todavía no impactó el pago de la orden y por eso bloquea la conversación.",
            "blocked_by_cancelled_order": "La orden fue cancelada y el canal de mensajes quedó bloqueado.",
        }
        return reasons.get(normalized) or "Mercado Libre bloqueó temporalmente la conversación post venta."

    @classmethod
    def _reply_capability(
        cls,
        *,
        buyer_user_id: int | None,
        message_count: int,
        conversation_status: str | None,
        conversation_substatus: str | None,
    ) -> tuple[bool, str | None]:
        if message_count <= 0:
            return False, "Todavía no hay mensajes post venta en este pack."
        if buyer_user_id is None:
            return False, "No se pudo identificar al comprador para responder este pack."
        if str(conversation_status or "").strip().lower() == "blocked":
            return False, cls._blocked_reason(conversation_substatus)
        return True, None

    @staticmethod
    def _iter_chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
        return [items[index : index + size] for index in range(0, len(items), size)]

    def _group_recent_orders(
        self,
        raw_orders: list[dict[str, Any]],
        unread_by_pack: dict[str, int],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}

        for raw in raw_orders:
            order_id = self._safe_int(raw.get("id"))
            pack_id = str(raw.get("pack_id") or order_id or "").strip()
            if not pack_id or order_id is None:
                continue

            buyer = raw.get("buyer") if isinstance(raw.get("buyer"), dict) else {}
            shipping = raw.get("shipping") if isinstance(raw.get("shipping"), dict) else {}
            item_titles = []
            for order_item in raw.get("order_items") or []:
                if not isinstance(order_item, dict):
                    continue
                item = order_item.get("item") if isinstance(order_item.get("item"), dict) else {}
                title = str(item.get("title") or "").strip()
                if title:
                    item_titles.append(title)

            entry = grouped.setdefault(
                pack_id,
                {
                    "pack_id": pack_id,
                    "buyer_user_id": self._safe_int(buyer.get("id")),
                    "buyer_name": str(buyer.get("nickname") or "").strip() or None,
                    "buyer_nickname": str(buyer.get("nickname") or "").strip() or None,
                    "item_titles": [],
                    "order_ids": [],
                    "date_created": raw.get("date_created"),
                    "last_updated": raw.get("last_updated") or raw.get("date_closed") or raw.get("date_created"),
                    "unread_count": unread_by_pack.get(pack_id, 0),
                    "pack_status": raw.get("status"),
                    "pack_status_detail": raw.get("status_detail"),
                    "site_id": raw.get("site_id"),
                    "shipping_id": self._safe_int(shipping.get("id")),
                    "total_amount": 0.0,
                    "currency_id": raw.get("currency_id"),
                },
            )

            entry["order_ids"].append(order_id)
            if item_titles:
                entry["item_titles"].extend(item_titles)

            if not entry.get("buyer_user_id"):
                entry["buyer_user_id"] = self._safe_int(buyer.get("id"))
            if not entry.get("buyer_name"):
                entry["buyer_name"] = str(buyer.get("nickname") or "").strip() or None
            if not entry.get("buyer_nickname"):
                entry["buyer_nickname"] = str(buyer.get("nickname") or "").strip() or None

            current_created = str(entry.get("date_created") or "")
            next_created = str(raw.get("date_created") or "")
            if not current_created or (next_created and next_created < current_created):
                entry["date_created"] = raw.get("date_created")

            current_updated = str(entry.get("last_updated") or "")
            next_updated = str(raw.get("last_updated") or raw.get("date_closed") or raw.get("date_created") or "")
            if next_updated and next_updated > current_updated:
                entry["last_updated"] = next_updated

            total_amount = self._safe_float(raw.get("total_amount"))
            if total_amount is not None:
                entry["total_amount"] = float(entry.get("total_amount") or 0.0) + total_amount

        grouped_items = list(grouped.values())
        for entry in grouped_items:
            deduped_titles = list(dict.fromkeys(title for title in entry["item_titles"] if title))
            entry["item_titles"] = deduped_titles
            entry["primary_item_title"] = deduped_titles[0] if deduped_titles else None
            entry["order_ids"] = list(dict.fromkeys(entry["order_ids"]))

        grouped_items.sort(
            key=lambda entry: (
                int(entry.get("unread_count") or 0) > 0,
                str(entry.get("last_updated") or ""),
                str(entry.get("pack_id") or ""),
            ),
            reverse=True,
        )
        return grouped_items

    async def _load_conversation_heads(
        self,
        account_key: str,
        *,
        seller_id: int,
        candidates: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        metadata: dict[str, dict[str, Any]] = {}
        for chunk in self._iter_chunks(candidates, self._LIST_BATCH_SIZE):
            results = await asyncio.gather(
                *[
                    self._adapter.get_pack_messages(
                        account_key,
                        pack_id=str(candidate["pack_id"]),
                        seller_id=seller_id,
                        mark_as_read=False,
                        limit=1,
                        offset=0,
                    )
                    for candidate in chunk
                ],
                return_exceptions=True,
            )

            for candidate, result in zip(chunk, results):
                if isinstance(result, Exception):
                    if isinstance(result, AppError) and result.status_code in {400, 404}:
                        continue
                    raise result
                metadata[str(candidate["pack_id"])] = result
        return metadata

    async def list_conversations(
        self,
        account_key: str,
        *,
        limit: int,
        offset: int,
    ) -> PostSaleConversationListResponse:
        seller_id = await self._resolve_user_id(account_key)
        unread_payload = await self._adapter.get_unread_messages(account_key)
        unread_by_pack = self._build_unread_map(unread_payload)

        order_window = min(self._ORDER_SCAN_LIMIT, max(limit + offset + 20, 30))
        raw_orders_payload = await self._adapter.list_recent_orders(
            account_key,
            seller_id=seller_id,
            limit=order_window,
            offset=0,
        )
        raw_orders = raw_orders_payload.get("results") if isinstance(raw_orders_payload.get("results"), list) else []
        candidates = self._group_recent_orders(
            [entry for entry in raw_orders if isinstance(entry, dict)],
            unread_by_pack,
        )
        if not candidates:
            return PostSaleConversationListResponse(items=[], total=0, offset=offset, limit=limit)

        metadata_by_pack = await self._load_conversation_heads(
            account_key,
            seller_id=seller_id,
            candidates=candidates,
        )

        conversations: list[PostSaleConversationSummary] = []
        for candidate in candidates:
            metadata = metadata_by_pack.get(str(candidate["pack_id"]))
            if not metadata:
                continue

            message_count = self._extract_message_count(metadata)
            if message_count <= 0 and int(candidate.get("unread_count") or 0) <= 0:
                continue

            conversation_status = (
                metadata.get("conversation_status")
                if isinstance(metadata.get("conversation_status"), dict)
                else {}
            )
            can_reply, limitation = self._reply_capability(
                buyer_user_id=self._safe_int(candidate.get("buyer_user_id")),
                message_count=message_count,
                conversation_status=conversation_status.get("status"),
                conversation_substatus=conversation_status.get("substatus"),
            )
            claim_ids = [
                claim_id
                for claim_id in (
                    self._safe_int(entry) for entry in (conversation_status.get("claim_ids") or [])
                )
                if claim_id is not None
            ]
            conversations.append(
                PostSaleConversationSummary(
                    pack_id=str(candidate["pack_id"]),
                    buyer_user_id=self._safe_int(candidate.get("buyer_user_id")),
                    buyer_name=candidate.get("buyer_name"),
                    buyer_nickname=candidate.get("buyer_nickname"),
                    primary_item_title=candidate.get("primary_item_title"),
                    item_titles=candidate.get("item_titles") or [],
                    order_ids=candidate.get("order_ids") or [],
                    date_created=candidate.get("date_created"),
                    last_updated=candidate.get("last_updated"),
                    unread_count=int(candidate.get("unread_count") or 0),
                    message_count=message_count,
                    conversation_status=conversation_status.get("status"),
                    conversation_substatus=conversation_status.get("substatus"),
                    pack_status=candidate.get("pack_status"),
                    pack_status_detail=candidate.get("pack_status_detail"),
                    seller_max_message_length=self._safe_int(metadata.get("seller_max_message_length")),
                    buyer_max_message_length=self._safe_int(metadata.get("buyer_max_message_length")),
                    can_reply=can_reply,
                    reply_limitations=limitation,
                    site_id=candidate.get("site_id"),
                    shipping_id=self._safe_int(
                        conversation_status.get("shipping_id") or candidate.get("shipping_id")
                    ),
                    total_amount=self._safe_float(candidate.get("total_amount")),
                    currency_id=candidate.get("currency_id"),
                    claim_ids=claim_ids,
                )
            )

        paged_items = conversations[offset : offset + limit]
        return PostSaleConversationListResponse(
            items=paged_items,
            total=len(conversations),
            offset=offset,
            limit=limit,
        )

    async def _load_pack_orders(
        self,
        account_key: str,
        *,
        pack_id: str,
        seller_id: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        pack_payload: dict[str, Any] = {}
        order_ids: list[int] = []

        try:
            pack_payload = await self._adapter.get_pack(account_key, pack_id)
            raw_orders = pack_payload.get("orders") if isinstance(pack_payload.get("orders"), list) else []
            order_ids = [self._safe_int(entry.get("id")) for entry in raw_orders if isinstance(entry, dict)]
            order_ids = [order_id for order_id in order_ids if order_id is not None]
        except AppError as exc:
            if exc.status_code not in {400, 404}:
                raise

        if not order_ids:
            fallback_order_id = self._safe_int(pack_id)
            if fallback_order_id is None:
                raise BadRequestError("No se pudo resolver el pack solicitado.")
            order_payload = await self._adapter.get_order(account_key, fallback_order_id)
            return {}, [order_payload]

        raw_results = await asyncio.gather(
            *[self._adapter.get_order(account_key, order_id) for order_id in order_ids],
            return_exceptions=True,
        )
        orders: list[dict[str, Any]] = []
        for result in raw_results:
            if isinstance(result, Exception):
                if isinstance(result, AppError) and result.status_code in {400, 404}:
                    continue
                raise result
            if not isinstance(result, dict):
                continue
            order_seller = result.get("seller") if isinstance(result.get("seller"), dict) else {}
            order_seller_id = self._safe_int(order_seller.get("id"))
            if order_seller_id is not None and order_seller_id != seller_id:
                continue
            orders.append(result)

        return pack_payload, orders

    async def _load_messages_payload(
        self,
        account_key: str,
        *,
        pack_id: str,
        seller_id: int,
        mark_as_read: bool,
    ) -> dict[str, Any]:
        payload = await self._adapter.get_pack_messages(
            account_key,
            pack_id=pack_id,
            seller_id=seller_id,
            mark_as_read=mark_as_read,
            limit=self._MESSAGE_PAGE_SIZE,
            offset=0,
        )
        raw_messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        total = self._extract_message_count(payload)
        loaded = len(raw_messages)

        while loaded < total and loaded < self._MESSAGE_HARD_LIMIT:
            page = await self._adapter.get_pack_messages(
                account_key,
                pack_id=pack_id,
                seller_id=seller_id,
                mark_as_read=False,
                limit=self._MESSAGE_PAGE_SIZE,
                offset=loaded,
            )
            page_messages = page.get("messages") if isinstance(page.get("messages"), list) else []
            if not page_messages:
                break
            raw_messages.extend(page_messages)
            loaded += len(page_messages)

        payload["messages"] = raw_messages
        return payload

    def _serialize_order(self, raw: dict[str, Any]) -> PostSaleOrderRef:
        order_items: list[PostSaleOrderItemRef] = []
        for order_item in raw.get("order_items") or []:
            if not isinstance(order_item, dict):
                continue
            item = order_item.get("item") if isinstance(order_item.get("item"), dict) else {}
            order_items.append(
                PostSaleOrderItemRef(
                    item_id=str(item.get("id")) if item.get("id") is not None else None,
                    title=item.get("title"),
                    quantity=self._safe_int(order_item.get("quantity")),
                    unit_price=self._safe_float(order_item.get("unit_price")),
                    currency_id=order_item.get("currency_id") or raw.get("currency_id"),
                    full_unit_price=self._safe_float(order_item.get("full_unit_price")),
                    variation_id=self._safe_int(item.get("variation_id")),
                    thumbnail=item.get("thumbnail"),
                )
            )

        shipping = raw.get("shipping") if isinstance(raw.get("shipping"), dict) else {}
        return PostSaleOrderRef(
            id=int(raw["id"]),
            pack_id=str(raw.get("pack_id")) if raw.get("pack_id") is not None else None,
            status=raw.get("status"),
            status_detail=raw.get("status_detail"),
            date_created=raw.get("date_created"),
            date_closed=raw.get("date_closed"),
            last_updated=raw.get("last_updated"),
            total_amount=self._safe_float(raw.get("total_amount")),
            paid_amount=self._safe_float(raw.get("paid_amount")),
            currency_id=raw.get("currency_id"),
            shipping_id=self._safe_int(shipping.get("id")),
            tags=[str(tag) for tag in raw.get("tags") or [] if tag is not None],
            items=order_items,
        )

    @staticmethod
    def _counterparty_from_messages(
        messages: list[PostSaleMessage],
        *,
        seller_id: int,
    ) -> tuple[int | None, str | None, str | None]:
        for message in messages:
            parties = []
            if message.from_user:
                parties.append(message.from_user)
            parties.extend(message.to_users)
            for party in parties:
                if party.user_id is None or party.user_id == seller_id:
                    continue
                return party.user_id, party.name or party.nickname, party.nickname or party.name
        return None, None, None

    async def get_conversation(
        self,
        account_key: str,
        pack_id: str,
        *,
        mark_as_read: bool = False,
    ) -> PostSaleConversationDetail:
        seller_id = await self._resolve_user_id(account_key)
        pack_payload, raw_orders = await self._load_pack_orders(
            account_key,
            pack_id=pack_id,
            seller_id=seller_id,
        )
        messages_payload = await self._load_messages_payload(
            account_key,
            pack_id=pack_id,
            seller_id=seller_id,
            mark_as_read=mark_as_read,
        )

        serialized_orders = [self._serialize_order(raw) for raw in raw_orders if raw.get("id") is not None]
        serialized_messages = sorted(
            [
                self._serialize_message(raw, seller_id)
                for raw in (messages_payload.get("messages") if isinstance(messages_payload.get("messages"), list) else [])
                if isinstance(raw, dict)
            ],
            key=self._message_sort_key,
        )

        buyer_user_id = None
        buyer_name = None
        buyer_nickname = None
        site_id = None
        shipping_id = None
        item_titles: list[str] = []
        order_ids: list[int] = []
        total_amount = 0.0
        currency_id = None
        pack_status = pack_payload.get("status") if isinstance(pack_payload, dict) else None
        pack_status_detail = pack_payload.get("status_detail") if isinstance(pack_payload, dict) else None

        for order in serialized_orders:
            order_ids.append(order.id)
            for item in order.items:
                if item.title:
                    item_titles.append(item.title)

            raw_order = next(
                (
                    entry
                    for entry in raw_orders
                    if isinstance(entry, dict) and self._safe_int(entry.get("id")) == order.id
                ),
                None,
            )
            buyer = raw_order.get("buyer") if isinstance(raw_order, dict) and isinstance(raw_order.get("buyer"), dict) else {}
            buyer_user_id = buyer_user_id or self._safe_int(buyer.get("id"))
            buyer_name = buyer_name or buyer.get("nickname")
            buyer_nickname = buyer_nickname or buyer.get("nickname")
            site_id = site_id or (raw_order.get("site_id") if isinstance(raw_order, dict) else None)

            shipping_id = order.shipping_id or shipping_id
            if order.total_amount is not None:
                total_amount += order.total_amount
            currency_id = currency_id or order.currency_id
            pack_status = pack_status or order.status
            pack_status_detail = pack_status_detail or order.status_detail

        counterparty_user_id, counterparty_name, counterparty_nickname = self._counterparty_from_messages(
            serialized_messages,
            seller_id=seller_id,
        )
        buyer_user_id = buyer_user_id or counterparty_user_id
        buyer_name = buyer_name or counterparty_name
        buyer_nickname = buyer_nickname or counterparty_nickname
        site_id = site_id or next((message.site_id for message in serialized_messages if message.site_id), None)

        conversation_status = (
            messages_payload.get("conversation_status")
            if isinstance(messages_payload.get("conversation_status"), dict)
            else {}
        )
        message_count = self._extract_message_count(messages_payload)
        can_reply, limitation = self._reply_capability(
            buyer_user_id=buyer_user_id,
            message_count=message_count,
            conversation_status=conversation_status.get("status"),
            conversation_substatus=conversation_status.get("substatus"),
        )

        item_titles = list(dict.fromkeys(title for title in item_titles if title))
        claim_ids = [
            claim_id
            for claim_id in (
                self._safe_int(entry) for entry in (conversation_status.get("claim_ids") or [])
            )
            if claim_id is not None
        ]
        unread_count = self._build_unread_map(
            await self._adapter.get_unread_messages(account_key)
        ).get(pack_id, 0)

        last_updated = pack_payload.get("last_updated") if isinstance(pack_payload, dict) else None
        if not last_updated and serialized_messages:
            last_updated = serialized_messages[-1].date_created or serialized_messages[-1].date_available
        if not last_updated and serialized_orders:
            last_updated = max(
                (order.last_updated or order.date_created or "" for order in serialized_orders),
                default="",
            )

        return PostSaleConversationDetail(
            pack_id=pack_id,
            buyer_user_id=buyer_user_id,
            buyer_name=buyer_name,
            buyer_nickname=buyer_nickname,
            primary_item_title=item_titles[0] if item_titles else None,
            item_titles=item_titles,
            order_ids=list(dict.fromkeys(order_ids)),
            date_created=pack_payload.get("date_created")
            or (serialized_orders[0].date_created if serialized_orders else None),
            last_updated=last_updated,
            unread_count=unread_count,
            message_count=message_count,
            conversation_status=conversation_status.get("status"),
            conversation_substatus=conversation_status.get("substatus"),
            pack_status=pack_status,
            pack_status_detail=pack_status_detail,
            seller_max_message_length=self._safe_int(messages_payload.get("seller_max_message_length")),
            buyer_max_message_length=self._safe_int(messages_payload.get("buyer_max_message_length")),
            can_reply=can_reply,
            reply_limitations=limitation,
            site_id=site_id,
            shipping_id=self._safe_int(conversation_status.get("shipping_id")) or shipping_id,
            total_amount=total_amount or None,
            currency_id=currency_id,
            seller_user_id=seller_id,
            messages=serialized_messages,
            orders=serialized_orders,
            claim_ids=claim_ids,
        )

    async def reply_to_conversation(
        self,
        account_key: str,
        pack_id: str,
        *,
        text: str,
    ) -> PostSaleMessageResult:
        detail = await self.get_conversation(account_key, pack_id, mark_as_read=False)
        if not detail.can_reply:
            raise BadRequestError(
                detail.reply_limitations or "La conversación post venta no admite respuestas por API.",
                details={
                    "pack_id": pack_id,
                    "conversation_status": detail.conversation_status,
                    "conversation_substatus": detail.conversation_substatus,
                },
            )
        if detail.buyer_user_id is None or detail.seller_user_id is None:
            raise BadRequestError("No se pudo identificar a las partes de la conversación para responder.")

        max_length = detail.seller_max_message_length or 350
        if len(text.strip()) > max_length:
            raise BadRequestError(
                f"El mensaje supera el máximo permitido por Mercado Libre para el vendedor ({max_length} caracteres)."
            )

        raw = await self._adapter.post_message(
            account_key,
            pack_id=pack_id,
            seller_id=detail.seller_user_id,
            buyer_user_id=detail.buyer_user_id,
            text=text.strip(),
        )
        raw_payload = raw if isinstance(raw, dict) else {"message": str(raw or "message sent")}
        return PostSaleMessageResult(raw=raw_payload)
