from django.conf import settings
from django.db import migrations, models


def seed_promocodes(apps, schema_editor):
    PromoCode = apps.get_model("users", "PromoCode")
    seed_data = [
        ("BROSKILUDOSKI", "pro", 30, 5),
        ("ZOLOTOKABAN", "pro", 30, 5),
        ("VALERKAPOZORNIK", "pro", 30, 5),
        ("STASIKLOX", "pro", 20, 5),
    ]
    for code, plan, duration_days, max_activations in seed_data:
        PromoCode.objects.update_or_create(
            code=code,
            defaults={
                "plan": plan,
                "duration_days": duration_days,
                "max_activations": max_activations,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0006_userprofile_preferred_custom_comment_styles"),
    ]

    operations = [
        migrations.CreateModel(
            name="PromoCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=64, unique=True)),
                ("plan", models.CharField(choices=[("free", "Free"), ("pro", "Pro"), ("supporter", "Supporter")], default="pro", max_length=16)),
                ("duration_days", models.PositiveIntegerField(default=30)),
                ("max_activations", models.PositiveIntegerField(default=1)),
                ("activations_count", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="PromoCodeRedemption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("granted_until", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("promo_code", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="redemptions", to="users.promocode")),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="promo_redemptions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"], "unique_together": {("promo_code", "user")}},
        ),
        migrations.RunPython(seed_promocodes, migrations.RunPython.noop),
    ]
