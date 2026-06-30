from rest_framework.routers import DefaultRouter

from .views import EstadoClaimViewSet, InstitucionViewSet, ResponderViewSet

router = DefaultRouter()
router.register(r"instituciones", InstitucionViewSet, basename="institucion")
router.register(r"responders", ResponderViewSet, basename="responder")
router.register(r"claims", EstadoClaimViewSet, basename="claim")

urlpatterns = router.urls
