from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PlanAccess, User, UserProfile


@receiver(post_save, sender=User)
def ensure_profile_and_plan(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)
        PlanAccess.objects.get_or_create(user=instance)
