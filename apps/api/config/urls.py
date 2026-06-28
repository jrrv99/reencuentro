"""URLs raíz. La API va versionada bajo /api/v1/ desde el día uno."""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

# Todo lo de la v1 vive bajo este prefijo. El url_name del esquema queda dentro del
# namespace 'v1', por eso las vistas de docs lo referencian como 'v1:schema'.
api_v1 = [
    path("", include("personas.urls")),
    # OpenAPI (drf-spectacular)
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="v1:schema"),
        name="swagger-ui",
    ),
    path("redoc/", SpectacularRedocView.as_view(url_name="v1:schema"), name="redoc"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include((api_v1, "v1"), namespace="v1")),
]
