from rest_framework import serializers
from .models import InfrastructureMetric

class InfrastructureMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = InfrastructureMetric
        fields = '__all__'