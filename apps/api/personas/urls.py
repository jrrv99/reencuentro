from rest_framework.routers import DefaultRouter

from .views import PersonaCanonicaViewSet

router = DefaultRouter()
router.register(r"personas", PersonaCanonicaViewSet, basename="persona")

urlpatterns = router.urls
