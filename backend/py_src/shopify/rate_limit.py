"""
Request limits, per connection (the caller's address) and per customer.

The store-customer endpoints get three, checked together:
  - a request rate per connection, so no one connection hammers the engine;
  - a cap on how many DIFFERENT customers one connection acts as in an hour --
    a connection cycling through hundreds of customers is someone minting
    tokens with the theme's secret, the one misuse the theme-only design can't
    prevent outright, so it is refused and logged;
  - a request rate per customer, so no one account takes a connection's whole
    allowance.
The per-connection limits are generous because one address can carry many
real shoppers: an office, a campus, a mobile carrier's shared addresses. The
per-customer rate is what the per-connection rate used to be, so raising the
shared allowance gave no single account more than it had.

Photo scans -- the one expensive request: the server runs them one at a time
and everything else waits behind them -- also have their own hourly limits,
per customer and per connection, for store and demo accounts alike.

In memory, per process: right for the single process the API runs as.
"""

import threading
import time
from collections import defaultdict, deque

from py_src.utils.logger import logger

REQUESTS_PER_MINUTE = 600                 # per connection
CUSTOMERS_PER_HOUR = 300                  # per connection
CUSTOMER_REQUESTS_PER_MINUTE = 120        # per customer
PHOTO_SCANS_PER_HOUR = 10                 # per customer -- a shopper needs one to three
CONNECTION_PHOTO_SCANS_PER_HOUR = 60      # per connection


class RateLimited(Exception):
    """Maps to HTTP 429."""


def _within(times: deque, window: float, now: float) -> deque:
    """Drop the entries older than the window; the deque that's left."""
    while times and now - times[0] > window:
        times.popleft()
    return times


class ClientLimiter:
    def __init__(
        self,
        requests_per_minute=REQUESTS_PER_MINUTE,
        customers_per_hour=CUSTOMERS_PER_HOUR,
        customer_requests_per_minute=CUSTOMER_REQUESTS_PER_MINUTE,
    ):
        self.requests_per_minute = requests_per_minute
        self.customers_per_hour = customers_per_hour
        self.customer_requests_per_minute = customer_requests_per_minute
        self._requests = defaultdict(deque)          # client -> request times
        self._customer_requests = defaultdict(deque) # user_id -> request times
        self._customers = defaultdict(dict)          # client -> {user_id: last seen}
        self._lock = threading.Lock()

    def check(self, client: str, user_id: str, now: float = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            requests = _within(self._requests[client], 60, now)
            if len(requests) >= self.requests_per_minute:
                raise RateLimited("Too many requests -- please wait a minute and try again")

            own = _within(self._customer_requests[user_id], 60, now)
            if len(own) >= self.customer_requests_per_minute:
                raise RateLimited("Too many requests -- please wait a minute and try again")

            customers = self._customers[client]
            for seen_id, seen_at in list(customers.items()):
                if now - seen_at > 3600:
                    del customers[seen_id]
            if user_id not in customers and len(customers) >= self.customers_per_hour:
                logger.warn(
                    "Store-customer requests refused: one client acting as many customers",
                    {"client": client, "customers_this_hour": len(customers)},
                )
                raise RateLimited("Too many requests -- please try again later")

            requests.append(now)
            own.append(now)
            customers[user_id] = now


class PhotoScanLimiter:
    """Hourly photo-scan limits, per customer and per connection."""

    def __init__(self, per_customer=PHOTO_SCANS_PER_HOUR, per_connection=CONNECTION_PHOTO_SCANS_PER_HOUR):
        self.per_customer = per_customer
        self.per_connection = per_connection
        self._by_customer = defaultdict(deque)
        self._by_connection = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, client: str, user_id: str, now: float = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            mine = _within(self._by_customer[user_id], 3600, now)
            theirs = _within(self._by_connection[client], 3600, now)
            if len(mine) >= self.per_customer:
                raise RateLimited("You've scanned several photos in the last hour -- please enter your measurements, or try again later")
            if len(theirs) >= self.per_connection:
                logger.warn("Photo scans refused: many from one connection", {"client": client, "scans_this_hour": len(theirs)})
                raise RateLimited("Too many photo scans right now -- please enter your measurements, or try again later")
            mine.append(now)
            theirs.append(now)


def client_address(request) -> str:
    """
    The caller's address. Behind Render's proxy the connecting address is the
    proxy's, so take the last X-Forwarded-For entry -- the one the proxy itself
    added, which a client can't forge (anything it sends ends up further left).
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
