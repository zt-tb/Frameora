# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio
import os
import time
import uuid

import pytest

from database import Database


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured")
def test_stars_invoice_types_and_subscription_grant_are_atomic_and_idempotent():
    async def run():
        db = Database()
        await db.connect(os.environ["TEST_DATABASE_URL"])
        uid = 7_000_000_000_000 + time.time_ns() % 1_000_000
        sub_payload = f"ffsub30:{uid}:{uuid.uuid4().hex}"
        video_payload = f"ffstars:{uid}:{uuid.uuid4().hex}"
        try:
            assert await db.create_star_invoice(uid, sub_payload, 777, product_type="sub30")
            invoice = await db.get_star_invoice(uid, sub_payload, 777)
            assert invoice == {"product_type": "sub30", "amount": 777}
            now = time.time()
            assert await db.record_subscription_payment(uid, sub_payload, "sub-charge-" + uuid.uuid4().hex, 777) == "granted"
            sub = await db.get_sub(uid)
            first_expiry = sub["expires_at"]
            assert sub["active"] and first_expiry.timestamp() >= now + 29 * 86400
            assert await db.record_subscription_payment(
                uid, sub_payload, "sub-charge-" + "different", 777
            ) == "invalid"
            original_charge = await db.pool.fetchval(
                "SELECT charge_id FROM stars_payments WHERE invoice_payload=$1", sub_payload
            )
            assert await db.record_subscription_payment(uid, sub_payload, original_charge, 777) == "duplicate"
            assert (await db.get_sub(uid))["expires_at"] == first_expiry

            assert await db.create_star_invoice(uid, video_payload, 250, product_type="video")
            assert await db.record_star_payment(uid, video_payload, "video-charge-" + uuid.uuid4().hex, 250)
            claimed = await db.claim_star_payment(uid, "video-job-" + uuid.uuid4().hex)
            assert claimed and claimed["amount"] == 250
            assert (await db.pool.fetchval(
                "SELECT product_type FROM stars_payments WHERE invoice_payload=$1", video_payload
            )) == "video"
        finally:
            await db.pool.execute("DELETE FROM stars_payments WHERE user_id=$1", uid)
            await db.pool.execute("DELETE FROM subscriptions WHERE user_id=$1", uid)
            await db.close()

    asyncio.run(run())
