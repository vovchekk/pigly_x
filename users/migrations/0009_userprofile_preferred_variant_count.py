from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_planaccess_expires_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="preferred_variant_count",
            field=models.PositiveSmallIntegerField(choices=[(1, "1"), (2, "2"), (3, "3")], default=3),
        ),
    ]
