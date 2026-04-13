import json

from django import forms
from django.contrib.auth import authenticate, get_user_model

from .models import UserProfile, generate_random_username


User = get_user_model()


class CustomAuthenticationForm(forms.Form):
    username = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

    def clean(self):
        cleaned_data = super().clean()
        email = (cleaned_data.get("username") or "").strip()
        password = cleaned_data.get("password") or ""

        if email and password:
            self.user = authenticate(email=email, password=password)
            if self.user is None:
                raise forms.ValidationError("Неверный email или пароль.")
        return cleaned_data

    def get_user(self):
        return getattr(self, "user", None)


class CustomUserCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirm = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email",)

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже существует.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "Пароли не совпадают.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = generate_random_username()
        user.email = self.cleaned_data["email"]
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class UserProfileForm(forms.ModelForm):
    LANGUAGE_CHOICES = (
        ("ru", "Russian"),
        ("en", "English"),
    )
    TONE_CHOICES = (
        ("friendly", "Friendly"),
        ("neutral", "Neutral"),
        ("concise", "Concise"),
        ("confident", "Confident"),
    )

    preferred_language = forms.ChoiceField(choices=LANGUAGE_CHOICES)
    preferred_tone = forms.ChoiceField(choices=TONE_CHOICES)
    preferred_comment_styles_json = forms.CharField(required=False, widget=forms.HiddenInput)
    preferred_custom_comment_styles_json = forms.CharField(required=False, widget=forms.HiddenInput)
    preferred_translate_language = forms.ChoiceField(choices=UserProfile.TRANSLATE_CHOICES, required=False)
    preferred_comment_length = forms.ChoiceField(choices=UserProfile.LENGTH_CHOICES)
    preferred_emoji_mode = forms.ChoiceField(choices=UserProfile.EMOJI_CHOICES)
    preferred_dash_style = forms.ChoiceField(choices=UserProfile.DASH_CHOICES)
    preferred_terminal_punctuation = forms.ChoiceField(choices=UserProfile.PUNCT_CHOICES)
    preferred_capitalization = forms.ChoiceField(choices=UserProfile.CAPS_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["preferred_comment_styles_json"].initial = json.dumps(self.instance.selected_comment_styles)
            self.fields["preferred_custom_comment_styles_json"].initial = json.dumps(self.instance.custom_comment_styles)

    def _parse_json_list(self, field_name):
        raw = (self.cleaned_data.get(field_name) or "").strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise forms.ValidationError("Invalid style payload.")
        if not isinstance(value, list):
            raise forms.ValidationError("Invalid style payload.")
        return value

    def clean(self):
        cleaned_data = super().clean()
        selected = self._parse_json_list("preferred_comment_styles_json")
        custom = self._parse_json_list("preferred_custom_comment_styles_json")
        valid_preset_ids = {value for value, _ in UserProfile.COMMENT_STYLE_CHOICES}
        valid_custom_ids = set()
        normalized_custom = []
        for item in custom:
            if not isinstance(item, dict):
                continue
            style_id = str(item.get("id") or "").strip()
            label = str(item.get("label") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            description = str(item.get("description") or "").strip()
            if not (style_id.startswith("custom-") and label and prompt):
                continue
            valid_custom_ids.add(style_id)
            normalized_custom.append(
                {
                    "id": style_id,
                    "label": label[:32],
                    "description": description[:160],
                    "prompt": prompt[:800],
                }
            )

        normalized_selected = [style_id for style_id in selected if style_id in valid_preset_ids or style_id in valid_custom_ids]
        deduped_selected = []
        for style_id in normalized_selected:
            if style_id not in deduped_selected:
                deduped_selected.append(style_id)

        if not deduped_selected:
            raise forms.ValidationError("Select at least one style.")

        cleaned_data["parsed_preferred_comment_styles"] = deduped_selected
        cleaned_data["parsed_preferred_custom_comment_styles"] = normalized_custom
        return cleaned_data

    def save(self, commit=True):
        profile = super().save(commit=False)
        styles = self.cleaned_data["parsed_preferred_comment_styles"]
        profile.preferred_comment_styles = styles
        profile.preferred_custom_comment_styles = self.cleaned_data["parsed_preferred_custom_comment_styles"]
        profile.preferred_tone = UserProfile.map_style_to_tone(styles[0])
        if commit:
            profile.save()
        return profile

    class Meta:
        model = UserProfile
        fields = (
            "preferred_language",
            "preferred_tone",
            "preferred_comment_styles_json",
            "preferred_custom_comment_styles_json",
            "preferred_translate_language",
            "preferred_comment_length",
            "preferred_emoji_mode",
            "preferred_dash_style",
            "preferred_terminal_punctuation",
            "preferred_capitalization",
        )
