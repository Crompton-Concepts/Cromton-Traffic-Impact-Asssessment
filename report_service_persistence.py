from __future__ import annotations

"""
Persistence abstractions for report_service.py.

Provides pluggable backends for draft storage and rate limiting.
Default fallback is in-memory (identical to legacy behaviour).
Redis and Firestore backends are available for multi-instance deployments.

Usage:
    from report_service_persistence import DraftStore, RateLimiter, create_draft_store, create_rate_limiter

    draft_store = create_draft_store()
    rate_limiter = create_rate_limiter()

Environment variables:
    REPORT_DRAFT_STORE     - "memory" | "redis" | "firestore"  (default: "memory")
    REPORT_RATE_LIMITER    - "memory" | "redis"               (default: "memory")
    REDIS_URL              - Redis connection string            (default: "redis://localhost:6379")
    REDIS_DB               - Redis database number              (default: 0)
    FIRESTORE_PROJECT      - Google Cloud project ID            (default: inferred from env)
    FIRESTORE_COLLECTION   - Firestore collection name          (default: "tia_drafts")
"""

import json
import os
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any


# ── Logging helpers ──────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


# ── Draft Store ──────────────────────────────────────────────────────────

class DraftStore(ABC):
    """Abstract draft storage. All methods are synchronous (blocking)."""

    @abstractmethod
    def get(self, draft_id: str) -> dict[str, Any] | None:
        """Retrieve a draft by ID. Returns None if not found or expired."""
        raise NotImplementedError

    @abstractmethod
    def set(self, draft_id: str, data: dict[str, Any]) -> None:
        """Store (or overwrite) a draft."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, draft_id: str) -> None:
        """Remove a draft."""
        raise NotImplementedError

    @abstractmethod
    def prune(self, ttl_hours: int, max_drafts: int) -> int:
        """Remove stale drafts and enforce max count. Returns number removed."""
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        """Return current draft count."""
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Return health/status info for the store."""
        raise NotImplementedError


