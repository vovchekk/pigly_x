from django.conf import settings
from django.db import models


class GenerationRequest(models.Model):
    KIND_SHORTEN = "shorten"
    KIND_REPLY = "reply"
    KIND_CHOICES = (
        (KIND_SHORTEN, "Shorten"),
        (KIND_REPLY, "Reply"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="generation_requests")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    source_text = models.TextField()
    tone = models.CharField(max_length=32, blank=True)
    request_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} - {self.kind} - {self.created_at:%Y-%m-%d %H:%M}"


class GenerationResult(models.Model):
    request = models.ForeignKey(GenerationRequest, on_delete=models.CASCADE, related_name="results")
    content = models.TextField()
    position = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.request_id} #{self.position}"
