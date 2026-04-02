# Generated manually — adds signing_key_hash for HMAC verification.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_add_composite_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="apikey",
            name="signing_key_hash",
            field=models.CharField(max_length=128, null=True, blank=True),
        ),
    ]
