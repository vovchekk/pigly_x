from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0013_set_shorten_trigger_default_to_200"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="preferred_inline_translate_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
