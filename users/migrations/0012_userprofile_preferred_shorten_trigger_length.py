from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0011_planaccess_generation_blocked_until"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="preferred_shorten_trigger_length",
            field=models.PositiveIntegerField(default=280),
        ),
    ]
