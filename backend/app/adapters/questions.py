from __future__ import annotations

from typing import Any

from app.clients.mercadolibre import MercadoLibreClient
from app.core.exceptions import BadRequestError, MercadoLibreAPIError


class QuestionsAdapter:
    def __init__(self, client: MercadoLibreClient) -> None:
        self._client = client

    async def list_questions(
        self,
        account_key: str,
        *,
        seller_id: int,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        params = {
            "seller_id": seller_id,
            "limit": limit,
            "offset": offset,
            "api_version": 4,
        }
        data = await self._client.request(account_key, "GET", "/questions/search", params=params)
        return data if isinstance(data, dict) else {}

    async def get_question(self, account_key: str, question_id: int) -> dict[str, Any]:
        data = await self._client.request(
            account_key,
            "GET",
            f"/questions/{question_id}",
            params={"api_version": 4},
        )
        return data if isinstance(data, dict) else {}

    async def answer_question(self, account_key: str, question_id: int, text: str) -> dict[str, Any]:
        payload = {"question_id": question_id, "text": text}
        try:
            data = await self._client.request(
                account_key,
                "POST",
                "/answers",
                json_body=payload,
                headers={"Content-Type": "application/json"},
            )
        except MercadoLibreAPIError as exc:
            if exc.status_code == 405:
                try:
                    data = await self._client.request(
                        account_key,
                        "POST",
                        "/answers/",
                        json_body=payload,
                        headers={"Content-Type": "application/json"},
                    )
                except MercadoLibreAPIError as trailing_exc:
                    if trailing_exc.status_code == 405:
                        raise BadRequestError(
                            "Mercado Libre rechazo la respuesta. La documentacion oficial mantiene POST /answers, asi que el problema suele ser la cuenta activa, el estado de la pregunta o una restriccion puntual del caso.",
                            details={
                                "question_id": question_id,
                                "attempted_paths": ["/answers", "/answers/"],
                                "mercadolibre_response": trailing_exc.details,
                            },
                        ) from trailing_exc
                    raise
            else:
                raise
        return data if isinstance(data, dict) else {}
