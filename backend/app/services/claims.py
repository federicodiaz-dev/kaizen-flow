from __future__ import annotations

import asyncio
from typing import Any

from app.adapters.claims import ClaimsAdapter
from app.clients.mercadolibre import MercadoLibreClient
from app.core.account_store import AccountStore
from app.core.exceptions import AppError, BadRequestError
from app.schemas.claims import (
    ClaimAction,
    ClaimDetail,
    ClaimExpectedResolution,
    ClaimListResponse,
    ClaimMessage,
    ClaimMessageResult,
    ClaimPlayer,
    ClaimReasonDetail,
    ClaimReputationImpact,
    ClaimStatusHistoryEntry,
    ClaimSummary,
)


def _flatten_actions(players: list[dict[str, Any]]) -> list[ClaimAction]:
    actions: list[ClaimAction] = []
    for player in players:
        for raw_action in player.get("available_actions") or []:
            actions.append(
                ClaimAction(
                    action=str(raw_action.get("action") or "unknown"),
                    due_date=raw_action.get("due_date"),
                    mandatory=raw_action.get("mandatory"),
                    player_role=player.get("role"),
                    player_type=player.get("type"),
                    user_id=player.get("user_id"),
                ),
            )
    return actions


def _serialize_players(players: list[dict[str, Any]]) -> list[ClaimPlayer]:
    serialized: list[ClaimPlayer] = []
    for player in players:
        serialized.append(
            ClaimPlayer(
                role=str(player.get("role") or "unknown"),
                type=player.get("type"),
                user_id=player.get("user_id"),
                available_actions=_flatten_actions([player]),
            )
        )
    return serialized


