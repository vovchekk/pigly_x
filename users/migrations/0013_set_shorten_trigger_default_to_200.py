from django.db import migrations, models


def migrate_default_shorten_trigger_to_200(apps, schema_editor):
    UserProfile = apps.get_model("users", "UserProfile")
    UserProfile.objects.filter(preferred_shorten_trigger_length=280).update(preferred_shorten_trigger_length=200)


def revert_default_shorten_trigger_to_280(apps, schema_editor):
    UserProfile = apps.get_model("users", "UserProfile")
    UserProfile.objects.filter(preferred_shorten_trigger_length=200).update(preferred_shorten_trigger_length=280)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0012_userprofile_preferred_shorten_trigger_length"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="preferred_shorten_trigger_length",
            field=models.PositiveIntegerField(default=200),
        ),
        migrations.RunPython(
            migrate_default_shorten_trigger_to_200,
            revert_default_shorten_trigger_to_280,
        ),
    ]
