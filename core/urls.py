from django.urls import path

from . import payment_views, views


app_name = "core"

urlpatterns = [
    path("", views.landing_view, name="landing"),
    path("pricing/create-wallet-payment/", payment_views.create_wallet_payment_view, name="pricing_create_wallet_payment"),
    path("pricing/verify-wallet-payment/", payment_views.verify_wallet_payment_view, name="pricing_verify_wallet_payment"),
    path("pricing/create-payment/", payment_views.create_nowpayments_invoice_view, name="pricing_create_payment"),
    path("payments/nowpayments/ipn/", payment_views.nowpayments_ipn_view, name="nowpayments_ipn"),
    path("dashboard/", views.profile_view, name="dashboard"),
    path("profile/", views.profile_view, name="profile"),
]
