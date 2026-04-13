from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_profile_preferences_and_purchase"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="preferred_comment_styles",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
