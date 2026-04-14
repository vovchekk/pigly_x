import hashlib
import hmac
import json
import re
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.utils import timezone

from .models import PlanAccess, Purchase


NOWPAYMENTS_FINISHED_STATUSES = {"confirmed", "finished"}
NOWPAYMENTS_TERMINAL_FAILURE_STATUSES = {"failed", "expired", "refunded"}
PURCHASE_FINISHED_STATUSES = NOWPAYMENTS_FINISHED_STATUSES | {"paid", "wallet_confirmed"}
ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

PRICING_PLANS = {
    PlanAccess.PLAN_PRO: {
        "amount": Decimal("2.00"),
        "duration_days": 30,
        "description": "Pigly Pro subscription",
    },
    PlanAccess.PLAN_SUPPORTER: {
        "amount": Decimal("18.00"),
        "duration_days": 30,
        "description": "Pigly Supporter subscription",
    },
}

WEB3_PAYMENT_NETWORKS = {
    "ethereum": {
        "name": "Ethereum",
        "chain_id": 1,
        "chain_id_hex": "0x1",
        "rpc_url_setting": "WEB3_ETHEREUM_RPC_URL",
        "native_currency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
        "block_explorer_url": "https://etherscan.io",
        "usdc_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "eth_per_usd": Decimal("0.0005"),
    },
    "base": {
        "name": "Base",
        "chain_id": 8453,
        "chain_id_hex": "0x2105",
        "rpc_url_setting": "WEB3_BASE_RPC_URL",
        "native_currency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
        "block_explorer_url": "https://basescan.org",
        "usdc_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "eth_per_usd": Decimal("0.0005"),
    },
    "arbitrum": {
        "name": "Arbitrum One",
        "chain_id": 42161,
        "chain_id_hex": "0xa4b1",
        "rpc_url_setting": "WEB3_ARBITRUM_RPC_URL",
        "native_currency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
        "block_explorer_url": "https://arbiscan.io",
        "usdc_address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "eth_per_usd": Decimal("0.0005"),
    },
    "abstract": {
        "name": "Abstract",
        "chain_id": 2741,
        "chain_id_hex": "0xab5",
        "rpc_url_setting": "WEB3_ABSTRACT_RPC_URL",
        "native_currency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
        "block_explorer_url": "https://abscan.org",
        "usdc_address": "0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1",
        "eth_per_usd": Decimal("0.0005"),
    },
}


def apply_plan_access_defaults(plan_access, plan):
    plan_access.plan = plan
    if plan == PlanAccess.PLAN_FREE:
        plan_access.ai_reply_limit = 30
        plan_access.shorten_limit = 30
    else:
        plan_access.ai_reply_limit = 0
        plan_access.shorten_limit = 0


def activate_plan_from_purchase(purchase):
    plan_config = PRICING_PLANS.get(purchase.plan)
    if not plan_config:
        return
    plan_access = purchase.user.plan_access
    now = timezone.now()
    base_date = plan_access.expires_at if plan_access.expires_at and plan_access.expires_at > now else now
    apply_plan_access_defaults(plan_access, purchase.plan)
    plan_access.expires_at = base_date + timezone.timedelta(days=plan_config["duration_days"])
    plan_access.save(update_fields=["plan", "ai_reply_limit", "shorten_limit", "expires_at"])


def absolute_site_url(path):
    root = settings.SITE_URL.rstrip("/")
    if str(path).startswith("http://") or str(path).startswith("https://"):
        return str(path)
    return f"{root}{path}"


def json_sort(value):
    if isinstance(value, dict):
        return {key: json_sort(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [json_sort(item) for item in value]
    return value


def nowpayments_signature(payload):
    sorted_payload = json_sort(payload)
    message = json.dumps(sorted_payload, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(
        settings.NOWPAYMENTS_IPN_SECRET.encode(),
        message.encode(),
        hashlib.sha512,
    ).hexdigest()


def decimal_from_payload(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalize_evm_address(value):
    address = (value or "").strip().lower()
    if re.fullmatch(r"0x[a-f0-9]{40}", address):
        return address
    return ""


def address_to_topic(address):
    normalized = normalize_evm_address(address)
    if not normalized:
        return ""
    return f"0x{'0' * 24}{normalized[2:]}"


def rpc_call(rpc_url, method, params):
    response = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise ValueError(data["error"])
    return data.get("result")


def receipt_has_expected_usdc_transfer(receipt, *, token_address, receiver_address, amount_units, payer_address=""):
    token = normalize_evm_address(token_address)
    receiver_topic = address_to_topic(receiver_address)
    payer_topic = address_to_topic(payer_address) if payer_address else ""
    for log in receipt.get("logs") or []:
        topics = [str(topic).lower() for topic in (log.get("topics") or [])]
        if len(topics) < 3:
            continue
        if normalize_evm_address(log.get("address")) != token:
            continue
        if topics[0] != ERC20_TRANSFER_TOPIC:
            continue
        if topics[2] != receiver_topic:
            continue
        if payer_topic and topics[1] != payer_topic:
            continue
        try:
            transferred = int(str(log.get("data") or "0x0"), 16)
        except ValueError:
            continue
        if transferred == amount_units:
            return transferred
    return 0


def eth_amount_wei_for_plan(plan_config, network):
    return int(plan_config["amount"] * network["eth_per_usd"] * Decimal("1000000000000000000"))


def transaction_matches_expected_eth_transfer(tx, *, payer_address, receiver_address, amount_wei):
    if normalize_evm_address(tx.get("from")) != normalize_evm_address(payer_address):
        return False
    if normalize_evm_address(tx.get("to")) != normalize_evm_address(receiver_address):
        return False
    try:
        sent_value = int(str(tx.get("value") or "0x0"), 16)
    except ValueError:
        return False
    return sent_value == amount_wei


def payment_status_label(status):
    labels = dict(Purchase.STATUS_CHOICES)
    return labels.get(status, str(status or "").replace("_", " ").title())
