"""Orders and payment (roadmap P4 s48): an order's life, and who takes the money.

Three parts, each knowing as little as possible about the others:

- **`states`**: the order's state machine. Every transition the business allows is written
  down once; anything else raises, so an order cannot become "delivered" without having been
  paid, by any path.
- **`providers`**: `PaymentProvider`, the one interface the order logic talks to, and its first
  implementation, `InvoiceProvider` (a proforma, a bank transfer, a person reconciling it).
  Neither Stripe nor PayPal can pay out to North Macedonia (brief §3.2); a local card gateway
  (CPay/CaSys) is a second implementation, added to `PROVIDERS`, with nothing here changed.
- **`service`**: creating an order at the price `config/prices.yaml` says, asking its provider
  for payment, and confirming it. It never asks which provider it has.

The buyer's legal identity on an order (name, ЕДБ, ЕМБС, address) is for the invoice alone and
never reaches a model (CLAUDE.md invariant 4): nothing in this package calls the gateway.
"""
