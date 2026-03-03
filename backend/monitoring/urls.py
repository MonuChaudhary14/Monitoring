from django.urls import path
from .views import ingest_metric,get_metrics, dashboard

urlpatterns = [
    path('ingest/', ingest_metric),
    path('metrics/', get_metrics),
    path('dashboard/', dashboard),
]