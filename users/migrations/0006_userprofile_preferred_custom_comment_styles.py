from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_userprofile_preferred_translate_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="preferred_custom_comment_styles",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
