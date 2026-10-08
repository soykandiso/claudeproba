"""The order's state machine (roadmap P4 s48, docs/architecture.md §6).

    created ──► invoiced ──► paid ──► in_progress ──► delivered
       │           │          │           │               │
       └──────────►└──► cancelled         └───────────────┴──► refunded

An order is asked for (created), billed (invoiced: the provider asked for payment), paid
(the provider confirmed it), worked on (the deep analysis and its review), and delivered.
Before payment it can be cancelled; after payment only refunded. A card gateway that takes
the money at once still passes through `invoiced` (it asked) and `paid` (it got it), in the
same call: the states describe the order, not the provider.
"""

from app.models.enums import OrderState as S

ALLOWED: dict[S, frozenset[S]] = {
    S.CREATED: frozenset({S.INVOICED, S.CANCELLED}),
    S.INVOICED: frozenset({S.PAID, S.CANCELLED}),
    S.PAID: frozenset({S.IN_PROGRESS, S.REFUNDED}),
    S.IN_PROGRESS: frozenset({S.DELIVERED, S.REFUNDED}),
    S.DELIVERED: frozenset({S.REFUNDED}),
    S.CANCELLED: frozenset(),
    S.REFUNDED: frozenset(),
}


class IllegalTransition(ValueError):
    """An order was asked to move where the business does not allow."""


def move(order, to: S) -> None:
    """Move an order to `to`, or raise: there is no other way to change its state."""
    current = S(order.state) if order.state else S.CREATED
    if to not in ALLOWED[current]:
        raise IllegalTransition(f"order {order.id}: {current.value} → {to.value} is not allowed")
    order.state = to
