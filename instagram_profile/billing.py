"""Pushing rows and charging for them. ``Platform`` is the only part that touches the
Apify charging API, so tests can drive it with a fake Actor.

Rules this module keeps:
- Only delivered rows are charged, on push: one 'profile' event per profile row, one 'post' event
  per post row.
- Error rows (not found, private, restricted, login required, blocked, invalid input) are pushed free.
- Room in the user's spending limit is reserved, in dollars, before a page is fetched, so concurrent
  workers never fetch pages the user can't pay for, and the SDK's deliberate overcharge-by-one is
  never relied on. The two events have different prices, so the reservation is money, not a count.
- Outside pay-per-event pricing (local runs, other pricing models) rows are pushed plainly and
  nothing is charged.
"""

from __future__ import annotations

from decimal import Decimal

PROFILE_EVENT = "profile"
POST_EVENT = "post"
EVENTS = (PROFILE_EVENT, POST_EVENT)


class Platform:
    def __init__(self, actor, log=None) -> None:
        self.actor = actor
        self.log = log
        self.reserved = Decimal(0)
        self.charged: dict[str, int] = dict.fromkeys(EVENTS, 0)

    def _manager(self):
        return self.actor.get_charging_manager()

    def is_pay_per_event(self) -> bool:
        return bool(self._manager().get_pricing_info().is_pay_per_event)

    def _price(self, event: str) -> Decimal:
        price = self._manager().get_pricing_info().per_event_prices.get(event)
        return Decimal(str(price)) if price else Decimal(0)

    def reserve(self, event: str) -> bool:
        """Reserve room for one more charged row of this event. False means the spending limit is reached."""
        if not self.is_pay_per_event():
            return True
        price = self._price(event)
        if price:
            manager = self._manager()
            limit = Decimal(str(manager.get_pricing_info().max_total_charge_usd))
            if limit.is_finite():
                left = limit - Decimal(str(manager.calculate_total_charged_amount())) - self.reserved
                if left < price:
                    return False
        self.reserved += price
        return True

    def release(self, event: str) -> None:
        """Give back a reservation (after the row was pushed, or when it turned out free)."""
        if self.is_pay_per_event():
            self.reserved = max(Decimal(0), self.reserved - self._price(event))

    async def push_charged(self, row: dict, event: str) -> None:
        """Push one profile or post row and charge its event."""
        if not self.is_pay_per_event():
            await self.actor.push_data(row)
            return
        result = await self.actor.push_data(row, charged_event_name=event)
        self.charged[event] += result.charged_count
        if result.charged_count < 1 and self.log:
            self.log.warning(f"A {event} row was pushed but the '{event}' event was not charged.")

    async def push_free(self, row: dict) -> None:
        """Push an error row. Never charged."""
        await self.actor.push_data(row)
