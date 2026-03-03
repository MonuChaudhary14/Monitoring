from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import InfrastructureMetric, Server
from .serializers import InfrastructureMetricSerializer
from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg
from django.shortcuts import render

@api_view(['POST'])
def ingest_metric(request):
    server_id = request.data.get("server_id")
    try:
        server = Server.objects.get(id=server_id)
    except Server.DoesNotExist:
        return Response({"error": "Server not found"}, status=404)

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
    if last_metric:
        if timezone.now() - last_metric.timestamp < timedelta(seconds=15):
            status = "online"

    return Response({
        "metrics": data,
        "average_cpu": avg_cpu,
        "status": status
    })

def dashboard(request):
    return render(request, "monitoring/dashboard.html")