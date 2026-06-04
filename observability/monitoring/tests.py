from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import APIRequestLog, Alert, InfrastructureMetric, Server


class MetricIngestionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.server = Server.objects.create(name="web-01", ip_address="10.0.0.1")
        self.url = "/api/ingest/"

    def _broadcast_recorder(self):
        broadcasts = []

        def fake_group_send(group_name, event):
            broadcasts.append((group_name, event))

        return broadcasts, SimpleNamespace(group_send=fake_group_send)

    def test_ingest_metric_broadcasts_metric_and_summary_updates(self):
        broadcasts, fake_layer = self._broadcast_recorder()

        payload = {
            "cpu_percent": 42.5,
            "memory_percent": 61.2,
            "disk_percent": 73.9,
        }

        with patch("monitoring.views.get_channel_layer", return_value=fake_layer), patch(
            "monitoring.views.async_to_sync", side_effect=lambda fn: fn
        ):
            response = self.client.post(
                self.url,
                payload,
                format="json",
                HTTP_X_API_KEY=str(self.server.api_key),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(InfrastructureMetric.objects.count(), 1)
        self.assertEqual(len(broadcasts), 2)

        metric_event = broadcasts[0][1]
        summary_event = broadcasts[1][1]

        self.assertEqual(metric_event["type"], "metric_update")
        self.assertEqual(metric_event["data"]["type"], "metric_update")
        self.assertEqual(metric_event["data"]["server"], self.server.name)

        self.assertEqual(summary_event["type"], "summary_update")
        self.assertEqual(summary_event["data"]["type"], "summary_update")
        self.assertEqual(summary_event["data"]["status"], "online")
        self.assertEqual(summary_event["data"]["active_alerts"], 0)

    def test_ingest_metric_broadcasts_alert_when_high_cpu_persists(self):
        old_metric = InfrastructureMetric.objects.create(
            server=self.server,
            cpu_percent=95,
            memory_percent=55,
            disk_percent=60,
        )
        InfrastructureMetric.objects.filter(pk=old_metric.pk).update(
            timestamp=timezone.now() - timedelta(seconds=30)
        )

        broadcasts, fake_layer = self._broadcast_recorder()

        with patch("monitoring.views.get_channel_layer", return_value=fake_layer), patch(
            "monitoring.views.async_to_sync", side_effect=lambda fn: fn
        ):
            response = self.client.post(
                self.url,
                {
                    "cpu_percent": 96,
                    "memory_percent": 58,
                    "disk_percent": 62,
                },
                format="json",
                HTTP_X_API_KEY=str(self.server.api_key),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Alert.objects.count(), 1)
        self.assertEqual(len(broadcasts), 3)

        alert_event = broadcasts[1][1]
        summary_event = broadcasts[2][1]

        self.assertEqual(alert_event["type"], "alert_update")
        self.assertEqual(alert_event["data"]["type"], "alert_update")
        self.assertEqual(alert_event["data"]["severity"], "HIGH")
        self.assertFalse(alert_event["data"]["resolved"])

        self.assertEqual(summary_event["type"], "summary_update")
        self.assertEqual(summary_event["data"]["active_alerts"], 1)

    def test_ingest_metric_logs_api_request(self):
        response = self.client.post(
            self.url,
            {
                "cpu_percent": 55,
                "memory_percent": 44,
                "disk_percent": 66,
            },
            format="json",
            HTTP_X_API_KEY=str(self.server.api_key),
        )

        self.assertEqual(response.status_code, 200)
        log = APIRequestLog.objects.get(endpoint="/api/ingest/")
        self.assertEqual(log.method, "POST")
        self.assertEqual(log.status_code, 200)
        self.assertEqual(log.source, "agent")
        self.assertEqual(log.server, self.server)

    def test_ingest_metric_logs_forwarded_ip_address(self):
        self.client.post(
            self.url,
            {
                "cpu_percent": 55,
                "memory_percent": 44,
                "disk_percent": 66,
            },
            format="json",
            HTTP_X_API_KEY=str(self.server.api_key),
            HTTP_X_FORWARDED_FOR="203.0.113.10, 10.0.0.5",
        )

        log = APIRequestLog.objects.get(endpoint="/api/ingest/")
        self.assertEqual(log.ip_address, "203.0.113.10")

    def test_ingest_metric_ignores_invalid_forwarded_ip_address(self):
        self.client.post(
            self.url,
            {
                "cpu_percent": 55,
                "memory_percent": 44,
                "disk_percent": 66,
            },
            format="json",
            HTTP_X_API_KEY=str(self.server.api_key),
            HTTP_X_FORWARDED_FOR="unknown",
        )

        log = APIRequestLog.objects.get(endpoint="/api/ingest/")
        self.assertIsNone(log.ip_address)


class MonitoringApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.server = Server.objects.create(name="app-01", ip_address="10.0.0.8")
        self.other_server = Server.objects.create(name="db-01", ip_address="10.0.0.9")

        current_metric = InfrastructureMetric.objects.create(
            server=self.server,
            cpu_percent=64,
            memory_percent=51,
            disk_percent=72,
        )
        InfrastructureMetric.objects.filter(pk=current_metric.pk).update(
            timestamp=timezone.now() - timedelta(seconds=5)
        )

        stale_metric = InfrastructureMetric.objects.create(
            server=self.other_server,
            cpu_percent=22,
            memory_percent=48,
            disk_percent=31,
        )
        InfrastructureMetric.objects.filter(pk=stale_metric.pk).update(
            timestamp=timezone.now() - timedelta(minutes=2)
        )

        Alert.objects.create(
            server=self.server,
            message="CPU usage high for more than 1 minute",
            severity="HIGH",
        )

    def test_list_servers_returns_status_for_each_server(self):
        response = self.client.get("/api/servers/")

        self.assertEqual(response.status_code, 200)
        data = response.json()["servers"]
        status_by_name = {server["name"]: server["status"] for server in data}

        self.assertEqual(status_by_name["app-01"], "online")
        self.assertEqual(status_by_name["db-01"], "offline")

    def test_system_summary_returns_counts(self):
        response = self.client.get("/api/system-summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "total_servers": 2,
                "active_servers": 1,
                "inactive_servers": 1,
                "active_alerts": 1,
            },
        )

    def test_dashboard_data_includes_metrics_alerts_and_activity(self):
        self.client.get("/api/system-summary/")
        self.client.get("/api/servers/")

        response = self.client.get(
            f"/api/dashboard-data/?server={self.server.id}&minutes=15",
            HTTP_REFERER="http://testserver/api/dashboard/",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["selected_server"]["id"], self.server.id)
        self.assertEqual(payload["system_summary"]["active_servers"], 1)
        self.assertEqual(len(payload["metrics"]["metrics"]), 1)
        self.assertEqual(payload["metrics"]["status"], "online")
        self.assertEqual(payload["metrics"]["alerts"][0]["message"], "CPU usage high for more than 1 minute")
        self.assertGreaterEqual(len(payload["api_activity"]["recent_requests"]), 2)
        self.assertTrue(
            any(hit["endpoint"] == "/api/system-summary/" for hit in payload["api_activity"]["endpoint_hits"])
        )
        self.assertTrue(APIRequestLog.objects.filter(endpoint="/api/dashboard-data/").exists())

    def test_api_activity_lists_recent_requests(self):
        self.client.get("/api/servers/", REMOTE_ADDR="192.168.1.40")
        self.client.get("/api/system-summary/")

        response = self.client.get("/api/api-activity/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        endpoints = {entry["endpoint"] for entry in payload["recent_requests"]}

        self.assertIn("/api/servers/", endpoints)
        self.assertIn("/api/system-summary/", endpoints)
        self.assertTrue(
            any(hit["endpoint"] == "/api/servers/" and hit["ip_address"] == "192.168.1.40" for hit in payload["endpoint_hits"])
        )
        self.assertTrue(APIRequestLog.objects.filter(endpoint="/api/api-activity/").exists())

    def test_dashboard_data_rejects_invalid_minutes(self):
        response = self.client.get(f"/api/dashboard-data/?server={self.server.id}&minutes=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Minutes must be a number")

    def test_register_server_rejects_invalid_ip_address(self):
        response = self.client.post(
            "/api/register/",
            {"name": "bad-host", "ip_address": "999.1.1.1"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Invalid IP address")
