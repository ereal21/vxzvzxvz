import requests
from typing import Tuple

from .env import EnvKeys

API_BASE = "https://api.nowpayments.io/v1"
API_KEY = EnvKeys.NOWPAYMENTS_API_KEY

IPN_URL = EnvKeys.NOWPAYMENTS_IPN_URL



def create_payment(amount_eur: float, pay_currency: str) -> Tuple[str, str, float]:
    """Create a payment and return payment_id, pay_address and pay_amount."""
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "price_amount": amount_eur,
        "price_currency": "eur",
        "pay_currency": pay_currency.lower(),
    }

    if IPN_URL:
        payload["ipn_callback_url"] = IPN_URL

    resp = requests.post(f"{API_BASE}/payment", json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return str(data["payment_id"]), data["pay_address"], float(data["pay_amount"])


def check_payment(payment_id: str) -> str | None:
    """Return payment status string for given payment id."""
    headers = {"x-api-key": API_KEY}
    resp = requests.get(f"{API_BASE}/payment/{payment_id}", headers=headers)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    return data.get("payment_status")
