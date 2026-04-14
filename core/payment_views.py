import logging
import json
import re
import uuid
from decimal import Decimal

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from users.billing import (
    NOWPAYMENTS_FINISHED_STATUSES,
    NOWPAYMENTS_TERMINAL_FAILURE_STATUSES,
    PRICING_PLANS,
    PURCHASE_FINISHED_STATUSES,
    WEB3_PAYMENT_NETWORKS,
    absolute_site_url,
    activate_plan_from_purchase,
    decimal_from_payload,
    eth_amount_wei_for_plan,
    normalize_evm_address,
    nowpayments_signature,
    receipt_has_expected_usdc_transfer,
    rpc_call,
    transaction_matches_expected_eth_transfer,
)
from users.models import Purchase


logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["POST"])
def create_wallet_payment_view(request):
    plan = (request.POST.get("plan") or "").strip().lower()
    network_key = (request.POST.get("network") or "base").strip().lower()
    currency = (request.POST.get("currency") or "usdc").strip().lower()
    payer_address = normalize_evm_address(request.POST.get("payer_address"))
    plan_config = PRICING_PLANS.get(plan)
    network = WEB3_PAYMENT_NETWORKS.get(network_key)
    receiver_address = normalize_evm_address(settings.WEB3_PAYMENT_RECEIVER_ADDRESS)
    if not plan_config:
        return JsonResponse({"ok": False, "error": "unknown_plan"}, status=400)
    if not network:
        return JsonResponse({"ok": False, "error": "unknown_network"}, status=400)
    if not receiver_address:
        return JsonResponse({"ok": False, "error": "web3_receiver_not_configured"}, status=503)
    if currency not in {"usdc", "eth"}:
        return JsonResponse({"ok": False, "error": "unknown_currency"}, status=400)

    amount_units = int(plan_config["amount"] * Decimal("1000000"))
    amount_wei = eth_amount_wei_for_plan(plan_config, network)
    amount_eth = Decimal(amount_wei) / Decimal("1000000000000000000")
    purchase = Purchase.objects.create(
        user=request.user,
        plan=plan,
        provider=Purchase.PROVIDER_WALLET,
        order_id=f"wallet-{request.user.id}-{uuid.uuid4().hex[:20]}",
        amount_usd=plan_config["amount"],
        status=Purchase.STATUS_WALLET_WAITING,
        currency=currency,
        network=network_key,
        raw_payload={
            "provider": "wallet",
            "network": network_key,
            "currency": currency,
            "chain_id": network["chain_id"],
            "payer_address": payer_address,
            "receiver_address": receiver_address,
            "token_address": network["usdc_address"],
            "amount_units": str(amount_units),
            "amount_wei": str(amount_wei),
        },
    )
    return JsonResponse(
        {
            "ok": True,
            "payment_id": purchase.id,
            "currency": currency,
            "amount_units": str(amount_units),
            "amount_wei": hex(amount_wei),
            "amount_eth": format(amount_eth.normalize(), "f"),
            "receiver_address": receiver_address,
            "token_address": network["usdc_address"],
            "chain": {
                "key": network_key,
                "name": network["name"],
                "chain_id": network["chain_id"],
                "chain_id_hex": network["chain_id_hex"],
                "rpc_url": getattr(settings, network["rpc_url_setting"]),
                "native_currency": network["native_currency"],
                "block_explorer_url": network["block_explorer_url"],
            },
        }
    )


