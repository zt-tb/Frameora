# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    BIGINT PRIMARY KEY,
    first_name TEXT,
    username   TEXT,
    joined_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id    BIGINT PRIMARY KEY,
    expires_at TIMESTAMPTZ,
    added_by   BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS admins (
    user_id  BIGINT PRIMARY KEY,
    added_by BIGINT,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS stars_payments (
    invoice_payload TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    charge_id TEXT UNIQUE,
    amount INTEGER NOT NULL DEFAULT 250,
    product_type TEXT NOT NULL DEFAULT 'video',
    job_id TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stars_available_idx ON stars_payments (user_id, created_at) WHERE status='available';
CREATE TABLE IF NOT EXISTS jobs (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    fps        INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS warned BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS height INT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT;
ALTER TABLE stars_payments ADD COLUMN IF NOT EXISTS amount INTEGER NOT NULL DEFAULT 250;
ALTER TABLE stars_payments ADD COLUMN IF NOT EXISTS product_type TEXT NOT NULL DEFAULT 'video';
ALTER TABLE stars_payments ADD COLUMN IF NOT EXISTS job_id TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS jobs_job_id_idx ON jobs (job_id) WHERE job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_user_idx ON jobs (user_id);
CREATE INDEX IF NOT EXISTS jobs_created_idx ON jobs (created_at);
CREATE INDEX IF NOT EXISTS stars_created_idx ON stars_payments (created_at);
"""

ACTIVE = "(expires_at IS NULL OR expires_at > now())"


class Database:
    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None
        self._instance_lock_conn: Optional[asyncpg.Connection] = None

    async def connect(self, dsn: str) -> None:
        if dsn.startswith("postgres://"):
            dsn = "postgresql://" + dsn[len("postgres://"):]
        self.pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
        async with self.pool.acquire() as con:
            await con.execute(SCHEMA)
        log.info("PostgreSQL connected")

    async def close(self) -> None:
        if self.pool:
            if self._instance_lock_conn:
                try:
                    await self._instance_lock_conn.execute(
                        "SELECT pg_advisory_unlock($1::bigint)", 0x46524652414D45
                    )
                except Exception:
                    log.exception("could not release PostgreSQL instance lock cleanly")
                finally:
                    await self.pool.release(self._instance_lock_conn)
                    self._instance_lock_conn = None
            await self.pool.close()

    async def acquire_instance_lock(self) -> bool:
        if not self.pool:
            raise RuntimeError("Database is not connected")
        if self._instance_lock_conn:
            return True
        con = await self.pool.acquire()
        acquired = await con.fetchval("SELECT pg_try_advisory_lock($1::bigint)", 0x46524652414D45)
        if not acquired:
            await self.pool.release(con)
            return False
        self._instance_lock_conn = con
        return True


    async def upsert_user(self, uid: int, first_name: str | None, username: str | None) -> None:
        await self.pool.execute(
            """INSERT INTO users (user_id, first_name, username) VALUES ($1,$2,$3)
               ON CONFLICT (user_id) DO UPDATE
               SET first_name=$2, username=$3, last_seen=now()""",
            uid, first_name, username,
        )

    async def get_lang(self, uid: int) -> str | None:
        return await self.pool.fetchval("SELECT lang FROM users WHERE user_id=$1", uid)

    async def set_lang(self, uid: int, lang: str) -> None:
        await self.pool.execute(
            """INSERT INTO users (user_id, lang) VALUES ($1,$2)
               ON CONFLICT (user_id) DO UPDATE SET lang=$2""",
            uid, lang,
        )

    async def touch_user(self, uid: int) -> None:
        await self.pool.execute("UPDATE users SET last_seen=now() WHERE user_id=$1", uid)

    async def all_user_ids(self) -> list[int]:
        rows = await self.pool.fetch("SELECT user_id FROM users")
        return [r["user_id"] for r in rows]

    async def get_sub(self, uid: int) -> Optional[dict]:
        row = await self.pool.fetchrow(
            f"SELECT expires_at, {ACTIVE} AS active FROM subscriptions WHERE user_id=$1", uid
        )
        return dict(row) if row else None

    async def has_active_sub(self, uid: int) -> bool:
        return bool(
            await self.pool.fetchval(
                f"SELECT 1 FROM subscriptions WHERE user_id=$1 AND {ACTIVE}", uid
            )
        )

    async def _add_subscription_tx(self, con, uid: int, days: Optional[int], by: Optional[int]) -> Optional[datetime]:
        await con.execute("SELECT pg_advisory_xact_lock($1::bigint)", uid)
        now = datetime.now(timezone.utc)
        cur = await con.fetchrow("SELECT expires_at FROM subscriptions WHERE user_id=$1 FOR UPDATE", uid)
        if days is None:
            expires = None
        elif cur and cur["expires_at"] is None:
            expires = None
        else:
            base = cur["expires_at"] if cur and cur["expires_at"] > now else now
            expires = base + timedelta(days=days)
        await con.execute(
            """INSERT INTO subscriptions (user_id, expires_at, added_by) VALUES ($1,$2,$3)
               ON CONFLICT (user_id) DO UPDATE
               SET expires_at=$2, added_by=$3, updated_at=now(), warned=false""",
            uid, expires, by,
        )
        return expires

    async def add_subscription(self, uid: int, days: Optional[int], by: Optional[int]) -> Optional[datetime]:
        async with self.pool.acquire() as con:
            async with con.transaction():
                return await self._add_subscription_tx(con, uid, days, by)

    async def expiring_subs(self, within_days: int) -> list[dict]:
        rows = await self.pool.fetch(
            """SELECT user_id, expires_at FROM subscriptions
               WHERE expires_at IS NOT NULL AND expires_at > now()
                 AND expires_at <= now() + make_interval(days => $1)
                 AND warned = false""",
            within_days,
        )
        return [dict(r) for r in rows]

    async def mark_warned(self, uid: int) -> None:
        await self.pool.execute("UPDATE subscriptions SET warned=true WHERE user_id=$1", uid)

    async def remove_subscription(self, uid: int) -> bool:
        res = await self.pool.execute("DELETE FROM subscriptions WHERE user_id=$1", uid)
        return res.endswith("1")

    async def is_admin(self, uid: int) -> bool:
        return bool(await self.pool.fetchval("SELECT 1 FROM admins WHERE user_id=$1", uid))

    async def add_admin(self, uid: int, by: int) -> None:
        await self.pool.execute(
            "INSERT INTO admins (user_id, added_by) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, by
        )

    async def remove_admin(self, uid: int) -> bool:
        res = await self.pool.execute("DELETE FROM admins WHERE user_id=$1", uid)
        return res.endswith("1")


    async def create_star_invoice(self, uid: int, payload: str, amount: int,
                                  max_open: int = 3, ttl_hours: int = 24,
                                  product_type: str = "video") -> bool:
        if product_type not in ("video", "sub30"):
            raise ValueError("invalid Stars product type")
        async with self.pool.acquire() as con:
            async with con.transaction():
                await con.execute("SELECT pg_advisory_xact_lock($1::bigint)", uid)
                await con.execute(
                    "UPDATE stars_payments SET status='expired',updated_at=now() "
                    "WHERE user_id=$1 AND status='created' AND created_at < now()-make_interval(hours => $2)",
                    uid, ttl_hours,
                )
                pending = await con.fetchval(
                    "SELECT count(*) FROM stars_payments WHERE user_id=$1 AND status='created' "
                    "AND created_at >= now()-make_interval(hours => $2)", uid, ttl_hours,
                )
                if pending >= max_open:
                    return False
                await con.execute(
                    "INSERT INTO stars_payments (invoice_payload,user_id,amount,product_type,status) "
                    "VALUES ($1,$2,$3,$4,'created')",
                    payload, uid, amount, product_type,
                )
        return True

    async def cleanup_star_invoices(self, ttl_hours: int = 24) -> int:
        result = await self.pool.execute(
            "UPDATE stars_payments SET status='expired',updated_at=now() "
            "WHERE status='created' AND created_at < now()-make_interval(hours => $1)", ttl_hours,
        )
        return int(result.rsplit(" ", 1)[-1])

    async def expire_star_invoice(self, payload: str) -> None:
        await self.pool.execute(
            "UPDATE stars_payments SET status='expired',updated_at=now() "
            "WHERE invoice_payload=$1 AND status='created'", payload,
        )

    async def verify_star_invoice(self, uid: int, payload: str, amount: int) -> bool:
        return bool(await self.pool.fetchval(
            "SELECT 1 FROM stars_payments WHERE invoice_payload=$1 AND user_id=$2 "
            "AND status='created' AND amount=$3", payload, uid, amount,
        ))

    async def get_star_invoice(self, uid: int, payload: str, amount: int) -> Optional[dict]:
        row = await self.pool.fetchrow(
            "SELECT product_type,amount FROM stars_payments WHERE invoice_payload=$1 AND user_id=$2 "
            "AND status='created' AND amount=$3", payload, uid, amount,
        )
        return dict(row) if row else None

    async def record_star_payment(self, uid: int, payload: str, charge_id: str, amount: int) -> bool:
        result = await self.pool.execute(
            "UPDATE stars_payments SET charge_id=$3,status='available',updated_at=now() "
            "WHERE invoice_payload=$1 AND user_id=$2 AND amount=$4 AND product_type='video' "
            "AND status='created' AND charge_id IS NULL",
            payload, uid, charge_id, amount,
        )
        return result.endswith('1')

    async def record_subscription_payment(self, uid: int, payload: str, charge_id: str,
                                          amount: int) -> str:
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "SELECT amount,product_type,status,charge_id FROM stars_payments "
                    "WHERE invoice_payload=$1 AND user_id=$2 FOR UPDATE", payload, uid,
                )
                if not row or row["product_type"] != "sub30" or row["amount"] != amount:
                    return "invalid"
                if row["status"] == "used" and row["charge_id"] == charge_id:
                    return "duplicate"
                if row["status"] != "created" or row["charge_id"] is not None:
                    return "invalid"

                await self._add_subscription_tx(con, uid, 30, None)
                updated = await con.execute(
                    "UPDATE stars_payments SET charge_id=$3,status='used',updated_at=now() "
                    "WHERE invoice_payload=$1 AND user_id=$2 AND product_type='sub30' AND status='created' "
                    "AND amount=$4 AND charge_id IS NULL",
                    payload, uid, charge_id, amount,
                )
                if not updated.endswith("1"):
                    raise RuntimeError("subscription payment state changed during transaction")
                return "granted"
    async def has_available_star(self, uid: int) -> bool:
        return bool(await self.pool.fetchval(
            "SELECT 1 FROM stars_payments WHERE user_id=$1 AND status='available' LIMIT 1", uid
        ))
    async def claim_star_payment(self, uid: int, job_id: str) -> Optional[dict]:
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "SELECT invoice_payload,charge_id,amount FROM stars_payments "
                    "WHERE user_id=$1 AND status='available' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED", uid
                )
                if not row:
                    return None
                await con.execute(
                    "UPDATE stars_payments SET status='processing',job_id=$2,updated_at=now() "
                    "WHERE invoice_payload=$1", row['invoice_payload'], job_id,
                )
                return dict(row)

    async def settle_star_payment(self, payload: str, status: str) -> None:
        if status not in ('used','available','refund_pending','refund_processing','refunded'):
            raise ValueError('invalid star payment status')
        await self.pool.execute(
            "UPDATE stars_payments SET status=$2,updated_at=now() WHERE invoice_payload=$1 "
            "AND status IN ('processing','refund_processing','refund_pending')",
            payload, status,
        )

    async def recover_stale_star_payments(self, processing_hours: int = 24,
                                          refund_minutes: int = 30) -> int:
        result = await self.pool.execute(
            "UPDATE stars_payments SET status='refund_pending',updated_at=now() WHERE "
            "(status='processing' AND updated_at < now()-make_interval(hours => $1)) OR "
            "(status='refund_processing' AND updated_at < now()-make_interval(mins => $2))",
            processing_hours, refund_minutes,
        )
        return int(result.rsplit(" ", 1)[-1])

    async def claim_pending_refunds(self, limit: int = 50) -> list[dict]:
        async with self.pool.acquire() as con:
            async with con.transaction():
                rows = await con.fetch(
                    "SELECT invoice_payload,user_id,charge_id,amount,job_id FROM stars_payments "
                    "WHERE status='refund_pending' ORDER BY updated_at LIMIT $1 FOR UPDATE SKIP LOCKED", limit,
                )
                if not rows:
                    return []
                await con.execute(
                    "UPDATE stars_payments SET status='refund_processing',updated_at=now() "
                    "WHERE invoice_payload = ANY($1::text[])", [r['invoice_payload'] for r in rows],
                )
                return [dict(r) for r in rows]
    async def log_job(self, uid: int, fps: int, size_bytes: int | None = None,
                      height: int | None = None, job_id: str | None = None) -> None:
        await self.pool.execute(
            "INSERT INTO jobs (user_id, fps, size_bytes, height, job_id) VALUES ($1,$2,$3,$4,$5)",
            uid, fps, size_bytes, height, job_id,
        )

    async def user_stats(self, uid: int) -> dict:
        row = await self.pool.fetchrow(
            """SELECT count(*) AS total,
                      count(*) FILTER (WHERE created_at > now() - interval '1 day') AS today,
                      count(*) FILTER (WHERE fps = 120) AS fps120,
                      max(created_at) AS last
               FROM jobs WHERE user_id=$1""",
            uid,
        )
        return dict(row)

    async def stats(self) -> dict:
        row = await self.pool.fetchrow(
            f"""SELECT (SELECT count(*) FROM users)                                        AS users,
                       (SELECT count(*) FROM subscriptions WHERE {ACTIVE})                 AS subs,
                       (SELECT count(*) FROM users WHERE last_seen > now() - interval '7 days') AS active_week,
                       (SELECT count(*) FROM jobs)                                         AS jobs,
                       (SELECT count(*) FROM jobs WHERE created_at > now() - interval '1 day')  AS jobs_today,
                       (SELECT count(*) FROM jobs WHERE created_at > now() - interval '7 days') AS jobs_week,
                       (SELECT count(*) FROM jobs WHERE fps = 120)                         AS jobs_120,
                       (SELECT count(*) FROM admins)                                       AS admins"""
        )
        return dict(row)


db = Database()
