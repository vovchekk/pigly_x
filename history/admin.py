from django.contrib import admin

from .models import GenerationRequest, GenerationResult


@admin.register(GenerationRequest)
class GenerationRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "tone", "created_at")
    search_fields = ("user__email", "source_text")


@admin.register(GenerationResult)
class GenerationResultAdmin(admin.ModelAdmin):
    list_display = ("request", "position")