@login_required
@require_http_methods(["POST"])
def verify_wallet_payment_view(request):
    payment_id = request.POST.get("payment_id")
    tx_hash = (request.POST.get("tx_hash") or "").strip().lower()
    if not tx_hash.startswith("0x") or not re.fullmatch(r"0x[a-f0-9]{64}", tx_hash):
        return JsonResponse({"ok": False, "error": "invalid_tx_hash"}, status=400)

    purchase = get_object_or_404(Purchase, pk=payment_id, user=request.user)
    if Purchase.objects.filter(tx_hash__iexact=tx_hash, status__in=PURCHASE_FINISHED_STATUSES).exclude(pk=purchase.pk).exists():
        return JsonResponse({"ok": False, "error": "tx_already_used"}, status=400)

    payload = purchase.raw_payload or {}
    network_key = payload.get("network")
    network = WEB3_PAYMENT_NETWORKS.get(network_key)
    if not network:
        return JsonResponse({"ok": False, "error": "unknown_network"}, status=400)

    rpc_url = getattr(settings, network["rpc_url_setting"])
    try:
        receipt = rpc_call(rpc_url, "eth_getTransactionReceipt", [tx_hash])
    except (requests.RequestException, ValueError):
        logger.exception("Wallet payment receipt lookup failed for purchase %s", purchase.id)
        return JsonResponse({"ok": False, "error": "receipt_lookup_failed"}, status=502)
    if not receipt:
        return JsonResponse({"ok": False, "error": "tx_not_confirmed"}, status=202)
    if str(receipt.get("status")).lower() != "0x1":
        purchase.status = Purchase.STATUS_WALLET_FAILED
        purchase.tx_hash = tx_hash
        purchase.raw_payload = {**payload, "receipt": receipt}
        purchase.save(update_fields=["status", "tx_hash", "raw_payload", "updated_at"])
        return JsonResponse({"ok": False, "error": "tx_failed"}, status=400)

    currency = (payload.get("currency") or "usdc").lower()
    transferred_units = 0
    if currency == "eth":
        try:
            tx = rpc_call(rpc_url, "eth_getTransactionByHash", [tx_hash])
        except (requests.RequestException, ValueError):
            logger.exception("Wallet payment transaction lookup failed for purchase %s", purchase.id)
            return JsonResponse({"ok": False, "error": "tx_lookup_failed"}, status=502)
        amount_wei = int(payload.get("amount_wei") or "0")
        if not tx or not transaction_matches_expected_eth_transfer(
            tx,
            payer_address=payload.get("payer_address") or "",
            receiver_address=payload.get("receiver_address") or settings.WEB3_PAYMENT_RECEIVER_ADDRESS,
            amount_wei=amount_wei,
        ):
            purchase.status = Purchase.STATUS_WALLET_REJECTED
            purchase.tx_hash = tx_hash
            purchase.raw_payload = {**payload, "receipt": receipt, "transaction": tx}
            purchase.save(update_fields=["status", "tx_hash", "raw_payload", "updated_at"])
            return JsonResponse({"ok": False, "error": "expected_transfer_not_found"}, status=400)
        transferred_units = amount_wei
        payload = {**payload, "transaction": tx}
    else:
        amount_units = int(payload.get("amount_units") or "0")
        transferred_units = receipt_has_expected_usdc_transfer(
            receipt,
            token_address=payload.get("token_address") or network["usdc_address"],
            receiver_address=payload.get("receiver_address") or settings.WEB3_PAYMENT_RECEIVER_ADDRESS,
            amount_units=amount_units,
            payer_address=payload.get("payer_address") or "",
        )
        if not transferred_units:
            purchase.status = Purchase.STATUS_WALLET_REJECTED
            purchase.tx_hash = tx_hash
            purchase.raw_payload = {**payload, "receipt": receipt}
            purchase.save(update_fields=["status", "tx_hash", "raw_payload", "updated_at"])
            return JsonResponse({"ok": False, "error": "expected_transfer_not_found"}, status=400)

    previous_status = str(purchase.status or "").lower()
    purchase.status = Purchase.STATUS_WALLET_CONFIRMED
    purchase.tx_hash = tx_hash
    purchase.amount_crypto = (
        Decimal(transferred_units) / Decimal("1000000000000000000")
        if currency == "eth"
        else Decimal(transferred_units) / Decimal("1000000")
    )
    purchase.raw_payload = {**payload, "receipt": receipt, "transferred_units": str(transferred_units)}
    purchase.save(update_fields=["status", "tx_hash", "amount_crypto", "raw_payload", "updated_at"])
    if previous_status not in PURCHASE_FINISHED_STATUSES:
        activate_plan_from_purchase(purchase)
    return JsonResponse({"ok": True, "status": purchase.status})


