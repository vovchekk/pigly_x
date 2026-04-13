from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_extensionaccesstoken"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="preferred_capitalization",
            field=models.CharField(
                choices=[("upper", "Uppercase"), ("preserve", "Preserve"), ("mix", "Mix")],
                default="upper",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="preferred_comment_length",
            field=models.CharField(
                choices=[("short", "Short"), ("medium", "Medium"), ("long", "Long"), ("mix", "Mix")],
                default="mix",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="preferred_dash_style",
            field=models.CharField(
                choices=[("hyphen", "Hyphen -"), ("ndash", "En dash -"), ("mdash", "Em dash -")],
                default="ndash",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="preferred_emoji_mode",
            field=models.CharField(
                choices=[("none", "None"), ("moderate", "Moderate"), ("many", "Many"), ("mix", "Mix")],
                default="moderate",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="preferred_terminal_punctuation",
            field=models.CharField(
                choices=[("none", "No period"), ("keep", "Keep"), ("mix", "Mix")],
                default="none",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="planaccess",
            name="plan",
            field=models.CharField(
                choices=[("free", "Free"), ("pro", "Pro"), ("supporter", "Supporter")],
                default="free",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="Purchase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plan", models.CharField(choices=[("free", "Free"), ("pro", "Pro"), ("supporter", "Supporter")], default="pro", max_length=16)),
                ("amount_usd", models.DecimalField(decimal_places=2, max_digits=10)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("paid", "Paid"), ("cancelled", "Cancelled")], default="pending", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="purchases", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
