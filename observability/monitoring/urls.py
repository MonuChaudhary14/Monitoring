from django.urls import path
from .views import (
    api_activity,
    dashboard,
    dashboard_data,
    get_metrics,
    ingest_metric,
    ingest_logs,
    list_servers,
    register_server,
    system_summary,
)

urlpatterns = [
    path('ingest/', ingest_metric),
    path('ingest-logs/', ingest_logs),
    path('metrics/', get_metrics),
    path('dashboard/', dashboard),
    path('dashboard-data/', dashboard_data),
    path('register/', register_server),
    path('servers/', list_servers),
    path('system-summary/', system_summary),
    path('api-activity/', api_activity),
]
