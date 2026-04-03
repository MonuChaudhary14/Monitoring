from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import InfrastructureMetric, Server, Alert
from .serializers import InfrastructureMetricSerializer
from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg
from django.shortcuts import render

@api_view(['POST'])
def ingest_metric(request):
    api_key = request.headers.get("X-API-KEY")

    if not api_key:
        return Response({"error": "API key required"}, status=401)

    try:
        server = Server.objects.get(api_key=api_key)
    except Server.DoesNotExist:
        return Response({"error": "Invalid API key"}, status=403)

    data = request.data.copy()
    data['server'] = server.id

    serializer = InfrastructureMetricSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return Response({"status": "Metric stored"})

    return Response(serializer.errors, status=400)

@api_view(['GET'])
def get_metrics(request):
    server_id = request.GET.get("server")
    minutes = int(request.GET.get("minutes", 5))

    if not server_id:
        return Response({"error": "Server ID required"}, status=400)

    time_threshold = timezone.now() - timedelta(minutes=minutes)

    metrics = InfrastructureMetric.objects.filter(
        server_id=server_id,
        timestamp__gte=time_threshold
    ).order_by("timestamp")

    data = [
        {
            "timestamp": m.timestamp,
            "cpu": m.cpu_percent,
            "memory": m.memory_percent,
            "disk": m.disk_percent,
        }
        for m in metrics
    ]

    avg_cpu = metrics.aggregate(Avg("cpu_percent"))["cpu_percent__avg"]

    last_metric = InfrastructureMetric.objects.filter(
        server_id=server_id
    ).order_by("-timestamp").first()

    status = "offline"
    if last_metric and timezone.now() - last_metric.timestamp < timedelta(seconds=15):
        status = "online"

    high_cpu_threshold = 80
    sustained_duration = timedelta(seconds=60)

    recent_high_cpu = InfrastructureMetric.objects.filter(
        server_id=server_id,
        cpu_percent__gt=high_cpu_threshold,
        timestamp__gte=timezone.now() - sustained_duration
    )

    active_alert = Alert.objects.filter(
        server_id=server_id,
        resolved=False,
        message__contains="CPU usage high"
    ).first()

    if recent_high_cpu.exists():
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

    active_alerts = Alert.objects.filter(
        server_id=server_id,
        resolved=False
    ).values("message", "severity", "triggered_at")

    return Response({
        "metrics": data,
        "average_cpu": avg_cpu,
        "status": status,
        "alerts": list(active_alerts)
    })


def dashboard(request):
    return render(request, "monitoring/dashboard.html")