class ClaimsService:
    def __init__(
        self,
        account_store: AccountStore,
        client: MercadoLibreClient,
        claims_adapter: ClaimsAdapter,
    ) -> None:
        self._account_store = account_store
        self._client = client
        self._claims_adapter = claims_adapter

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
    def _allowed_message_roles(raw_claim: dict[str, Any], account_user_id: int) -> list[str]:
        action_to_role = {
            "send_message_to_complainant": "complainant",
            "send_message_to_respondent": "respondent",
            "send_message_to_mediator": "mediator",
        }
        for player in raw_claim.get("players") or []:
            user_id = player.get("user_id")
            if user_id is None or int(user_id) != account_user_id:
                continue

            roles: list[str] = []
            for raw_action in player.get("available_actions") or []:
                role = action_to_role.get(str(raw_action.get("action") or ""))
                if role and role not in roles:
                    roles.append(role)
            return roles
        return []

    @classmethod
    def _message_capability(
        cls,
        raw_claim: dict[str, Any],
        account_user_id: int,
    ) -> tuple[bool, str | None, list[str]]:
        stage = str(raw_claim.get("stage") or "")
        status = str(raw_claim.get("status") or "")
        allowed_roles = cls._allowed_message_roles(raw_claim, account_user_id)
        if status.lower() == "closed":
            return False, "El reclamo esta cerrado y la API ya no permite enviar mensajes.", allowed_roles
        if not allowed_roles:
            return (
                False,
                "La cuenta activa no tiene una accion send_message_to_* disponible en este reclamo. Mercado Libre exige validar available_actions antes de enviar mensajes.",
                allowed_roles,
            )
        if stage == "dispute" and "mediator" in allowed_roles:
            return (
                True,
                "La mensajeria esta habilitada y en esta etapa debe dirigirse al mediador cuando Mercado Libre ya intervino.",
                allowed_roles,
            )
        return True, None, allowed_roles

    @staticmethod
    def _serialize_claim(raw: dict[str, Any]) -> ClaimSummary:
        players = raw.get("players") or []
        return ClaimSummary(
            id=int(raw["id"]),
            type=raw.get("type"),
            stage=raw.get("stage"),
            status=raw.get("status"),
            reason_id=raw.get("reason_id"),
            resource=raw.get("resource"),
            resource_id=raw.get("resource_id"),
            parent_id=raw.get("parent_id"),
            date_created=raw.get("date_created"),
            last_updated=raw.get("last_updated"),
            players=_serialize_players(players),
            available_actions=_flatten_actions(players),
        )

    @staticmethod
    def _is_optional_resource_error(exc: AppError) -> bool:
        return exc.status_code in {400, 404}

    async def _optional_resource(self, loader, default):
        try:
            return await loader()
        except AppError as exc:
            if self._is_optional_resource_error(exc):
                return default
            raise

    async def list_claims(
        self,
        account_key: str,
        *,
        limit: int,
        offset: int,
        stage: str | None,
        status: str | None,
    ) -> ClaimListResponse:
        user_id = await self._resolve_user_id(account_key)
        request_window = min(100, max(limit + offset, limit))
        payloads = await asyncio.gather(
            self._claims_adapter.list_claims(
                account_key,
                limit=request_window,
                offset=0,
                player_user_id=user_id,
                player_role="complainant",
                stage=stage,
                status=status,
            ),
            self._claims_adapter.list_claims(
                account_key,
                limit=request_window,
                offset=0,
                player_user_id=user_id,
                player_role="respondent",
                stage=stage,
                status=status,
            ),
        )

        raw_by_id: dict[int, dict[str, Any]] = {}
        total = 0
        for payload in payloads:
            raw_items = payload.get("data") if isinstance(payload.get("data"), list) else []
            total += int(payload.get("paging", {}).get("total") or len(raw_items))
            for raw in raw_items:
                claim_id = raw.get("id")
                if claim_id is None:
                    continue
                raw_by_id[int(claim_id)] = raw

        def _sort_key(raw: dict[str, Any]) -> tuple[str, int]:
            return (str(raw.get("last_updated") or raw.get("date_created") or ""), int(raw.get("id") or 0))

        merged_raw_items = sorted(raw_by_id.values(), key=_sort_key, reverse=True)
        paged_raw_items = merged_raw_items[offset : offset + limit]
        items = [self._serialize_claim(raw) for raw in paged_raw_items]
        return ClaimListResponse(items=items, total=total, offset=offset, limit=limit)

    async def get_claim(self, account_key: str, claim_id: int) -> ClaimDetail:
        raw_claim = await self._claims_adapter.get_claim(account_key, claim_id)
        account_user_id = await self._resolve_user_id(account_key)
        summary = self._serialize_claim(raw_claim)
        messages = await self._optional_resource(
            lambda: self._claims_adapter.get_messages(account_key, claim_id),
            [],
        )
        history = await self._optional_resource(
            lambda: self._claims_adapter.get_status_history(account_key, claim_id),
            [],
        )
        expected_resolutions = await self._optional_resource(
            lambda: self._claims_adapter.get_expected_resolutions(account_key, claim_id),
            [],
        )
        reputation = await self._optional_resource(
            lambda: self._claims_adapter.get_affects_reputation(account_key, claim_id),
            {},
        )
        reason_detail = None
        if raw_claim.get("reason_id"):
            raw_reason = await self._optional_resource(
                lambda: self._claims_adapter.get_reason_detail(account_key, str(raw_claim["reason_id"])),
                {},
            )
            if raw_reason:
                reason_detail = ClaimReasonDetail(
                    id=raw_reason.get("id"),
                    name=raw_reason.get("name"),
                    detail=raw_reason.get("detail"),
                    flow=raw_reason.get("flow"),
                    parent_id=raw_reason.get("parent_id"),
                    status=raw_reason.get("status"),
                )

        can_message, limitation, allowed_receiver_roles = self._message_capability(raw_claim, account_user_id)
        return ClaimDetail(
            **summary.model_dump(),
            resolution=raw_claim.get("resolution"),
            labels=raw_claim.get("labels") or [],
            coverages=raw_claim.get("coverages") or [],
            site_id=raw_claim.get("site_id"),
            messages=[
                ClaimMessage(
                    sender_role=message.get("sender_role"),
                    receiver_role=message.get("receiver_role"),
                    stage=message.get("stage"),
                    date_created=message.get("date_created"),
                    message=message.get("message"),
                    attachments=message.get("attachments") or [],
                )
                for message in messages
            ],
            status_history=[
                ClaimStatusHistoryEntry(
                    stage=entry.get("stage"),
                    status=entry.get("status"),
                    date=entry.get("date"),
                    change_by=entry.get("change_by"),
                )
                for entry in history
            ],
            expected_resolutions=[
                ClaimExpectedResolution(
                    player_role=entry.get("player_role"),
                    user_id=entry.get("user_id"),
                    expected_resolution=entry.get("expected_resolution"),
                    status=entry.get("status"),
                    date_created=entry.get("date_created"),
                    last_updated=entry.get("last_updated"),
                )
                for entry in expected_resolutions
            ],
            reputation_impact=ClaimReputationImpact(
                affects_reputation=reputation.get("affects_reputation"),
                has_incentive=reputation.get("has_incentive"),
                due_date=reputation.get("due_date"),
            )
            if reputation
            else None,
            reason_detail=reason_detail,
            can_message=can_message,
            message_limitations=limitation,
            allowed_receiver_roles=allowed_receiver_roles,
        )

    async def get_messages(self, account_key: str, claim_id: int) -> list[ClaimMessage]:
        raw_messages = await self._claims_adapter.get_messages(account_key, claim_id)
        return [
            ClaimMessage(
                sender_role=message.get("sender_role"),
                receiver_role=message.get("receiver_role"),
                stage=message.get("stage"),
                date_created=message.get("date_created"),
                message=message.get("message"),
                attachments=message.get("attachments") or [],
            )
            for message in raw_messages
        ]

    async def get_available_actions(self, account_key: str, claim_id: int) -> list[ClaimAction]:
        claim = await self._claims_adapter.get_claim(account_key, claim_id)
        return _flatten_actions(claim.get("players") or [])

    async def post_message(
        self,
        account_key: str,
        claim_id: int,
        *,
        message: str,
        receiver_role: str | None = None,
    ) -> ClaimMessageResult:
        claim_detail = await self.get_claim(account_key, claim_id)
        if not claim_detail.can_message:
            raise BadRequestError(
                claim_detail.message_limitations
                or "Accion no disponible por limitacion actual de la API o por el estado del reclamo.",
                details={
                    "claim_status": claim_detail.status,
                    "claim_stage": claim_detail.stage,
                    "allowed_receiver_roles": claim_detail.allowed_receiver_roles,
                },
            )

        effective_receiver = receiver_role or claim_detail.allowed_receiver_roles[0]
        if effective_receiver not in claim_detail.allowed_receiver_roles:
            raise BadRequestError(
                "El destinatario elegido no esta habilitado por Mercado Libre para este reclamo.",
                details={
                    "receiver_role": effective_receiver,
                    "allowed_receiver_roles": claim_detail.allowed_receiver_roles,
                },
            )

        raw = await self._claims_adapter.post_message(
            account_key,
            claim_id,
            receiver_role=effective_receiver,
            message=message,
        )
        raw_payload = raw if isinstance(raw, dict) else {"message": str(raw or "status 201 created")}
        return ClaimMessageResult(
            execution_response=raw_payload.get("execution_response"),
            new_state=raw_payload.get("new_state"),
            raw=raw_payload,
        )
