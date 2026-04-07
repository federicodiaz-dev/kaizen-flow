from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.adapters.market_research import MarketResearchAdapter
from app.agents.config import AgentSettings, get_agent_settings
from app.agents.listing_doctor_workflow import build_listing_doctor_graph
from app.core.account_store import AccountStore
from app.core.exceptions import NotFoundError
from app.schemas.listing_doctor import (
    ListingDoctorJobAccepted,
    ListingDoctorJobRequest,
    ListingDoctorJobStatus,
    ListingDoctorProgressStep,
    ListingDoctorTraceEntry,
)
from app.services.copywriter import CopywriterService
from app.services.items import ItemsService


STEP_BLUEPRINT = [
    ("listing_intake", "Cargando publicacion"),
    ("query_strategy", "Construyendo queries"),
    ("competitor_discovery", "Buscando competencia"),
    ("competitor_enrichment", "Enriqueciendo competidores"),
    ("benchmark_analysis", "Comparando benchmark"),
    ("opportunities", "Priorizando oportunidades"),
    ("strategy_synthesis", "Generando diagnostico"),
    ("copywriter_enhancement", "Preparando sugerencias IA"),
]
TRACE_LIMIT = 800
logger = logging.getLogger("kaizen-flow.listing-doctor")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ListingDoctorJobStore:
    def __init__(self, base_dir: Path, *, user_id: int) -> None:
        self._base_dir = Path(base_dir) / f"user_{user_id}"
        self._jobs_dir = self._base_dir / "jobs"
        self._logs_dir = self._base_dir / "logs"
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self.mark_orphaned_jobs_interrupted()

    def _job_path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"

    def _log_path(self, job_id: str) -> Path:
        return self._logs_dir / f"{job_id}.md"

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def default_steps(self) -> list[dict[str, Any]]:
        return [
            ListingDoctorProgressStep(key=key, label=label).model_dump(mode="json")
            for key, label in STEP_BLUEPRINT
        ]

    def create_job(
        self,
        *,
        job_id: str,
        account_key: str,
        site_id: str,
        payload: ListingDoctorJobRequest,
    ) -> dict[str, Any]:
        timestamp = _now_iso()
        record = {
            "job_id": job_id,
            "status": "queued",
            "created_at": timestamp,
            "updated_at": timestamp,
            "account_key": account_key,
            "site_id": site_id,
            "item_id": payload.item_id.strip().upper(),
            "include_copywriter": payload.include_copywriter,
            "competitor_limit": payload.competitor_limit,
            "search_depth": payload.search_depth,
            "error_message": None,
            "warnings": [],
            "steps": self.default_steps(),
            "trace": [],
            "log_file_path": str(self._log_path(job_id)),
            "result": None,
        }
        self._write_json(self._job_path(job_id), record)
        return record

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        if not path.exists():
            raise NotFoundError("Listing Doctor job not found.")
        payload = self._read_json(path, {})
        if not isinstance(payload, dict):
            raise NotFoundError("Listing Doctor job payload is invalid.")
        return payload

    def ensure_terminal_log(self, job_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        record = dict(payload or self.get_job(job_id))
        record.setdefault("log_file_path", str(self._log_path(job_id)))
        result = record.get("result")
        if isinstance(result, dict):
            result.setdefault("execution_trace", list(record.get("trace", [])))
            result.setdefault("log_file_path", record.get("log_file_path"))
            record["result"] = result
        if record.get("status") in {"completed", "partial", "failed", "interrupted"}:
            self.save_job(job_id, record)
            self.write_execution_log(job_id, record)
        return record

    def save_job(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload["updated_at"] = _now_iso()
        payload.setdefault("log_file_path", str(self._log_path(job_id)))
        self._write_json(self._job_path(job_id), payload)
        return payload

    def update_status(
        self,
        job_id: str,
        *,
        status: str,
        error_message: str | None = None,
        result: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = self.get_job(job_id)
        payload["status"] = status
        payload["error_message"] = error_message
        if warnings is not None:
            payload["warnings"] = warnings
        if result is not None:
            payload["result"] = {
                **result,
                "execution_trace": list(payload.get("trace", [])),
                "log_file_path": payload.get("log_file_path"),
            }
        payload = self.save_job(job_id, payload)
        if status in {"completed", "partial", "failed", "interrupted"}:
            self.write_execution_log(job_id, payload)
        return payload

    def append_trace(
        self,
        job_id: str,
        *,
        agent: str,
        node: str,
        phase: str,
        message: str,
        details: Any | None = None,
    ) -> dict[str, Any]:
        payload = self.get_job(job_id)
        trace = payload.get("trace") if isinstance(payload.get("trace"), list) else []
        entry = ListingDoctorTraceEntry(
            sequence=len(trace) + 1,
            timestamp=_now_iso(),
            agent=agent,
            node=node,
            phase=phase,
            message=message,
            details=details,
        ).model_dump(mode="json")
        trace.append(entry)
        payload["trace"] = trace[-TRACE_LIMIT:]
        return self.save_job(job_id, payload)

    def write_execution_log(self, job_id: str, payload: dict[str, Any] | None = None) -> Path:
        job = payload or self.get_job(job_id)
        result = job.get("result") if isinstance(job.get("result"), dict) else None
        warnings = job.get("warnings") if isinstance(job.get("warnings"), list) else []
        steps = job.get("steps") if isinstance(job.get("steps"), list) else []
        trace = job.get("trace") if isinstance(job.get("trace"), list) else []
        log_path = self._log_path(job_id)

        lines: list[str] = [
            f"# Listing Doctor Execution Log - {job_id}",
            "",
            "## Metadata",
            f"- status: {job.get('status')}",
            f"- created_at: {job.get('created_at')}",
            f"- updated_at: {job.get('updated_at')}",
            f"- account_key: {job.get('account_key')}",
            f"- site_id: {job.get('site_id')}",
            f"- item_id: {job.get('item_id')}",
            f"- include_copywriter: {job.get('include_copywriter')}",
            f"- competitor_limit: {job.get('competitor_limit')}",
            f"- search_depth: {job.get('search_depth')}",
            f"- log_file_path: {log_path}",
            "",
        ]

        if job.get("error_message"):
            lines.extend(
                [
                    "## Error",
                    str(job.get("error_message")),
                    "",
                ]
            )

        lines.extend(["## Steps", ""])
        for step in steps:
            if not isinstance(step, dict):
                continue
            lines.extend(
                [
                    f"### {step.get('label') or step.get('key')}",
                    f"- key: {step.get('key')}",
                    f"- status: {step.get('status')}",
                    f"- message: {step.get('message')}",
                    f"- started_at: {step.get('started_at')}",
                    f"- completed_at: {step.get('completed_at')}",
                    "",
                ]
            )

        lines.extend(["## Warnings", ""])
        if warnings:
            lines.extend([f"- {warning}" for warning in warnings if warning])
        else:
            lines.append("- none")
        lines.append("")

        lines.extend(["## Trace", ""])
        if not trace:
            lines.extend(["No trace events were recorded.", ""])
        else:
            for entry in trace:
                if not isinstance(entry, dict):
                    continue
                lines.extend(
                    [
                        f"### #{entry.get('sequence')} {entry.get('agent')} / {entry.get('node')} / {entry.get('phase')}",
                        f"- timestamp: {entry.get('timestamp')}",
                        f"- message: {entry.get('message')}",
                    ]
                )
                details = entry.get("details")
                if details is not None:
                    lines.extend(
                        [
                            "",
                            "```json",
                            json.dumps(details, ensure_ascii=False, indent=2),
                            "```",
                        ]
                    )
                lines.append("")

        if result is not None:
            lines.extend(
                [
                    "## Final Result",
                    "",
                    "```json",
                    json.dumps(result, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

        log_path.write_text("\n".join(lines), encoding="utf-8")
        return log_path

    def append_warning(self, job_id: str, message: str) -> dict[str, Any]:
        payload = self.get_job(job_id)
        warnings = list(payload.get("warnings", []))
        if message not in warnings:
            warnings.append(message)
        payload["warnings"] = warnings
        return self.save_job(job_id, payload)

    def update_step(self, job_id: str, *, step_key: str, status: str, message: str | None = None) -> dict[str, Any]:
        payload = self.get_job(job_id)
        steps = payload.get("steps") if isinstance(payload.get("steps"), list) else self.default_steps()
        now = _now_iso()
        updated_steps: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            current = dict(step)
            if current.get("key") == step_key:
                current["status"] = status
                if message is not None:
                    current["message"] = message
                if status == "running" and not current.get("started_at"):
                    current["started_at"] = now
                if status in {"completed", "skipped", "failed"}:
                    current["completed_at"] = now
            updated_steps.append(current)
        payload["steps"] = updated_steps
        if payload.get("status") == "queued" and status == "running":
            payload["status"] = "running"
            payload["error_message"] = None
        return self.save_job(job_id, payload)

    def mark_orphaned_jobs_interrupted(self) -> None:
        for path in self._jobs_dir.glob("*.json"):
            payload = self._read_json(path, {})
            if not isinstance(payload, dict):
                continue
            if payload.get("status") not in {"queued", "running"}:
                continue
            payload["status"] = "interrupted"
            payload["error_message"] = "El servidor se reinicio durante la ejecucion del analisis."
            steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
            for step in steps:
                if isinstance(step, dict) and step.get("status") == "running":
                    step["status"] = "failed"
                    step["completed_at"] = _now_iso()
                    step["message"] = "La ejecucion fue interrumpida por reinicio del servicio."
            payload["steps"] = steps
            trace = payload.get("trace") if isinstance(payload.get("trace"), list) else []
            trace.append(
                ListingDoctorTraceEntry(
                    sequence=len(trace) + 1,
                    timestamp=_now_iso(),
                    agent="service",
                    node="job",
                    phase="failed",
                    message="El servidor se reinicio durante la ejecucion del analisis.",
                    details={"reason": "service_restart"},
                ).model_dump(mode="json")
            )
            payload["trace"] = trace[-TRACE_LIMIT:]
            payload["log_file_path"] = str(self._log_path(str(payload.get("job_id") or path.stem)))
            self._write_json(path, payload)
            self.write_execution_log(str(payload.get("job_id") or path.stem), payload)


class ListingDoctorService:
    def __init__(
        self,
        *,
        user_id: int,
        account_store: AccountStore,
        items_service: ItemsService,
        market_research: MarketResearchAdapter,
        copywriter_service: CopywriterService,
        agent_settings: AgentSettings | None = None,
    ) -> None:
        self._user_id = user_id
        self._account_store = account_store
        self._items_service = items_service
        self._market_research = market_research
        self._copywriter_service = copywriter_service
        self._agent_settings = agent_settings or get_agent_settings()
        self._job_store = ListingDoctorJobStore(
            self._agent_settings.memory_dir.parent / "listing_doctor",
            user_id=user_id,
        )
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._graph = None
        self._llm = None
        self._ready_lock = asyncio.Lock()

    async def aclose(self) -> None:
        tasks = list(self._tasks.items())
        self._tasks.clear()
        for job_id, task in tasks:
            if not task.done():
                task.cancel()
                self._job_store.update_status(
                    job_id,
                    status="interrupted",
                    error_message="El analisis fue interrumpido por apagado del servicio.",
                )
        if tasks:
            await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)

    async def create_job(
        self,
        *,
        account_key: str,
        payload: ListingDoctorJobRequest,
    ) -> ListingDoctorJobAccepted:
        site_id = (payload.site_id or self._agent_settings.default_site_id).strip().upper()
        job_id = self._generate_job_id()
        record = self._job_store.create_job(
            job_id=job_id,
            account_key=account_key,
            site_id=site_id,
            payload=payload,
        )
        task = asyncio.create_task(self._run_job(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))
        return ListingDoctorJobAccepted.model_validate(record)

    def get_job(self, job_id: str) -> ListingDoctorJobStatus:
        payload = self._job_store.get_job(job_id)
        if payload.get("status") in {"queued", "running"} and job_id not in self._tasks:
            payload = self._job_store.update_status(
                job_id,
                status="interrupted",
                error_message="El job quedo sin proceso en memoria y fue marcado como interrumpido.",
            )
        payload = self._job_store.ensure_terminal_log(job_id, payload)
        return ListingDoctorJobStatus.model_validate(payload)

    async def _run_job(self, job_id: str) -> None:
        job = self._job_store.get_job(job_id)
        progress_hook = self._build_progress_hook(job_id)
        trace_hook = self._build_trace_hook(job_id)
        try:
            await self._ensure_ready()
            self._job_store.update_status(job_id, status="running", error_message=None)
            self._job_store.append_trace(
                job_id,
                agent="service",
                node="job",
                phase="started",
                message="Inicio del job de Listing Doctor.",
                details={
                    "account_key": str(job["account_key"]),
                    "site_id": str(job["site_id"]),
                    "item_id": str(job["item_id"]),
                    "include_copywriter": bool(job.get("include_copywriter")),
                    "competitor_limit": int(job.get("competitor_limit") or 8),
                    "search_depth": int(job.get("search_depth") or 2),
                },
            )
            state = {
                "job_id": job_id,
                "account_key": str(job["account_key"]),
                "site_id": str(job["site_id"]),
                "item_id": str(job["item_id"]),
                "include_copywriter": bool(job.get("include_copywriter")),
                "competitor_limit": int(job.get("competitor_limit") or 8),
                "search_depth": int(job.get("search_depth") or 2),
                "progress_hook": progress_hook,
                "trace_hook": trace_hook,
                "warnings": list(job.get("warnings", [])),
                "scores": {},
                "findings": {},
                "actions": [],
                "evidence": {
                    "factual_points": [],
                    "proxy_points": [],
                    "uncertainties": [],
                },
                "ai_suggestions": {},
                "market_summary": {},
            }
            result = await self._graph.ainvoke(state)
            result_payload = result.get("result", {})
            warnings = list(result_payload.get("warnings", [])) or list(result.get("warnings", []))
            is_partial = bool(result.get("partial_analysis")) or len(result_payload.get("competitor_snapshot", [])) < 3
            final_status = "partial" if is_partial else "completed"
            self._job_store.append_trace(
                job_id,
                agent="service",
                node="job",
                phase="completed",
                message="Job finalizado.",
                details={
                    "final_status": final_status,
                    "warnings_count": len(warnings),
                    "competitors": len(result_payload.get("competitor_snapshot", [])),
                    "scores": result_payload.get("scores", {}),
                },
            )
            self._job_store.update_status(
                job_id,
                status=final_status,
                error_message=None,
                result=result_payload,
                warnings=warnings,
            )
        except asyncio.CancelledError:
            self._job_store.append_trace(
                job_id,
                agent="service",
                node="job",
                phase="failed",
                message="El job fue cancelado antes de terminar.",
                details={"reason": "cancelled"},
            )
            self._job_store.update_status(
                job_id,
                status="interrupted",
                error_message="El job fue cancelado antes de terminar.",
            )
            raise
        except Exception as exc:
            self._job_store.append_trace(
                job_id,
                agent="service",
                node="job",
                phase="failed",
                message="El job fallo con una excepcion no controlada.",
                details={"error": str(exc), "exception_type": exc.__class__.__name__},
            )
            self._job_store.update_status(
                job_id,
                status="failed",
                error_message=str(exc),
            )

    async def _ensure_ready(self) -> None:
        if self._graph is not None:
            return
        async with self._ready_lock:
            if self._graph is not None:
                return
            worker_llm = None
            try:
                from app.agents.llm import build_chat_models

                _, worker_llm = build_chat_models(self._agent_settings)
            except Exception:
                worker_llm = None
            self._llm = worker_llm
            self._graph = build_listing_doctor_graph(
                llm=self._llm,
                market_research=self._market_research,
                items_service=self._items_service,
                copywriter_service=self._copywriter_service,
            )

    def _generate_job_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"listing-doctor-{timestamp}-{uuid4().hex[:6]}"

    def _build_progress_hook(self, job_id: str):
        async def progress_hook(step_key: str, status: str, message: str | None = None) -> None:
            self._job_store.update_step(job_id, step_key=step_key, status=status, message=message)

        return progress_hook

    def _build_trace_hook(self, job_id: str):
        async def trace_hook(agent: str, node: str, phase: str, message: str, details: Any | None = None) -> None:
            self._job_store.append_trace(
                job_id,
                agent=agent,
                node=node,
                phase=phase,
                message=message,
                details=details,
            )
            logger.info(
                "listing_doctor_trace job=%s agent=%s node=%s phase=%s message=%s details=%s",
                job_id,
                agent,
                node,
                phase,
                message,
                details,
            )

        return trace_hook
