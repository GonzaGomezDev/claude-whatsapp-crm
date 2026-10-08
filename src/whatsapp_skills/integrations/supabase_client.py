"""Acceso a Supabase.

Usamos el cliente sync de `supabase` envuelto en `asyncio.to_thread`. Es a
propósito: el cliente async existe pero cambió de nombre entre versiones, y una
llamada sync dentro de un `to_thread` funciona igual en todas. El costo es un
thread del pool por query, que para este volumen es irrelevante.

Todo el acceso a datos vive acá. Las tools de las skills no arman queries: le
piden cosas a esta clase. Así, cuando cambiás de Supabase a Postgres pelado o a
otro backend, tocás un archivo y las skills siguen andando.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from typing import Any

from supabase import Client, create_client


class Database:
    def __init__(self, url: str, service_role_key: str) -> None:
        self._client: Client = create_client(url, service_role_key)

    # ── Helper ──────────────────────────────────────────────────────────────

    async def _run(self, fn: Any) -> Any:
        """Ejecuta una query sync en el threadpool y devuelve `.data`."""
        response = await asyncio.to_thread(fn)
        return getattr(response, "data", response)

    # ── Clientes ────────────────────────────────────────────────────────────

    async def find_client_by_phone(self, phone: str) -> dict[str, Any] | None:
        rows = await self._run(
            lambda: self._client.table("clients")
            .select("*")
            .eq("phone", phone)
            .limit(1)
            .execute()
        )
        return rows[0] if rows else None

    async def find_clients_by_name(self, name: str, limit: int = 5) -> list[dict[str, Any]]:
        return await self._run(
            lambda: self._client.table("clients")
            .select("*")
            .ilike("name", f"%{name}%")
            .limit(limit)
            .execute()
        )

    async def create_client_row(
        self,
        *,
        phone: str,
        name: str | None = None,
        company: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "phone": phone,
            "name": name,
            "company": company,
            "metadata": metadata or {},
        }
        # upsert sobre phone: si dos mensajes del mismo número entran a la vez,
        # el segundo no explota con una violación de unique.
        rows = await self._run(
            lambda: self._client.table("clients")
            .upsert(payload, on_conflict="phone")
            .execute()
        )
        return rows[0]

    async def update_client_row(self, client_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        rows = await self._run(
            lambda: self._client.table("clients")
            .update(patch)
            .eq("id", client_id)
            .execute()
        )
        if not rows:
            raise LookupError(f"No existe el cliente {client_id}.")
        return rows[0]

    async def set_claude_session(self, client_id: str, session_id: str) -> None:
        await self._run(
            lambda: self._client.table("clients")
            .update({"claude_session_id": session_id})
            .eq("id", client_id)
            .execute()
        )

    # ── Mensajes ────────────────────────────────────────────────────────────

    async def record_message(
        self,
        *,
        client_id: str | None,
        direction: str,
        body: str,
        twilio_sid: str | None = None,
        metadata: dict[str, Any] | None = None,
        phone: str | None = None,
    ) -> dict[str, Any] | None:
        """Devuelve None si el twilio_sid ya existía (reintento de Twilio)."""
        payload = {
            "client_id": client_id,
            "phone": phone,
            "direction": direction,
            "body": body,
            "twilio_sid": twilio_sid,
            "metadata": metadata or {},
        }
        try:
            rows = await self._run(
                lambda: self._client.table("messages").insert(payload).execute()
            )
        except Exception as exc:  # noqa: BLE001
            # 23505 = unique_violation. Es el camino feliz de la idempotencia:
            # Twilio reintentó y este mensaje ya se procesó.
            if "23505" in str(exc) or "duplicate key" in str(exc).lower():
                return None
            raise
        return rows[0] if rows else None

    async def attach_message_client(self, message_id: str, client_id: str) -> None:
        """Asocia un mensaje entrante a su cliente.

        El webhook graba el entrante ANTES de saber de quién es (necesita el
        insert temprano para la idempotencia por twilio_sid). Sin este backfill
        el mensaje queda con client_id NULL y `recent_messages` no lo devuelve
        nunca: el modelo termina viendo sólo sus propias respuestas.
        """
        await self._run(
            lambda: self._client.table("messages")
            .update({"client_id": client_id})
            .eq("id", message_id)
            .is_("client_id", "null")
            .execute()
        )

    async def recent_messages(self, client_id: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self._run(
            lambda: self._client.table("messages")
            .select("direction, body, created_at")
            .eq("client_id", client_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(reversed(rows))  # cronológico para armar el historial

    # ── Conversaciones (CRM) ────────────────────────────────────────────────

    async def touch_conversation(self, phone: str) -> dict[str, Any]:
        """Marca actividad y devuelve la conversación (status, handoff_note).

        Upsert: la primera vez que escribe un número, la fila nace en 'bot'.
        """
        rows = await self._run(
            lambda: self._client.table("conversations")
            .upsert(
                {"phone": phone, "last_message_at": datetime.now(UTC).isoformat()},
                on_conflict="phone",
            )
            .execute()
        )
        return rows[0]

    async def get_conversation(self, phone: str) -> dict[str, Any] | None:
        rows = await self._run(
            lambda: self._client.table("conversations")
            .select("*")
            .eq("phone", phone)
            .limit(1)
            .execute()
        )
        return rows[0] if rows else None

    async def set_conversation_status(
        self,
        phone: str,
        status: str,
        *,
        only_from: str | None = None,
        **fields: Any,
    ) -> dict[str, Any] | None:
        """Cambia el estado. Con `only_from`, sólo si estaba en ese estado.

        `fields` va tal cual al update (handoff_note, assigned_to): pasar
        `assigned_to=None` lo limpia. Devuelve la fila actualizada, o None si no
        había nada que cambiar.
        """

        def query() -> Any:
            q = (
                self._client.table("conversations")
                .update({"status": status, **fields})
                .eq("phone", phone)
            )
            if only_from:
                q = q.eq("status", only_from)
            return q.execute()

        rows = await self._run(query)
        return rows[0] if rows else None

    async def assign_conversation(self, phone: str, user_id: str | None) -> dict[str, Any] | None:
        rows = await self._run(
            lambda: self._client.table("conversations")
            .update({"assigned_to": user_id})
            .eq("phone", phone)
            .execute()
        )
        return rows[0] if rows else None

    # ── Operadores ──────────────────────────────────────────────────────────

    async def operator_for_token(self, access_token: str) -> dict[str, Any] | None:
        """El operador activo dueño del token (user_id, role, name), o None."""
        try:
            response = await asyncio.to_thread(self._client.auth.get_user, access_token)
        except Exception:  # noqa: BLE001
            return None  # token vencido o inválido
        user = getattr(response, "user", None)
        if user is None:
            return None
        operator = await self.get_operator(user.id)
        return operator if operator and operator.get("active") else None

    async def get_operator(self, user_id: str) -> dict[str, Any] | None:
        rows = await self._run(
            lambda: self._client.table("operators")
            .select("user_id, name, email, role, active")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return rows[0] if rows else None

    async def create_operator(
        self, email: str, *, name: str | None = None, role: str = "agent"
    ) -> tuple[str, str | None]:
        """Crea el usuario de Auth (si no existe) y lo da de alta como operador.

        Devuelve (user_id, contraseña generada). La contraseña es None si el
        usuario ya existía en Auth: se mantiene la suya.
        """
        admin = self._client.auth.admin
        user_id = await asyncio.to_thread(_find_auth_user, admin, email)
        password = None
        if user_id is None:
            password = secrets.token_urlsafe(12)
            created = await asyncio.to_thread(
                admin.create_user,
                {"email": email, "password": password, "email_confirm": True},
            )
            user_id = created.user.id

        await self._run(
            lambda: self._client.table("operators")
            .upsert(
                {"user_id": user_id, "email": email, "name": name, "role": role, "active": True},
                on_conflict="user_id",
            )
            .execute()
        )
        return user_id, password

    # ── Ficha del cliente (CRM) ─────────────────────────────────────────────

    async def client_summary_input(self, client_id: str) -> dict[str, Any] | None:
        """Lo que lee Claude para resumir un cliente: datos, últimos 200 mensajes,
        tickets y escalados."""
        rows = await self._run(
            lambda: self._client.table("clients").select("*").eq("id", client_id).limit(1).execute()
        )
        if not rows:
            return None
        client = rows[0]
        messages, tickets, escalations = await asyncio.gather(
            self._run(
                lambda: self._client.table("messages")
                .select("direction, body, created_at, metadata")
                .eq("phone", client["phone"])
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            ),
            self._run(
                lambda: self._client.table("tickets")
                .select("ref, type, status, subject, metadata, created_at")
                .eq("client_id", client_id)
                .order("created_at")
                .execute()
            ),
            self._run(
                lambda: self._client.table("escalations")
                .select("reason, summary, status, created_at")
                .eq("client_id", client_id)
                .order("created_at")
                .execute()
            ),
        )
        return {
            "client": client,
            "messages": list(reversed(messages)),
            "tickets": tickets,
            "escalations": escalations,
        }

    async def save_client_summary(self, client_id: str, summary: str) -> None:
        await self._run(
            lambda: self._client.table("clients")
            .update({"ai_summary": summary, "ai_summary_at": datetime.now(UTC).isoformat()})
            .eq("id", client_id)
            .execute()
        )

    # ── Tickets ─────────────────────────────────────────────────────────────

    async def create_ticket_row(
        self,
        *,
        client_id: str,
        ticket_type: str,
        subject: str | None,
        priority: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rows = await self._run(
            lambda: self._client.table("tickets")
            .insert(
                {
                    "client_id": client_id,
                    "type": ticket_type,
                    "subject": subject,
                    "priority": priority,
                    "metadata": metadata or {},
                }
            )
            .execute()
        )
        return rows[0]

    async def get_ticket_by_ref(self, ticket_ref: int) -> dict[str, Any] | None:
        rows = await self._run(
            lambda: self._client.table("tickets")
            .select("*, clients(id, phone, name, company)")
            .eq("ref", ticket_ref)
            .limit(1)
            .execute()
        )
        return rows[0] if rows else None

    async def update_ticket_row(
        self,
        ticket_ref: int,
        patch: dict[str, Any],
        metadata_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """`metadata_patch` se MEZCLA con lo que ya había.

        Mandar metadata dentro de `patch` reemplaza la columna jsonb entera y se
        lleva puesto el `details` que había guardado create_ticket — que es
        justo el contexto que el equipo humano necesita para atender el ticket.
        """
        if metadata_patch:
            actual = await self.get_ticket_by_ref(ticket_ref)
            if actual is None:
                raise LookupError(f"No existe el ticket {ticket_ref}.")
            patch = {**patch, "metadata": {**(actual.get("metadata") or {}), **metadata_patch}}

        rows = await self._run(
            lambda: self._client.table("tickets")
            .update(patch)
            .eq("ref", ticket_ref)
            .execute()
        )
        if not rows:
            raise LookupError(f"No existe el ticket {ticket_ref}.")
        return rows[0]

    async def list_open_tickets(self, limit: int = 50) -> list[dict[str, Any]]:
        """Todos los tickets abiertos, de todos los clientes. Para el operador."""
        return await self._run(
            lambda: self._client.table("tickets")
            .select("ref, type, status, priority, subject, created_at, "
                    "clients(phone, name, company)")
            .in_("status", ["open", "in_progress", "waiting_client"])
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )

    async def last_inbound_at(self, phone: str) -> str | None:
        """Cuándo escribió el número por última vez (ventana de 24 h de WhatsApp)."""
        rows = await self._run(
            lambda: self._client.table("messages")
            .select("created_at")
            .eq("phone", phone)
            .eq("direction", "inbound")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return rows[0]["created_at"] if rows else None

    async def open_tickets(self, client_id: str) -> list[dict[str, Any]]:
        return await self._run(
            lambda: self._client.table("tickets")
            .select("ref, type, status, priority, subject, created_at")
            .eq("client_id", client_id)
            .in_("status", ["open", "in_progress", "waiting_client"])
            .order("created_at", desc=True)
            .execute()
        )

    # ── Knowledge ───────────────────────────────────────────────────────────

    async def search_knowledge(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return await self._run(
            lambda: self._client.rpc(
                "search_knowledge", {"query_text": query, "match_limit": limit}
            ).execute()
        )

    # ── Escalados ───────────────────────────────────────────────────────────

    async def create_escalation_row(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = await self._run(
            lambda: self._client.table("escalations").insert(payload).execute()
        )
        return rows[0]

    async def list_pending_escalations(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self._run(
            lambda: self._client.table("escalations")
            .select("id, reason, summary, status, created_at, ticket_id, "
                    "clients(phone, name)")
            .in_("status", ["pending", "claimed"])
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )

    async def resolve_escalations_for_ticket(self, ticket_id: str) -> int:
        """Cerrar el ticket cierra su escalado. Si no, la cola del equipo nunca baja."""
        rows = await self._run(
            lambda: self._client.table("escalations")
            .update({"status": "resolved"})
            .eq("ticket_id", ticket_id)
            .in_("status", ["pending", "claimed"])
            .execute()
        )
        return len(rows or [])

    async def move_escalations_for_client(
        self, client_id: str, from_status: str, to_status: str
    ) -> int:
        """Tomar el chat reclama los escalados; devolverlo los resuelve."""
        rows = await self._run(
            lambda: self._client.table("escalations")
            .update({"status": to_status})
            .eq("client_id", client_id)
            .eq("status", from_status)
            .execute()
        )
        return len(rows or [])


def _find_auth_user(admin: Any, email: str) -> str | None:
    """user_id del usuario de Auth con ese email. La API admin no filtra por email."""
    page = 1
    while True:
        users = admin.list_users(page=page, per_page=200)
        for user in users:
            if (user.email or "").lower() == email.lower():
                return user.id
        if len(users) < 200:
            return None
        page += 1
