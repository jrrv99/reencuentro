"""Clases de permiso para el anillo de acceso de responders (plan §8)."""
from rest_framework.permissions import BasePermission


class IsResponderActivo(BasePermission):
    """El usuario tiene un perfil Responder activo."""

    message = "Se requiere una cuenta de responder activa."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and hasattr(request.user, "responder")
            and request.user.responder.activo
        )


class IsWorkspaceAdmin(IsResponderActivo):
    """Responder con rol 'admin' en su workspace."""

    message = "Se requiere rol de admin en el workspace."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.responder.rol == "admin"


class IsInstitucionVerificada(IsResponderActivo):
    """Responder de una institución marcada como verificada.

    Requerido para acciones sensibles: registrar fallecido, confirmar identidad, etc.
    """

    message = "Esta acción requiere institución verificada por un administrador."

    def has_permission(self, request, view):
        return (
            super().has_permission(request, view)
            and request.user.responder.institucion.verificada
        )
