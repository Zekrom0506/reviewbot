"""Talks to the (pretend) payment gateway."""

import logging
import os

import requests

logger = logging.getLogger(__name__)

GATEWAY_URL = os.environ.get("PAYMENT_GATEWAY_URL", "https://payments.example.com")
GATEWAY_KEY = os.environ.get("PAYMENT_GATEWAY_KEY", "")
TIMEOUT_SECONDS = 10


class PaymentError(Exception):
    pass


def charge(order_id: int, amount_paise: int) -> str:
    if amount_paise <= 0:
        raise PaymentError("Amount must be positive")
    try:
        response = requests.post(
            f"{GATEWAY_URL}/charges",
            json={"order_id": order_id, "amount": amount_paise, "currency": "INR"},
            headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        logger.error("Charge failed for order %s: %s", order_id, error)
        raise PaymentError("Payment gateway error") from error
    return response.json()["charge_id"]


def refund(charge_id: str, amount_paise: int) -> bool:
    if amount_paise <= 0:
        raise PaymentError("Refund amount must be positive")
    try:
        response = requests.post(
            f"{GATEWAY_URL}/refunds",
            json={"charge_id": charge_id, "amount": amount_paise},
            headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        logger.error("Refund failed for charge %s: %s", charge_id, error)
        raise PaymentError("Refund failed") from error
    return response.json().get("status") == "refunded"
