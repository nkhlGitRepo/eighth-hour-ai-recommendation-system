"""
Per-client limits on the store-customer endpoints.

Two limits. A plain request rate, so one client can't hammer the engine; and a
cap on how many DIFFERENT customers one client acts as in an hour. A shopper is
one customer, and a shared connection (an office, a household) a handful -- a
client cycling through dozens of customers is someone minting tokens with the
theme's secret, which is the one misuse the theme-only design can't prevent
outright, so it is refused and logged.

In memory, per process: right for the single process the API runs as.
"""

import threading
import time
from collections import defaultdict, deque

from py_src.utils.logger import logger

REQUESTS_PER_MINUTE = 120
CUSTOMERS_PER_HOUR = 20


class RateLimited(Exception):
    """Maps to HTTP 429."""


class ClientLimiter:
    def __init__(self, requests_per_minute=REQUESTS_PER_MINUTE, customers_per_hour=CUSTOMERS_PER_HOUR):
        self.requests_per_minute = requests_per_minute
        self.customers_per_hour = customers_per_hour
        self._requests = defaultdict(deque)          # client -> request times
        self._customers = defaultdict(dict)          # client -> {user_id: last seen}
        self._lock = threading.Lock()

    def check(self, client: str, user_id: str, now: float = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            requests = self._requests[client]
            while requests and now - requests[0] > 60:
                requests.popleft()
            if len(requests) >= self.requests_per_minute:
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
            customers[user_id] = now


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