@login_required
@require_http_methods(["POST"])
def create_nowpayments_invoice_view(request):
    plan = (request.POST.get("plan") or "").strip().lower()
    plan_config = PRICING_PLANS.get(plan)
    if not plan_config:
        return JsonResponse({"ok": False, "error": "unknown_plan"}, status=400)
    if not settings.NOWPAYMENTS_API_KEY or not settings.NOWPAYMENTS_IPN_SECRET:
        return JsonResponse({"ok": False, "error": "nowpayments_not_configured"}, status=503)

    order_id = f"pigly-{request.user.id}-{uuid.uuid4().hex[:20]}"
    purchase = Purchase.objects.create(
        user=request.user,
        plan=plan,
        provider=Purchase.PROVIDER_NOWPAYMENTS,
        order_id=order_id,
        amount_usd=plan_config["amount"],
        status=Purchase.STATUS_CREATED,
        currency="usd",
    )
    callback_url = absolute_site_url(reverse("core:nowpayments_ipn"))
    pricing_url = absolute_site_url(reverse("core:landing"))
    payload = {
        "price_amount": str(plan_config["amount"]),
        "price_currency": "usd",
        "order_id": order_id,
        "order_description": plan_config["description"],
        "ipn_callback_url": callback_url,
        "success_url": f"{pricing_url}?payment=success#pricing",
        "cancel_url": f"{pricing_url}?payment=cancelled#pricing",
    }
    try:
        response = requests.post(
            f"{settings.NOWPAYMENTS_API_BASE_URL}/v1/invoice",
            headers={
                "x-api-key": settings.NOWPAYMENTS_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.exception("NOWPayments invoice creation failed for purchase %s", purchase.id)
        purchase.status = Purchase.STATUS_CREATE_FAILED
        purchase.raw_payload = {"error": str(exc)}
        purchase.save(update_fields=["status", "raw_payload", "updated_at"])
        return JsonResponse({"ok": False, "error": "invoice_create_failed"}, status=502)
    except ValueError:
        logger.exception("NOWPayments invoice response was not JSON for purchase %s", purchase.id)
        purchase.status = Purchase.STATUS_CREATE_FAILED
        purchase.raw_payload = {"error": "invalid_json_response"}
        purchase.save(update_fields=["status", "raw_payload", "updated_at"])
        return JsonResponse({"ok": False, "error": "invoice_create_failed"}, status=502)

    invoice_url = data.get("invoice_url") or data.get("url") or ""
    invoice_id = str(data.get("id") or data.get("invoice_id") or "")
    purchase.provider_invoice_id = invoice_id
    purchase.provider_payment_id = invoice_id
    purchase.invoice_url = invoice_url
    purchase.status = data.get("payment_status") or data.get("status") or Purchase.STATUS_WAITING
    purchase.raw_payload = data
    purchase.save(
        update_fields=[
            "provider_invoice_id",
            "provider_payment_id",
            "invoice_url",
            "status",
            "raw_payload",
            "updated_at",
        ]
    )
    if not invoice_url:
        return JsonResponse({"ok": False, "error": "missing_invoice_url"}, status=502)
    return JsonResponse({"ok": True, "invoice_url": invoice_url})


@csrf_exempt
@require_http_methods(["POST"])
def nowpayments_ipn_view(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    signature = request.headers.get("x-nowpayments-sig") or request.META.get("HTTP_X_NOWPAYMENTS_SIG", "")
    if not settings.NOWPAYMENTS_IPN_SECRET:
        logger.error("NOWPayments IPN received, but NOWPAYMENTS_IPN_SECRET is not configured.")
        return JsonResponse({"ok": False, "error": "nowpayments_not_configured"}, status=503)
    expected_signature = nowpayments_signature(payload)
    if not signature or not signatures_match(expected_signature, signature):
        logger.warning("Invalid NOWPayments IPN signature for payload order_id=%s", payload.get("order_id"))
        return JsonResponse({"ok": False, "error": "invalid_signature"}, status=400)

    order_id = str(payload.get("order_id") or "")
    invoice_id = str(payload.get("invoice_id") or "")
    payment_id = str(payload.get("payment_id") or payload.get("id") or "")
    filters = Q()
    if order_id:
        filters |= Q(order_id=order_id)
    if invoice_id:
        filters |= Q(provider_invoice_id=invoice_id)
    if payment_id:
        filters |= Q(provider_payment_id=payment_id)
    if not filters:
        return JsonResponse({"ok": False, "error": "missing_payment_reference"}, status=400)

    with transaction.atomic():
        purchase = Purchase.objects.select_for_update().filter(filters).order_by("-created_at").first()
        if not purchase:
            logger.warning("NOWPayments IPN received for unknown purchase: %s", payload)
            return JsonResponse({"ok": False, "error": "payment_not_found"}, status=404)

        previous_status = str(purchase.status or "").lower()
        status = str(payload.get("payment_status") or payload.get("status") or purchase.status).lower()
        amount_crypto = decimal_from_payload(payload.get("actually_paid") or payload.get("pay_amount"))
        purchase.status = status
        if payment_id:
            purchase.provider_payment_id = payment_id
        if invoice_id:
            purchase.provider_invoice_id = invoice_id
        if amount_crypto is not None:
            purchase.amount_crypto = amount_crypto
        purchase.tx_hash = str(payload.get("payin_hash") or payload.get("tx_hash") or purchase.tx_hash or "")
        purchase.raw_payload = payload
        purchase.save(
            update_fields=[
                "status",
                "provider_payment_id",
                "provider_invoice_id",
                "amount_crypto",
                "tx_hash",
                "raw_payload",
                "updated_at",
            ]
        )
        if status in NOWPAYMENTS_FINISHED_STATUSES and previous_status not in NOWPAYMENTS_FINISHED_STATUSES:
            activate_plan_from_purchase(purchase)
        elif status in NOWPAYMENTS_TERMINAL_FAILURE_STATUSES:
            logger.info("NOWPayments purchase %s ended with status %s", purchase.id, status)

    return JsonResponse({"ok": True})


def signatures_match(expected_signature, signature):
    import hmac

    return hmac.compare_digest(expected_signature, signature)
