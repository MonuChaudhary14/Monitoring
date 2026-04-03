from django.db import models
import uuid


class Server(models.Model):
    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
    api_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class InfrastructureMetric(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    cpu_percent = models.FloatField()
    memory_percent = models.FloatField()
    disk_percent = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['server', 'timestamp']),
        ]


class Alert(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    message = models.CharField(max_length=255)
    severity = models.CharField(max_length=50, default="HIGH")
    triggered_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.server.name} - {self.message}"