"""Tests de CRUD y permisos para instituciones, responders y claims."""
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from instituciones.models import Institucion, Responder
from personas.choices import AutorTipo, EstadoRep
from personas.models import EstadoClaim, PersonaCanonica, RegistroFuente

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _institucion(nombre="Hospital Vargas", tipo="hospital", verificada=False):
    return Institucion.objects.create(nombre=nombre, tipo=tipo, verificada=verificada)


def _user(email, password="Testpass123!"):
    return User.objects.create_user(
        username=email, email=email, password=password,
        first_name="Test", last_name="User",
    )


def _responder(email, institucion, rol="miembro", activo=True):
    user = _user(email)
    return Responder.objects.create(user=user, institucion=institucion, rol=rol, activo=activo)


def _token(client, email, password="Testpass123!"):
    r = client.post("/api/v1/auth/token/", {"username": email, "password": password})
    return r.data["access"]


def _persona():
    return PersonaCanonica.objects.create(nombre_display="Ana López", n_fuentes=1)


# ---------------------------------------------------------------------------
# Institución — CRUD
# ---------------------------------------------------------------------------

class InstitucionCRUDTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff = _user("staff@test.com")
        self.staff.is_staff = True
        self.staff.save()

    def test_list_publico(self):
        _institucion("Hospital A")
        _institucion("Hospital B")
        r = self.client.get("/api/v1/instituciones/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["results"]), 2)

    def test_retrieve_publico(self):
        inst = _institucion("Hospital Vargas")
        r = self.client.get(f"/api/v1/instituciones/{inst.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["nombre"], "Hospital Vargas")
        self.assertIn("n_responders", r.data)

    def test_create_requiere_staff(self):
        r = self.client.post("/api/v1/instituciones/", {"nombre": "X", "tipo": "hospital"})
        self.assertEqual(r.status_code, 401)

    def test_create_staff_ok(self):
        token = _token(self.client, "staff@test.com")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        r = self.client.post(
            "/api/v1/instituciones/",
            {"nombre": "Clínica Nueva", "tipo": "clinica", "zona": "Carabobo"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Institucion.objects.count(), 1)

    def test_patch_verificar_requiere_staff(self):
        inst = _institucion()
        r = self.client.patch(f"/api/v1/instituciones/{inst.id}/", {"verificada": True})
        self.assertEqual(r.status_code, 401)

    def test_patch_verificar_staff_ok(self):
        inst = _institucion()
        token = _token(self.client, "staff@test.com")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        r = self.client.patch(f"/api/v1/instituciones/{inst.id}/", {"verificada": True})
        self.assertEqual(r.status_code, 200)
        inst.refresh_from_db()
        self.assertTrue(inst.verificada)

    def test_delete_requiere_staff(self):
        inst = _institucion()
        r = self.client.delete(f"/api/v1/instituciones/{inst.id}/")
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# Responder — CRUD
# ---------------------------------------------------------------------------

class ResponderCRUDTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.inst = _institucion()
        self.admin_resp = _responder("admin@test.com", self.inst, rol="admin")
        self.miembro_resp = _responder("miembro@test.com", self.inst, rol="miembro")
        self.staff = _user("staff@test.com")
        self.staff.is_staff = True
        self.staff.save()

    def _auth(self, email):
        token = _token(self.client, email)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_list_requiere_responder(self):
        r = self.client.get("/api/v1/responders/")
        self.assertEqual(r.status_code, 401)

    def test_list_miembro_ve_su_institucion(self):
        otra_inst = _institucion("Otro Hospital")
        _responder("otro@test.com", otra_inst)
        self._auth("miembro@test.com")
        r = self.client.get("/api/v1/responders/")
        self.assertEqual(r.status_code, 200)
        emails = [res["email"] for res in r.data["results"]]
        self.assertIn("miembro@test.com", emails)
        self.assertIn("admin@test.com", emails)
        self.assertNotIn("otro@test.com", emails)

    def test_staff_ve_todos(self):
        otra_inst = _institucion("Otro Hospital")
        _responder("otro@test.com", otra_inst)
        self._auth("staff@test.com")
        r = self.client.get("/api/v1/responders/")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data["results"]), 3)

    def test_create_requiere_workspace_admin(self):
        self._auth("miembro@test.com")
        r = self.client.post(
            "/api/v1/responders/",
            {"email": "nuevo@test.com", "password": "Testpass123!", "first_name": "A", "last_name": "B"},
        )
        self.assertEqual(r.status_code, 403)

    def test_create_workspace_admin_ok(self):
        self._auth("admin@test.com")
        r = self.client.post(
            "/api/v1/responders/",
            {
                "email": "nuevo@test.com", "password": "Testpass123!",
                "first_name": "Pedro", "last_name": "García", "rol": "miembro",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Responder.objects.count(), 3)
        nuevo = Responder.objects.get(user__email="nuevo@test.com")
        self.assertEqual(nuevo.institucion, self.inst)

    def test_create_fuerza_propia_institucion(self):
        """Workspace admin no puede crear en otra institución."""
        otra = _institucion("Otra")
        self._auth("admin@test.com")
        r = self.client.post(
            "/api/v1/responders/",
            {
                "email": "infiltrado@test.com", "password": "Testpass123!",
                "first_name": "X", "last_name": "Y",
                "institucion": str(otra.id),
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        nuevo = Responder.objects.get(user__email="infiltrado@test.com")
        self.assertEqual(nuevo.institucion, self.inst)  # siempre la suya

    def test_destroy_soft_delete(self):
        self._auth("admin@test.com")
        r = self.client.delete(f"/api/v1/responders/{self.miembro_resp.id}/")
        self.assertEqual(r.status_code, 204)
        self.miembro_resp.refresh_from_db()
        self.assertFalse(self.miembro_resp.activo)


# ---------------------------------------------------------------------------
# RegistroFuente — escritura por responders
# ---------------------------------------------------------------------------

class RegistroFuenteResponderTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.inst = _institucion("Hospital Caracas", verificada=True)
        self.resp = _responder("doctor@test.com", self.inst)
        inst_no_verif = _institucion("Hospital Sin Verificar", verificada=False)
        self.resp_no_verif = _responder("novato@test.com", inst_no_verif)

    def _auth(self, email):
        token = _token(self.client, email)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_publico_no_puede_crear(self):
        r = self.client.post("/api/v1/registros/", {"tipo": "encontrado", "nombre": "X"})
        self.assertEqual(r.status_code, 401)

    def test_responder_crea_registro(self):
        self._auth("doctor@test.com")
        r = self.client.post(
            "/api/v1/registros/",
            {
                "tipo": "encontrado", "nombre": "María Pérez",
                "zona": "Caracas", "estado_rep": "hospitalizado",
                "ubicacion": "UCI piso 3",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        reg = RegistroFuente.objects.get()
        self.assertEqual(reg.tipo_fuente, "hospital")
        self.assertEqual(reg.confianza, 0.9)
        self.assertIn("hospital_", reg.fuente)
        self.assertNotIn("contacto", r.data)  # campo privado nunca en output

    def test_confianza_menor_no_verificada(self):
        self._auth("novato@test.com")
        r = self.client.post(
            "/api/v1/registros/",
            {"tipo": "encontrado", "nombre": "Pedro", "zona": "Valencia"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        reg = RegistroFuente.objects.get()
        self.assertEqual(reg.confianza, 0.7)

    def test_fallecido_requiere_institucion_verificada(self):
        self._auth("novato@test.com")
        r = self.client.post(
            "/api/v1/registros/",
            {"tipo": "encontrado", "nombre": "Test", "estado_rep": "fallecido"},
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_fallecido_institucion_verificada_ok(self):
        self._auth("doctor@test.com")
        r = self.client.post(
            "/api/v1/registros/",
            {"tipo": "encontrado", "nombre": "Test", "estado_rep": "fallecido"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)

    def test_contacto_privado_no_aparece_en_output(self):
        self._auth("doctor@test.com")
        r = self.client.post(
            "/api/v1/registros/",
            {
                "tipo": "buscado", "nombre": "Ana",
                "contacto": '{"telefono": "0412-1234567"}',
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertNotIn("contacto", r.data)
        reg = RegistroFuente.objects.get()
        self.assertIsNotNone(reg.contacto)  # guardado en DB


# ---------------------------------------------------------------------------
# EstadoClaim — escritura por responders
# ---------------------------------------------------------------------------

class EstadoClaimTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.inst_verif = _institucion("Hospital Verificado", verificada=True)
        self.inst_no_verif = _institucion("Hospital Sin Verificar", verificada=False)
        self.resp_verif = _responder("doctor@test.com", self.inst_verif)
        self.resp_no_verif = _responder("novato@test.com", self.inst_no_verif)
        self.persona = _persona()

    def _auth(self, email):
        token = _token(self.client, email)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_list_claims_publico(self):
        r = self.client.get("/api/v1/claims/")
        self.assertEqual(r.status_code, 200)

    def test_create_claim_requiere_responder(self):
        r = self.client.post(
            "/api/v1/claims/",
            {"persona": str(self.persona.id), "estado": "encontrado_vivo"},
        )
        self.assertEqual(r.status_code, 401)

    def test_create_claim_ok(self):
        self._auth("doctor@test.com")
        r = self.client.post(
            "/api/v1/claims/",
            {"persona": str(self.persona.id), "estado": "hospitalizado", "ubicacion": "UCI"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        claim = EstadoClaim.objects.get()
        self.assertEqual(claim.autor_tipo, AutorTipo.RESPONDER)
        self.assertEqual(claim.autor_responder_id, self.resp_verif.id)
        self.assertTrue(claim.vigente)

    def test_claim_actualiza_estado_actual_canonico(self):
        self._auth("doctor@test.com")
        self.client.post(
            "/api/v1/claims/",
            {"persona": str(self.persona.id), "estado": "encontrado_vivo"},
            format="json",
        )
        self.persona.refresh_from_db()
        self.assertEqual(self.persona.estado_actual, "encontrado_vivo")

    def test_fallecido_requiere_verificada(self):
        """Institución no verificada recibe 403 antes de cualquier validación de datos."""
        self._auth("novato@test.com")
        r = self.client.post(
            "/api/v1/claims/",
            {"persona": str(self.persona.id), "estado": "fallecido", "corrobora": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_fallecido_requiere_corrobora(self):
        """Institución verificada + sin corrobora → 400."""
        self._auth("doctor@test.com")
        r = self.client.post(
            "/api/v1/claims/",
            {"persona": str(self.persona.id), "estado": "fallecido"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("corrobora", r.data)

    def test_fallecido_verificada_con_corroboracion_ok(self):
        """Institución verificada + corrobora válido → 201."""
        self._auth("doctor@test.com")
        corrobora_claim = EstadoClaim.objects.create(
            persona=self.persona,
            estado=EstadoRep.ENCONTRADO_VIVO,
            autor_tipo=AutorTipo.SISTEMA,
        )
        r = self.client.post(
            "/api/v1/claims/",
            {
                "persona": str(self.persona.id),
                "estado": "fallecido",
                "corrobora": str(corrobora_claim.id),
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201)
