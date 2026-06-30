from rest_framework.routers import DefaultRouter

from .views import PersonaCanonicaViewSet, RegistroFuenteViewSet

router = DefaultRouter()
router.register(r"personas", PersonaCanonicaViewSet, basename="persona")
router.register(r"registros", RegistroFuenteViewSet, basename="registro")

urlpatterns = router.urls
