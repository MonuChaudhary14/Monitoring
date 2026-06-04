from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import APIRequestLog, InfrastructureMetric, Server, Alert
from .serializers import InfrastructureMetricSerializer
from .consumers import METRICS_GROUP_NAME
from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg, Count
from django.shortcuts import render
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import ipaddress
from django.utils.dateparse import parse_datetime


def broadcast_event(event_type, payload):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        METRICS_GROUP_NAME,
        {
            "type": event_type,
            "data": payload,
        },
    )


def build_metric_payload(metric):
    return {
        "type": "metric_update",
        "server_id": metric.server_id,
        "server": metric.server.name,
        "cpu": metric.cpu_percent,
        "memory": metric.memory_percent,
        "disk": metric.disk_percent,
        "timestamp": metric.timestamp.isoformat(),
    }


def build_alert_payload(server, message, severity, resolved=False):
    return {
        "type": "alert_update",
        "server_id": server.id,
        "server": server.name,
        "message": message,
        "severity": severity,
        "resolved": resolved,
        "timestamp": timezone.now().isoformat(),
    }


def build_summary_payload(server):
    recent_window = timezone.now() - timedelta(minutes=5)
    recent_metrics = InfrastructureMetric.objects.filter(
        server=server,
        timestamp__gte=recent_window,
    )

    aggregates = recent_metrics.aggregate(
        avg_cpu=Avg("cpu_percent"),
        avg_memory=Avg("memory_percent"),
        avg_disk=Avg("disk_percent"),
    )

    last_metric = InfrastructureMetric.objects.filter(server=server).order_by("-timestamp").first()
    server_online = bool(
        last_metric and timezone.now() - last_metric.timestamp < timedelta(seconds=15)
    )

    return {
        "type": "summary_update",
        "server_id": server.id,
        "server": server.name,
        "avg_cpu": aggregates["avg_cpu"],
        "avg_memory": aggregates["avg_memory"],
        "avg_disk": aggregates["avg_disk"],
        "active_alerts": Alert.objects.filter(server=server, resolved=False).count(),
        "status": "online" if server_online else "offline",
        "timestamp": timezone.now().isoformat(),
    }

def get_server_status(server):
    last_metric = InfrastructureMetric.objects.filter(server=server).order_by("-timestamp").first()
    if last_metric and timezone.now() - last_metric.timestamp < timedelta(seconds=15):
        return "online"
    return "offline"


def get_system_summary_data():
    total_servers = Server.objects.count()
    active_servers = sum(
        1 for server in Server.objects.all() if get_server_status(server) == "online"
    )

    return {
        "total_servers": total_servers,
        "active_servers": active_servers,
        "inactive_servers": total_servers - active_servers,
        "active_alerts": Alert.objects.filter(resolved=False).count(),
    }


def get_recent_activity_data(limit=20):
    recent_logs = APIRequestLog.objects.select_related("server")[:limit]
    return [
        {
            "endpoint": log.endpoint,
            "method": log.method,
            "status_code": log.status_code,
            "source": log.source,
            "server": log.server.name if log.server else None,
            "ip_address": log.ip_address,
            "requested_at": log.requested_at.isoformat(),
        }
        for log in recent_logs
    ]


def get_endpoint_hit_counts(limit=6):
    return list(
        APIRequestLog.objects.values("endpoint", "ip_address")
        .annotate(count=Count("id"))
        .order_by("-count", "endpoint", "ip_address")[:limit]
    )


def parse_minutes(request):
    try:
        minutes = int(request.GET.get("minutes", 5))
    except (TypeError, ValueError):
        raise ValueError("Minutes must be a number")

    if minutes <= 0:
        raise ValueError("Minutes must be greater than zero")

    return min(minutes, 24 * 60)


@api_view(['POST'])
def ingest_metric(request):
    api_key = request.headers.get("X-API-KEY")

    if not api_key:
        return Response({"error": "API key required"}, status=401)

    try:
        server = Server.objects.get(api_key=api_key)
    except Server.DoesNotExist:
        return Response({"error": "Invalid API key"}, status=403)

    request.monitoring_server = server

    data = request.data.copy()
    data['server'] = server.id

    serializer = InfrastructureMetricSerializer(data=data)

    if serializer.is_valid():
        metric = serializer.save()
        broadcast_event("metric_update", build_metric_payload(metric))

        high_cpu_threshold = 80
        sustained_duration = timedelta(seconds=60)

        recent_high_cpu = InfrastructureMetric.objects.filter(
            server=server,
            cpu_percent__gt=high_cpu_threshold,
            timestamp__gte=timezone.now() - sustained_duration
        )

        active_alert = Alert.objects.filter(
            server=server,
            resolved=False,
            message__contains="CPU usage high"
        ).first()

        if recent_high_cpu.exists():
            if not active_alert:
                alert = Alert.objects.create(
                    server=server,
                    message="CPU usage high for more than 1 minute",
                    severity="HIGH"
                )

                broadcast_event(
                    "alert_update",
                    build_alert_payload(
                        server=server,
                        message=alert.message,
                        severity=alert.severity,
                    ),
                )
        else:
            if active_alert:
                active_alert.resolved = True
                active_alert.save()

                broadcast_event(
                    "alert_update",
                    build_alert_payload(
                        server=server,
                        message="CPU back to normal",
                        severity="RESOLVED",
                        resolved=True,
                    ),
                )

        broadcast_event("summary_update", build_summary_payload(server))
        return Response({"status": "Metric stored"})

    return Response(serializer.errors, status=400)


