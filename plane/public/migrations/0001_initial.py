# Generated manually for the public app.

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DigestPilotLead",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("email", models.EmailField(max_length=254)),
                ("company", models.CharField(max_length=160)),
                ("role", models.CharField(blank=True, max_length=120)),
                ("document_types", models.CharField(blank=True, max_length=240)),
                ("deployment_target", models.CharField(blank=True, max_length=32)),
                ("timeline", models.CharField(blank=True, max_length=32)),
                ("use_case", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "New"),
                            ("contacted", "Contacted"),
                            ("qualified", "Qualified"),
                            ("closed", "Closed"),
                        ],
                        default="new",
                        max_length=32,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "digest_pilot_leads",
                "ordering": ["-created_at"],
            },
        ),
    ]
