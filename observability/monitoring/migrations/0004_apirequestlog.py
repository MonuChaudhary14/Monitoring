import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitoring", "0003_server_api_key"),
    ]

    operations = [
        migrations.CreateModel(
            name="APIRequestLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("endpoint", models.CharField(max_length=100)),
                ("method", models.CharField(max_length=10)),
                ("status_code", models.PositiveSmallIntegerField()),
                ("source", models.CharField(default="external", max_length=20)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                (
                    "server",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="monitoring.server"),
                ),
            ],
            options={
                "ordering": ["-requested_at"],
                "indexes": [models.Index(fields=["endpoint", "requested_at"], name="monitoring_endpoint_91a9d0_idx")],
            },
        ),
    ]
