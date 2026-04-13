from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_userprofile_preferred_comment_styles"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="preferred_translate_language",
            field=models.CharField(
                blank=True,
                choices=[("", "Not selected"), ("en", "English"), ("ru", "Russian"), ("zh", "Chinese")],
                default="",
                max_length=8,
            ),
        ),
    ]