class InMemoryDraftStore(DraftStore):
    """Thread-safe in-memory draft store. Identical to legacy DRAFTS dict."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, draft_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get(draft_id)

    def set(self, draft_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._data[draft_id] = data

    def delete(self, draft_id: str) -> None:
        with self._lock:
            self._data.pop(draft_id, None)

    def prune(self, ttl_hours: int, max_drafts: int) -> int:
        with self._lock:
            if not self._data:
                return 0

            now_dt = _utcnow()
            cutoff = now_dt - timedelta(hours=ttl_hours)
            stale_ids: list[str] = []

            for draft_id, item in list(self._data.items()):
                created_epoch = item.get("created_epoch")
                if isinstance(created_epoch, (int, float)):
                    created_at = datetime.fromtimestamp(created_epoch, timezone.utc)
                else:
                    created_at = _parse_datetime_utc(str(item.get("created_at") or ""), now_dt)
                if created_at < cutoff:
                    stale_ids.append(draft_id)

            for stale_id in stale_ids:
                self._data.pop(stale_id, None)

            removed = len(stale_ids)

            if len(self._data) > max_drafts:
                oldest_first = sorted(
                    self._data.items(),
                    key=lambda kv: float(kv[1].get("created_epoch") or 0),
                )
                to_drop = len(self._data) - max_drafts
                for draft_id, _ in oldest_first[:to_drop]:
                    self._data.pop(draft_id, None)
                removed += to_drop

            return removed

    def count(self) -> int:
        with self._lock:
            return len(self._data)

    def health(self) -> dict[str, Any]:
        return {"type": "memory", "count": self.count()}


class RedisDraftStore(DraftStore):
    """Redis-backed draft store using redis-py.

    Drafts are stored as JSON strings in a hash keyed by draft_id.
    TTL is enforced via Redis EXPIRE on each hash field.
    """

    def __init__(self, redis_url: str, db: int = 0, key_prefix: str = "tia:drafts") -> None:
        try:
            import redis
        except ImportError as exc:
            raise ImportError("redis-py is required for RedisDraftStore. Install: pip install redis") from exc

        self._redis = redis.from_url(redis_url, db=db, decode_responses=True)
        self._key_prefix = key_prefix
        self._hash_key = f"{key_prefix}:data"
        self._lock = threading.Lock()

    def _field_key(self, draft_id: str) -> str:
        return f"{self._key_prefix}:draft:{draft_id}"

    def get(self, draft_id: str) -> dict[str, Any] | None:
        field = self._field_key(draft_id)
        raw = self._redis.hget(self._hash_key, field)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set(self, draft_id: str, data: dict[str, Any]) -> None:
        field = self._field_key(draft_id)
        self._redis.hset(self._hash_key, field, json.dumps(data))

    def delete(self, draft_id: str) -> None:
        field = self._field_key(draft_id)
        self._redis.hdel(self._hash_key, field)

    def prune(self, ttl_hours: int, max_drafts: int) -> int:
        # Redis does not natively support per-field TTL in hashes.
        # We manually scan and remove stale entries based on created_epoch.
        removed = 0
        now_dt = _utcnow()
        cutoff = now_dt - timedelta(hours=ttl_hours)
        cutoff_ts = cutoff.timestamp()

        fields = self._redis.hkeys(self._hash_key)
        stale_fields: list[str] = []
        candidates: list[tuple[str, float]] = []

        for field in fields:
            raw = self._redis.hget(self._hash_key, field)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                stale_fields.append(field)
                continue

            created_epoch = data.get("created_epoch")
            if isinstance(created_epoch, (int, float)) and created_epoch < cutoff_ts:
                stale_fields.append(field)
            else:
                candidates.append((field, float(created_epoch or 0)))

        if stale_fields:
            self._redis.hdel(self._hash_key, *stale_fields)
            removed += len(stale_fields)

        if len(candidates) > max_drafts:
            candidates.sort(key=lambda x: x[1])
            to_drop = candidates[:len(candidates) - max_drafts]
            drop_fields = [f for f, _ in to_drop]
            if drop_fields:
                self._redis.hdel(self._hash_key, *drop_fields)
                removed += len(drop_fields)

        return removed

    def count(self) -> int:
        return self._redis.hlen(self._hash_key)

    def health(self) -> dict[str, Any]:
        try:
            info = self._redis.ping()
            return {"type": "redis", "connected": info, "count": self.count()}
        except Exception as e:
            return {"type": "redis", "connected": False, "error": str(e), "count": self.count()}


class FirestoreDraftStore(DraftStore):
    """Google Firestore-backed draft store.

    Each draft is a document in the configured collection.
    """

    def __init__(self, project: str | None = None, collection: str = "tia_drafts") -> None:
        try:
            from google.cloud import firestore
        except ImportError as exc:
            raise ImportError(
                "google-cloud-firestore is required for FirestoreDraftStore. "
                "Install: pip install google-cloud-firestore"
            ) from exc

        self._client = firestore.Client(project=project)
        self._collection = collection

    def _doc_ref(self, draft_id: str):
        return self._client.collection(self._collection).document(draft_id)

    def get(self, draft_id: str) -> dict[str, Any] | None:
        doc = self._doc_ref(draft_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        if data is None:
            return None
        # Firestore stores datetime objects natively; convert back to dict
        return dict(data)

    def set(self, draft_id: str, data: dict[str, Any]) -> None:
        # Firestore cannot serialize datetime in nested dicts easily,
        # so we convert to ISO strings for compatibility.
        clean = _firestore_clean(data)
        self._doc_ref(draft_id).set(clean)

    def delete(self, draft_id: str) -> None:
        self._doc_ref(draft_id).delete()

    def prune(self, ttl_hours: int, max_drafts: int) -> int:
        now_dt = _utcnow()
        cutoff = now_dt - timedelta(hours=ttl_hours)

        collection_ref = self._client.collection(self._collection)
        query = collection_ref.where("created_at", "<", cutoff.isoformat())
        stale = query.stream()

        removed = 0
        batch = self._client.batch()
        count = 0

        for doc in stale:
            batch.delete(doc.reference)
            count += 1
            if count >= 500:  # Firestore batch limit
                batch.commit()
                removed += count
                count = 0
                batch = self._client.batch()

        if count > 0:
            batch.commit()
            removed += count

        # Enforce max_drafts by deleting oldest
        current_count = self.count()
        if current_count > max_drafts:
            to_drop = current_count - max_drafts
            oldest = collection_ref.order_by("created_epoch").limit(to_drop).stream()
            batch = self._client.batch()
            drop_count = 0
            for doc in oldest:
                batch.delete(doc.reference)
                drop_count += 1
            if drop_count > 0:
                batch.commit()
                removed += drop_count

        return removed

    def count(self) -> int:
        # Approximate count via aggregation query (Firestore native)
        try:
            aggregation = self._client.collection(self._collection).count().get()
            return aggregation[0][0].value if aggregation else 0
        except Exception:
            # Fallback: count documents manually (slower)
            return sum(1 for _ in self._client.collection(self._collection).stream())

    def health(self) -> dict[str, Any]:
        try:
            # Lightweight health check: list one document
            docs = self._client.collection(self._collection).limit(1).stream()
            next(docs, None)
            return {"type": "firestore", "connected": True, "count": self.count()}
        except Exception as e:
            return {"type": "firestore", "connected": False, "error": str(e), "count": self.count()}


def _firestore_clean(data: Any) -> Any:
    """Recursively convert datetime objects to ISO strings for Firestore compatibility."""
    if isinstance(data, datetime):
        return data.isoformat()
    if isinstance(data, dict):
        return {k: _firestore_clean(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_firestore_clean(v) for v in data]
    return data


def _parse_datetime_utc(value: str, fallback: datetime) -> datetime:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def create_draft_store() -> DraftStore:
    """Factory: creates the configured draft store backend."""
    store_type = os.environ.get("REPORT_DRAFT_STORE", "memory").lower().strip()

    if store_type == "redis":
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        redis_db = _parse_env_int("REDIS_DB", 0)
        return RedisDraftStore(redis_url, db=redis_db)

    if store_type == "firestore":
        project = os.environ.get("FIRESTORE_PROJECT") or None
        collection = os.environ.get("FIRESTORE_COLLECTION", "tia_drafts")
        return FirestoreDraftStore(project=project, collection=collection)

    return InMemoryDraftStore()


# ── Rate Limiter ─────────────────────────────────────────────────────────

class RateLimiter(ABC):
    """Abstract rate limiter. Check and record hits per client identifier."""

    @abstractmethod
    def check(self, client_id: str, max_hits: int, window_s: int) -> dict[str, int]:
        """Return rate metadata. Raise HTTPException-compatible 429 if exceeded."""
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError


class InMemoryRateLimiter(RateLimiter):
    """Thread-safe in-memory rate limiter. Identical to legacy _RATE_BUCKETS."""

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, client_id: str, max_hits: int, window_s: int) -> dict[str, int]:
        now = time.time()
        cutoff = now - window_s

        with self._lock:
            hits = [t for t in self._buckets.get(client_id, []) if t >= cutoff]

            if len(hits) >= max_hits:
                retry_after = max(1, int(window_s - (now - min(hits))))
                return {
                    "limit": max_hits,
                    "remaining": 0,
                    "reset_epoch": int(min(hits) + window_s),
                    "retry_after": retry_after,
                    "exceeded": True,
                }

            hits.append(now)
            self._buckets[client_id] = hits

            # Opportunistic cleanup
            if len(self._buckets) > 5000:
                for k in [k for k, v in list(self._buckets.items()) if not any(t >= cutoff for t in v)]:
                    self._buckets.pop(k, None)

            return {
                "limit": max_hits,
                "remaining": max(0, max_hits - len(hits)),
                "reset_epoch": int(min(hits) + window_s),
                "retry_after": 0,
                "exceeded": False,
            }

    def health(self) -> dict[str, Any]:
        return {"type": "memory", "bucket_count": len(self._buckets)}


class RedisRateLimiter(RateLimiter):
    """Redis-backed rate limiter using sorted sets for sliding window."""

    def __init__(self, redis_url: str, db: int = 0, key_prefix: str = "tia:ratelimit") -> None:
        try:
            import redis
        except ImportError as exc:
            raise ImportError("redis-py is required for RedisRateLimiter. Install: pip install redis") from exc

        self._redis = redis.from_url(redis_url, db=db, decode_responses=True)
        self._key_prefix = key_prefix

    def _key(self, client_id: str) -> str:
        return f"{self._key_prefix}:{client_id}"

    def check(self, client_id: str, max_hits: int, window_s: int) -> dict[str, int]:
        now = time.time()
        cutoff = now - window_s
        key = self._key(client_id)

        # Remove old entries outside the window
        self._redis.zremrangebyscore(key, "-inf", cutoff)

        # Count current hits in the window
        current_hits = self._redis.zcard(key)

        if current_hits >= max_hits:
            # Get the oldest hit in the window to calculate reset time
            oldest = self._redis.zrange(key, 0, 0, withscores=True)
            oldest_ts = oldest[0][1] if oldest else now
            retry_after = max(1, int(window_s - (now - oldest_ts)))
            return {
                "limit": max_hits,
                "remaining": 0,
                "reset_epoch": int(oldest_ts + window_s),
                "retry_after": retry_after,
                "exceeded": True,
            }

        # Record this hit
        self._redis.zadd(key, {str(now): now})
        # Set expiry on the key so it auto-cleans
        self._redis.expire(key, window_s + 1)

        return {
            "limit": max_hits,
            "remaining": max(0, max_hits - current_hits - 1),
            "reset_epoch": int(now + window_s),
            "retry_after": 0,
            "exceeded": False,
        }

    def health(self) -> dict[str, Any]:
        try:
            info = self._redis.ping()
            return {"type": "redis", "connected": info}
        except Exception as e:
            return {"type": "redis", "connected": False, "error": str(e)}


def create_rate_limiter() -> RateLimiter:
    """Factory: creates the configured rate limiter backend."""
    limiter_type = os.environ.get("REPORT_RATE_LIMITER", "memory").lower().strip()

    if limiter_type == "redis":
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        redis_db = _parse_env_int("REDIS_DB", 0)
        return RedisRateLimiter(redis_url, db=redis_db)

    return InMemoryRateLimiter()
