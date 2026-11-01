# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio

from cache import Cache
import handlers
import ui


class FakeDB:
    def __init__(self, allow_invoice=True):
        self.created = []
        self.settled = []
        self.allow_invoice = allow_invoice
        self.expired = None

    async def create_star_invoice(self, uid, payload, amount, max_open, ttl_hours, product_type="video"):
        self.created.append((uid, payload, amount, max_open, ttl_hours, product_type))
        return self.allow_invoice

    async def expire_star_invoice(self, payload):
        self.expired = payload

    async def settle_star_payment(self, payload, status):
        self.settled.append((payload, status))


class FakeClient:
    def __init__(self, refund_result=True):
        self.invoice = None
        self.refund_result = refund_result
        self.refund_args = None
        self.messages = []

    async def send_invoice(self, **kwargs):
        self.invoice = kwargs

    async def refund_star_payment(self, **kwargs):
        self.refund_args = kwargs
        return self.refund_result

    async def send_message(self, uid, text):
        self.messages.append((uid, text))


def test_stars_invoice_uses_configured_xtr_price(monkeypatch):
    db = FakeDB()
    client = FakeClient()
    monkeypatch.setattr(handlers, "db", db)
    monkeypatch.setattr(handlers, "cache", Cache())
    result = asyncio.run(handlers._send_stars_invoice(client, 42, 42))
    invoice = client.invoice
    assert result is True
    assert invoice["currency"] == "XTR"
    assert invoice["provider_token"] == ""
    assert len(invoice["prices"]) == 1
    assert invoice["prices"][0].amount == handlers.config.STARS_VIDEO_PRICE
    assert invoice["payload"].startswith("ffstars:42:")
    assert db.created == [(42, invoice["payload"], handlers.config.STARS_VIDEO_PRICE,
                           handlers.config.MAX_OPEN_STAR_INVOICES,
                           handlers.config.STAR_INVOICE_TTL_HOURS, "video")]


def test_optional_subscription_invoice_is_distinct_and_uses_configured_price(monkeypatch):
    db = FakeDB()
    client = FakeClient()
    monkeypatch.setattr(handlers, "db", db)
    monkeypatch.setattr(handlers, "cache", Cache())
    monkeypatch.setattr(handlers.config, "STARS_SUB_30D_PRICE", 777)
    assert asyncio.run(handlers._send_stars_invoice(client, 42, 42, product_type="sub30"))
    assert client.invoice["payload"].startswith("ffsub30:42:")
    assert client.invoice["prices"][0].amount == 777
    assert db.created[0][-1] == "sub30"


def test_subscription_invoice_stays_disabled_when_price_is_zero(monkeypatch):
    db = FakeDB()
    client = FakeClient()
    monkeypatch.setattr(handlers, "db", db)
    monkeypatch.setattr(handlers, "cache", Cache())
    monkeypatch.setattr(handlers.config, "STARS_SUB_30D_PRICE", 0)
    assert not asyncio.run(handlers._send_stars_invoice(client, 42, 42, product_type="sub30"))
    assert not db.created and client.invoice is None


def test_subscription_purchase_button_is_hidden_unless_price_is_positive(monkeypatch):
    def callback_data():
        markup = ui.sub_alert_kb()
        return [button.callback_data for row in markup.inline_keyboard for button in row]

    monkeypatch.setattr(handlers.config, "STARS_SUB_30D_PRICE", 0)
    assert "stars:sub30" not in callback_data()
    monkeypatch.setattr(handlers.config, "STARS_SUB_30D_PRICE", 321)
    assert "stars:sub30" in callback_data()
    assert "321" in ui.sub_alert(42)


def test_invoice_cooldown_prevents_repeated_invoice_creation(monkeypatch):
    db = FakeDB()
    client = FakeClient()
    monkeypatch.setattr(handlers, "db", db)
    monkeypatch.setattr(handlers, "cache", Cache())

    async def run():
        assert await handlers._send_stars_invoice(client, 42, 42)
        assert not await handlers._send_stars_invoice(client, 42, 42)

    asyncio.run(run())
    assert len(db.created) == 1


def test_open_invoice_limit_does_not_send_invoice(monkeypatch):
    db = FakeDB(allow_invoice=False)
    client = FakeClient()
    monkeypatch.setattr(handlers, "db", db)
    monkeypatch.setattr(handlers, "cache", Cache())
    assert asyncio.run(handlers._send_stars_invoice(client, 42, 42)) is False
    assert client.invoice is None


def test_failed_job_refunds_and_records_refunded(monkeypatch):
    db = FakeDB()
    client = FakeClient()
    monkeypatch.setattr(handlers, "db", db)
    payment = {"invoice_payload": "ffstars:42:abc", "charge_id": "charge-1"}
    asyncio.run(handlers._refund_star_payment(client, 42, payment))
    assert client.refund_args == {"user_id": 42, "telegram_payment_charge_id": "charge-1"}
    assert db.settled == [("ffstars:42:abc", "refunded")]


def test_unconfirmed_refund_is_not_marked_refunded(monkeypatch):
    db = FakeDB()
    client = FakeClient(refund_result=False)
    monkeypatch.setattr(handlers, "db", db)
    payment = {"invoice_payload": "ffstars:42:abc", "charge_id": "charge-1"}
    asyncio.run(handlers._refund_star_payment(client, 42, payment))
    assert db.settled == [("ffstars:42:abc", "refund_pending")]
