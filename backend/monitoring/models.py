from django.db import models

class Server(models.Model):
    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
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