@api_view(['POST'])
def ingest_logs(request):
    api_key = request.headers.get("X-API-KEY")

    if not api_key:
        return Response({"error": "API key required"}, status=401)

    try:
        server = Server.objects.get(api_key=api_key)
    except Server.DoesNotExist:
        return Response({"error": "Invalid API key"}, status=403)

    logs = request.data.get("logs", [])
    if not isinstance(logs, list):
        return Response({"error": "Invalid logs format"}, status=400)

    log_objects = []
    for log_data in logs:
        # Optionally parse requested_at if provided
        req_time = timezone.now()
        if "requested_at" in log_data and log_data["requested_at"]:
            parsed = parse_datetime(log_data["requested_at"])
            if parsed:
                req_time = parsed

        log_objects.append(APIRequestLog(
            server=server,
            endpoint=str(log_data.get("endpoint", ""))[:100],
            method=str(log_data.get("method", ""))[:10],
            status_code=int(log_data.get("status_code", 0)),
            source=str(log_data.get("source", "external"))[:50],
            ip_address=log_data.get("ip_address"),
            requested_at=req_time,
        ))

    APIRequestLog.objects.bulk_create(log_objects, batch_size=500)

    # Trigger a broadcast so the dashboard updates
    broadcast_event("summary_update", build_summary_payload(server))

    return Response({"status": f"{len(log_objects)} logs stored"})


@api_view(['GET'])
def get_metrics(request):
    server_id = request.GET.get("server")
    try:
        minutes = parse_minutes(request)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)

    if not server_id:
        return Response({"error": "Server ID required"}, status=400)

    server = Server.objects.filter(id=server_id).first()
    if not server:
        return Response({"error": "Server not found"}, status=404)

    request.monitoring_server = server

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

    active_alerts = Alert.objects.filter(
        server_id=server_id,
        resolved=False
    ).values("message", "severity", "triggered_at")

    return Response({
        "metrics": data,
        "average_cpu": avg_cpu,
        "status": get_server_status(server),
        "alerts": list(active_alerts)
    })


@api_view(['POST'])
def register_server(request):
    name = request.data.get("name")
    ip_address = request.data.get("ip_address")

    if not name or not ip_address:
        return Response({"error": "Missing fields"}, status=400)

    try:
        normalized_ip = str(ipaddress.ip_address(ip_address))
    except ValueError:
        return Response({"error": "Invalid IP address"}, status=400)

    existing = Server.objects.filter(name=name, ip_address=normalized_ip).first()

    if existing:
        request.monitoring_server = existing
        return Response({
            "api_key": str(existing.api_key),
            "message": "Server already registered"
        })

    server = Server.objects.create(
        name=name,
        ip_address=normalized_ip
    )
    request.monitoring_server = server

    return Response({
        "api_key": str(server.api_key),
        "message": "Server registered"
    })


@api_view(['GET'])
def list_servers(request):
    servers = [
        {
            "id": server.id,
            "name": server.name,
            "ip_address": server.ip_address,
            "status": get_server_status(server),
        }
        for server in Server.objects.all().order_by("name")
    ]
    return Response({"servers": servers})


@api_view(['GET'])
def system_summary(request):
    return Response(get_system_summary_data())


@api_view(['GET'])
def api_activity(request):
    return Response(
        {
            "recent_requests": get_recent_activity_data(),
            "endpoint_hits": get_endpoint_hit_counts(),
        }
    )


@api_view(['GET'])
def dashboard_data(request):
    try:
        minutes = parse_minutes(request)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)

    selected_server = None
    server_id = request.GET.get("server")
    if server_id:
        selected_server = Server.objects.filter(id=server_id).first()
    if not selected_server:
        selected_server = Server.objects.order_by("name").first()

    metrics_response = {"metrics": [], "average_cpu": None, "status": "offline", "alerts": []}

    if selected_server:
        time_threshold = timezone.now() - timedelta(minutes=minutes)
        metrics = InfrastructureMetric.objects.filter(
            server=selected_server,
            timestamp__gte=time_threshold,
        ).order_by("timestamp")
        metrics_response = {
            "server_id": selected_server.id,
            "metrics": [
                {
                    "timestamp": metric.timestamp.isoformat(),
                    "cpu": metric.cpu_percent,
                    "memory": metric.memory_percent,
                    "disk": metric.disk_percent,
                }
                for metric in metrics
            ],
            "average_cpu": metrics.aggregate(Avg("cpu_percent"))["cpu_percent__avg"],
            "status": get_server_status(selected_server),
            "alerts": list(
                Alert.objects.filter(server=selected_server).order_by("-triggered_at").values(
                    "message", "severity", "triggered_at", "resolved"
                )[:10]
            ),
        }

    if selected_server:
        request.monitoring_server = selected_server

    return Response(
        {
            "system_summary": get_system_summary_data(),
            "servers": [
                {
                    "id": server.id,
                    "name": server.name,
                    "ip_address": server.ip_address,
                    "status": get_server_status(server),
                }
                for server in Server.objects.all().order_by("name")
            ],
            "selected_server": (
                {
                    "id": selected_server.id,
                    "name": selected_server.name,
                    "ip_address": selected_server.ip_address,
                }
                if selected_server
                else None
            ),
            "metrics": metrics_response,
            "api_activity": {
                "recent_requests": get_recent_activity_data(),
                "endpoint_hits": get_endpoint_hit_counts(),
            },
        }
    )


def dashboard(request):
    return render(request, "monitoring/dashboard.html")
