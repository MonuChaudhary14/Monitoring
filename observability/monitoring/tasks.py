from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import InfrastructureMetric, Alert

@shared_task
def check_cpu_alerts():
    high_cpu_threshold = 80
    duration = timedelta(seconds=60)

    servers = InfrastructureMetric.objects.values_list('server', flat=True).distinct()

    for server_id in servers:
        recent_high = InfrastructureMetric.objects.filter(
            server_id=server_id,
            cpu_percent__gt=high_cpu_threshold,
            timestamp__gte=timezone.now() - duration
        )

        active_alert = Alert.objects.filter(
            server_id=server_id,
            resolved=False,
            message__contains="CPU usage high"
        ).first()

        if recent_high.exists():
            if not active_alert:
                Alert.objects.create(
                    server_id=server_id,
                    message="CPU usage high for more than 1 minute",
                    severity="HIGH"
                )
        else:
            if active_alert:
                active_alert.resolved = True
                active_alert.save()