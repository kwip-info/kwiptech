from django import forms


class DigestPilotForm(forms.Form):
    name = forms.CharField(max_length=120)
    email = forms.EmailField()
    company = forms.CharField(max_length=160)
    role = forms.CharField(max_length=120, required=False)
    document_types = forms.CharField(
        max_length=240,
        required=False,
        help_text="Examples: PDFs, DOCX, scanned images, ZIP archives",
    )
    deployment_target = forms.ChoiceField(
        choices=[
            ("", "Select one"),
            ("docker", "Single Docker host"),
            ("kubernetes", "Kubernetes"),
            ("aws", "AWS"),
            ("azure", "Azure"),
            ("gcp", "GCP"),
            ("other", "Other"),
        ],
        required=False,
    )
    timeline = forms.ChoiceField(
        choices=[
            ("", "Select one"),
            ("now", "Now"),
            ("30_days", "Next 30 days"),
            ("quarter", "This quarter"),
            ("research", "Researching"),
        ],
        required=False,
    )
    use_case = forms.CharField(widget=forms.Textarea, max_length=2000)
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_website(self) -> str:
        value = self.cleaned_data.get("website", "")
        if value:
            raise forms.ValidationError("Invalid submission.")
        return value
