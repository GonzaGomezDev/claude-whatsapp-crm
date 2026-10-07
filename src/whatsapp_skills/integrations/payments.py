"""Proveedor de pagos, detrás de un Protocol.

La Skill de pagos no sabe qué proveedor hay abajo. Declara qué necesita
—crear un enlace, consultar un estado— y el adapter resuelve cómo.

Es el mismo argumento del video aplicado una capa más abajo: la Skill no cambia,
cambia el adapter. Si estás en LATAM y querés Mercado Pago, implementás
`PaymentProvider` con `preference_create` y no tocás skills/payments/tools.py.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class PaymentLink:
    external_id: str
    url: str
    amount_cents: int
    currency: str


@dataclass(frozen=True)
class PaymentStatus:
    external_id: str
    status: str  # pending | paid | failed | expired | refunded
    amount_cents: int
    currency: str
    raw: dict[str, Any]


@runtime_checkable
class PaymentProvider(Protocol):
    name: str

    async def create_link(
        self,
        *,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: dict[str, str],
    ) -> PaymentLink: ...

    async def get_status(self, external_id: str) -> PaymentStatus: ...


class StripeProvider:
    """Stripe Payment Links.

    Se elige Payment Links en vez de Checkout Sessions porque devuelve una URL
    permanente que se puede mandar por WhatsApp y sigue siendo válida más tarde;
    una Checkout Session expira en 24hs y el cliente vuelve a escribir enojado.
    """

    name = "stripe"

    # Stripe usa el subunit de cada moneda salvo en las zero-decimal.
    _ZERO_DECIMAL = {"jpy", "krw", "vnd", "clp", "isk", "xaf", "xof", "bif", "pyg"}

    def __init__(self, secret_key: str, default_currency: str = "usd") -> None:
        import stripe

        self._stripe = stripe
        self._stripe.api_key = secret_key
        self.default_currency = default_currency.lower()

    async def create_link(
        self,
        *,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: dict[str, str],
    ) -> PaymentLink:
        currency = (currency or self.default_currency).lower()

        def _call() -> Any:
            price = self._stripe.Price.create(
                currency=currency,
                unit_amount=amount_cents,
                product_data={"name": description[:250]},
            )
            return self._stripe.PaymentLink.create(
                line_items=[{"price": price.id, "quantity": 1}],
                metadata=metadata,
            )

        link = await asyncio.to_thread(_call)
        return PaymentLink(
            external_id=link.id,
            url=link.url,
            amount_cents=amount_cents,
            currency=currency,
        )

    async def get_status(self, external_id: str) -> PaymentStatus:
        def _call() -> Any:
            # Un PaymentLink no tiene "estado de pago": lo que se cobra son las
            # sesiones que nacen de él. Miramos la última.
            sessions = self._stripe.checkout.Session.list(
                payment_link=external_id, limit=1
            )
            return sessions.data[0] if sessions.data else None

        session = await asyncio.to_thread(_call)
        if session is None:
            return PaymentStatus(
                external_id=external_id,
                status="pending",
                amount_cents=0,
                currency=self.default_currency,
                raw={"detail": "Todavía no hay ninguna sesión de checkout para este enlace."},
            )

        mapping = {"paid": "paid", "unpaid": "pending", "no_payment_required": "paid"}
        return PaymentStatus(
            external_id=external_id,
            status=mapping.get(session.get("payment_status", ""), "pending"),
            amount_cents=session.get("amount_total") or 0,
            currency=(session.get("currency") or self.default_currency).lower(),
            raw={
                "session_id": session.get("id"),
                "payment_status": session.get("payment_status"),
                "status": session.get("status"),
            },
        )

    def to_minor_units(self, amount: float, currency: str) -> int:
        """USD 9.60 -> 960. JPY 960 -> 960."""
        if currency.lower() in self._ZERO_DECIMAL:
            return int(round(amount))
        return int(round(amount * 100))


def build_payment_provider(settings: Any) -> PaymentProvider:
    if settings.payment_provider == "stripe":
        if not settings.stripe_secret_key:
            raise ValueError(
                "PAYMENT_PROVIDER=stripe requiere STRIPE_SECRET_KEY. Sacala de "
                "dashboard.stripe.com/apikeys (empieza con sk_test_ para pruebas)."
            )
        return StripeProvider(settings.stripe_secret_key, settings.stripe_currency)

    raise ValueError(
        f"Proveedor de pagos desconocido: {settings.payment_provider!r}. "
        "Implementá el Protocol PaymentProvider y registralo acá."
    )
