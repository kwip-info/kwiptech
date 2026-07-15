from django.db import models


class DigestPilotLead(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        QUALIFIED = "qualified", "Qualified"
        CLOSED = "closed", "Closed"

    name = models.CharField(max_length=120)
    email = models.EmailField()
    company = models.CharField(max_length=160)
    role = models.CharField(max_length=120, blank=True)
    document_types = models.CharField(max_length=240, blank=True)
    deployment_target = models.CharField(max_length=32, blank=True)
    timeline = models.CharField(max_length=32, blank=True)
    use_case = models.TextField()
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.NEW,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "digest_pilot_leads"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.company} - {self.name}"
