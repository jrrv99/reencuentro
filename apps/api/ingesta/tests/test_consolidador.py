"""Tests del conector del consolidador (ingesta/connectors/consolidador.py).

Tests clave:
- Idempotencia: 2ª corrida → 0 insertados, 0 actualizados.
- Campo cambiado → 1 actualizado, 0 nuevos.
- cedula_norm correcto (V-9.810.928 → "9810928").
- Cédula no es única: dos registros con la misma cédula se insertan.
- Campos privados → contacto (nunca al serializer público).
- tipo derivado del estado.
- SyncRun registra la corrida con contadores correctos.
"""
import json
from pathlib import Path

from django.test import TestCase

from ingesta.connectors.consolidador import (
    CENTINELAS_CEDULA,
    IngestaParseError,
    compute_content_hash,
    ingest_file,
    normalizar_centinela,
)
from ingesta.models import SyncRun
from ingesta.tasks import ingesta_consolidador
from personas.models import RegistroFuente

FIXTURE = (
    Path(__file__).parent / "fixtures" / "consolidador_sample.json"
)
TOTAL_REGISTROS = 4  # registros en el fixture


class IdempotenciaTests(TestCase):
    """La clave de correctitud: dos corridas sobre los mismos datos = 0 cambios."""

    def test_primera_corrida_inserta_todos(self):
        stats = ingest_file(FIXTURE)
        self.assertEqual(stats.insertados, TOTAL_REGISTROS)
        self.assertEqual(stats.actualizados, 0)
        self.assertEqual(stats.sin_cambio, 0)
        self.assertEqual(stats.errores, 0)
        self.assertEqual(RegistroFuente.objects.count(), TOTAL_REGISTROS)

    def test_segunda_corrida_es_todo_sin_cambio(self):
        ingest_file(FIXTURE)
        stats = ingest_file(FIXTURE)
        self.assertEqual(stats.insertados, 0, "2ª corrida no debe insertar nada")
        self.assertEqual(stats.actualizados, 0, "2ª corrida no debe actualizar nada")
        self.assertEqual(stats.sin_cambio, TOTAL_REGISTROS)
        # La DB no crece.
        self.assertEqual(RegistroFuente.objects.count(), TOTAL_REGISTROS)

    def test_campo_cambiado_produce_uno_actualizado(self):
        ingest_file(FIXTURE)
        # Modificar el estado de Juan Pérez (id=111...): Desaparecido → Encontrado.
        with FIXTURE.open() as f:
            data = json.load(f)
        data[0]["estado"] = "Encontrado"

        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False)
            tmp_path = tmp.name

        try:
            stats = ingest_file(tmp_path)
            self.assertEqual(stats.actualizados, 1)
            self.assertEqual(stats.insertados, 0)
            self.assertEqual(stats.sin_cambio, TOTAL_REGISTROS - 1)
            # Verificar que el campo se actualizó.
            reg = RegistroFuente.objects.get(fuente="dtv", id_origen="111111111111111111")
            self.assertEqual(reg.estado_rep, "encontrado_vivo")
            self.assertEqual(reg.tipo, "encontrado")
        finally:
            os.unlink(tmp_path)


class CedulaNormTests(TestCase):
    def setUp(self):
        ingest_file(FIXTURE)

    def test_cedula_norm_elimina_no_digitos(self):
        """V-9.810.928 → '9810928'."""
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="111111111111111111")
        self.assertEqual(reg.cedula, "V-9.810.928")
        self.assertEqual(reg.cedula_norm, "9810928")

    def test_cedula_extranjero_norm(self):
        """E-81.234.567 → '81234567'."""
        reg = RegistroFuente.objects.get(fuente="vtb", id_origen="444444444444444444")
        self.assertEqual(reg.cedula_norm, "81234567")

    def test_cedula_nula_norm_vacia(self):
        """Sin cédula → cedula_norm = '' (string vacío, por el coalesce)."""
        reg = RegistroFuente.objects.get(fuente="vtb", id_origen="222222222222222222")
        self.assertIsNone(reg.cedula)
        self.assertEqual(reg.cedula_norm, "")

    def test_cedula_no_es_unica(self):
        """Dos registros con la misma cédula deben coexistir sin error."""
        regs = RegistroFuente.objects.filter(cedula_norm="9810928")
        self.assertEqual(regs.count(), 2, "Registros 111... y 333... tienen la misma cédula")


class MapeoTests(TestCase):
    def setUp(self):
        ingest_file(FIXTURE)

    def test_tipo_buscado_para_desaparecido(self):
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="111111111111111111")
        self.assertEqual(reg.estado_rep, "sin_contacto")
        self.assertEqual(reg.tipo, "buscado")

    def test_tipo_encontrado_para_hospitalizado(self):
        reg = RegistroFuente.objects.get(fuente="vtb", id_origen="222222222222222222")
        self.assertEqual(reg.estado_rep, "hospitalizado")
        self.assertEqual(reg.tipo, "encontrado")

    def test_tipo_encontrado_para_encontrado(self):
        reg = RegistroFuente.objects.get(fuente="vtb", id_origen="444444444444444444")
        self.assertEqual(reg.estado_rep, "encontrado_vivo")
        self.assertEqual(reg.tipo, "encontrado")

    def test_ubicacion_vs_blob_rescate(self):
        """ultima_ubicacion con blob de rescate: ubicación real separada del blob."""
        reg = RegistroFuente.objects.get(fuente="vtb", id_origen="222222222222222222")
        self.assertEqual(reg.ubicacion, "Hospital Universitario de Caracas")
        self.assertIn("DATOS CRÍTICOS", reg.descripcion)

    def test_raw_payload_es_el_registro_crudo(self):
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="111111111111111111")
        self.assertEqual(reg.raw_payload["id"], "111111111111111111")
        self.assertEqual(reg.raw_payload["fuente"], "dtv")


class PrivacidadTests(TestCase):
    """Los campos privados van a contacto; NUNCA aparecen en el serializer público."""

    def setUp(self):
        ingest_file(FIXTURE)

    def test_campos_privados_van_a_contacto(self):
        """telefono_contacto, encontrado_por, etc. deben estar en contacto (JSON)."""
        reg = RegistroFuente.objects.get(fuente="vtb", id_origen="222222222222222222")
        self.assertIsNotNone(reg.contacto)
        contacto = json.loads(reg.contacto)
        self.assertIn("telefono_contacto", contacto)
        self.assertEqual(contacto["telefono_contacto"], "0212-9876543")
        self.assertEqual(contacto["encontrado_por"], "Dr. Rodríguez")
        self.assertEqual(contacto["encontrado_por_cedula"], "V-8.500.000")

    def test_registro_sin_privados_tiene_contacto_nulo(self):
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="333333333333333333")
        # Solo tiene telefono_contacto=null → no hay privados → contacto=None
        self.assertIsNone(reg.contacto)

    def test_privados_no_aparecen_en_api_publica(self):
        """Verificar que el serializer público no filtra datos del campo contacto.

        El serializer lee PersonaCanonica, no RegistroFuente directamente.
        El campo contacto de RegistroFuente no está en ningún serializer público.
        """
        from django.conf import settings
        from django.test import override_settings
        from rest_framework.test import APIClient

        rf_sin_throttle = {
            **settings.REST_FRAMEWORK,
            "DEFAULT_THROTTLE_CLASSES": [],
            "DEFAULT_THROTTLE_RATES": {},
        }
        client = APIClient()
        with override_settings(REST_FRAMEWORK=rf_sin_throttle):
            resp = client.get("/api/v1/personas/")
        blob = json.dumps(resp.json())
        self.assertNotIn("0414-1234567", blob, "telefono_contacto filtrado al público")
        self.assertNotIn("0212-9876543", blob, "telefono_contacto filtrado al público")
        self.assertNotIn("Dr. Rodríguez", blob, "encontrado_por filtrado al público")
        self.assertNotIn("contacto", blob, "campo contacto expuesto")


class SyncRunTests(TestCase):
    def test_task_crea_syncrun_y_registra_contadores(self):
        result = ingesta_consolidador(archivo=str(FIXTURE))
        self.assertEqual(SyncRun.objects.count(), 1)
        run = SyncRun.objects.get()
        self.assertEqual(run.insertados, TOTAL_REGISTROS)
        self.assertEqual(run.actualizados, 0)
        self.assertEqual(run.sin_cambio, 0)
        self.assertEqual(run.errores, 0)
        self.assertIsNotNone(run.terminada_at)
        # El resultado de la tarea es consistente con el SyncRun.
        self.assertEqual(result["insertados"], TOTAL_REGISTROS)

    def test_segunda_corrida_syncrun_refleja_sin_cambio(self):
        ingesta_consolidador(archivo=str(FIXTURE))
        ingesta_consolidador(archivo=str(FIXTURE))
        self.assertEqual(SyncRun.objects.count(), 2)
        run2 = SyncRun.objects.order_by("-iniciada_at").first()
        self.assertEqual(run2.insertados, 0)
        self.assertEqual(run2.sin_cambio, TOTAL_REGISTROS)


class ContentHashTests(TestCase):
    def test_hash_excluye_fecha_actualizacion(self):
        record_a = {"id": "1", "nombre": "Juan", "fecha_actualizacion": "2026-01-01"}
        record_b = {"id": "1", "nombre": "Juan", "fecha_actualizacion": "2026-06-30"}
        self.assertEqual(
            compute_content_hash(record_a),
            compute_content_hash(record_b),
            "fecha_actualizacion no debe afectar el hash",
        )

    def test_hash_cambia_si_cambia_nombre(self):
        record_a = {"id": "1", "nombre": "Juan"}
        record_b = {"id": "1", "nombre": "Pedro"}
        self.assertNotEqual(compute_content_hash(record_a), compute_content_hash(record_b))

    def test_usa_content_hash_del_json_si_existe(self):
        record = {"id": "1", "nombre": "Juan", "content_hash": "abc123"}
        self.assertEqual(compute_content_hash(record), "abc123")

    def test_hash_no_cambia_al_normalizar_centinelas(self):
        """La limpieza de centinelas ocurre en _map_record, no toca el input del hash."""
        record = {
            "id": "1",
            "fuente": "dtv",
            "cedula": "No registrado",
            "nombre": "Test",
        }
        hash_antes = compute_content_hash(record)
        # Simular que _map_record es llamado (normaliza la cédula internamente)
        from ingesta.connectors.consolidador import _map_record
        _map_record(record)
        # El dict original no debe haber sido modificado
        self.assertEqual(record["cedula"], "No registrado")
        # El hash sigue siendo el mismo
        hash_despues = compute_content_hash(record)
        self.assertEqual(hash_antes, hash_despues)


# ---------------------------------------------------------------------------
# Tests del nuevo fixture: centinelas, es_menor, ubicacion con coma
# ---------------------------------------------------------------------------

FIXTURE_CENTINELAS = (
    Path(__file__).parent / "fixtures" / "consolidador_centinelas.json"
)
# 5 registros únicos por (fuente, id_origen); el 6º es duplicado del 2º.
DISTINTOS_CENTINELAS = 5


class NormalizarCentinelaTests(TestCase):
    """normalizar_centinela() — función pura, sin DB."""

    def test_centinela_conocido_devuelve_none(self):
        for val in ["No registrado", "NO REGISTRADO", "  no registrado  ", "n/a", "N/A",
                    "na", "desconocido", "sin cedula", "sin cédula", "ninguno", ""]:
            with self.subTest(val=val):
                self.assertIsNone(normalizar_centinela(val), f"'{val}' debe → None")

    def test_cedula_real_pasa_intacta(self):
        for val in ["37099131", "V-12.345.678", "E-81.234.567", "12345678"]:
            with self.subTest(val=val):
                self.assertEqual(normalizar_centinela(val), val)

    def test_none_pasa_como_none(self):
        self.assertIsNone(normalizar_centinela(None))

    def test_centinelas_personalizadas(self):
        custom = frozenset({"raro"})
        self.assertIsNone(normalizar_centinela("raro", centinelas=custom))
        # "no registrado" no es centinela con el set personalizado
        self.assertEqual(
            normalizar_centinela("no registrado", centinelas=custom), "no registrado"
        )

    def test_set_de_centinelas_es_configurable(self):
        """Verifica que CENTINELAS_CEDULA es la fuente de configuración."""
        self.assertIn("no registrado", CENTINELAS_CEDULA)
        self.assertIn("sin cédula", CENTINELAS_CEDULA)


class CentinelaDBTests(TestCase):
    """Centinelas en el flujo real de ingesta → DB."""

    def setUp(self):
        ingest_file(FIXTURE_CENTINELAS)

    def test_centinela_no_registrado_almacena_none(self):
        """'No registrado' → cedula=None en DB (no el string)."""
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="aaa1111111111111111")
        self.assertIsNone(reg.cedula)

    def test_centinela_cedula_norm_vacia(self):
        """Si cedula=None, cedula_norm generado por DB = ''."""
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="aaa1111111111111111")
        self.assertEqual(reg.cedula_norm, "")

    def test_centinela_raw_payload_preserva_original(self):
        """El raw_payload conserva 'No registrado' original — la limpieza no lo toca."""
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="aaa1111111111111111")
        self.assertEqual(reg.raw_payload["cedula"], "No registrado")

    def test_digitos_sin_prefijo_se_preservan(self):
        """'37099131' (sin V/E) → cedula='37099131', cedula_norm='37099131'."""
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="bbb2222222222222222")
        self.assertEqual(reg.cedula, "37099131")
        self.assertEqual(reg.cedula_norm, "37099131")

    def test_prefijo_y_puntos_cedula_norm(self):
        """'V-12.345.678' → cedula_norm='12345678'."""
        reg = RegistroFuente.objects.get(fuente="vtb", id_origen="ccc3333333333333333")
        self.assertEqual(reg.cedula, "V-12.345.678")
        self.assertEqual(reg.cedula_norm, "12345678")

    def test_tres_sin_digitos_tienen_cedula_norm_vacia(self):
        """Centinela, null, y otro null → cedula_norm vacío en los 3 casos."""
        centinela = RegistroFuente.objects.get(fuente="dtv", id_origen="aaa1111111111111111")
        nulo = RegistroFuente.objects.get(fuente="vtb", id_origen="ddd4444444444444444")
        self.assertEqual(centinela.cedula_norm, "")
        self.assertEqual(nulo.cedula_norm, "")
        # Los que tienen cédula real sí tienen cedula_norm no vacío.
        real = RegistroFuente.objects.get(fuente="dtv", id_origen="bbb2222222222222222")
        self.assertTrue(bool(real.cedula_norm))


class EdadYMenorTests(TestCase):
    def setUp(self):
        ingest_file(FIXTURE_CENTINELAS)

    def test_edad_null_se_almacena_null(self):
        """edad=null en JSON → edad=None en DB, no 0 ni False."""
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="aaa1111111111111111")
        self.assertIsNone(reg.edad)

    def test_edad_numerica_se_preserva(self):
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="bbb2222222222222222")
        self.assertEqual(reg.edad, 15)

    def test_es_menor_en_raw_payload(self):
        """es_menor=true (bool) se preserva en raw_payload, no se castea."""
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="bbb2222222222222222")
        self.assertIs(reg.raw_payload["es_menor"], True)

    def test_registro_sin_es_menor_no_tiene_el_campo_en_payload(self):
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="aaa1111111111111111")
        self.assertNotIn("es_menor", reg.raw_payload)


class UbicacionConComaTests(TestCase):
    def setUp(self):
        ingest_file(FIXTURE_CENTINELAS)

    def test_ubicacion_con_coma_se_preserva_intacta(self):
        """Sin marcador de rescate: ultima_ubicacion completa va a ubicacion sin truncar."""
        reg = RegistroFuente.objects.get(fuente="vtb", id_origen="ddd4444444444444444")
        self.assertEqual(
            reg.ubicacion,
            "Conjunto Residencial Las Acacias, La Guaira, Vargas",
        )
        self.assertIsNone(reg.descripcion)

    def test_observaciones_tipo_avistamiento_van_a_descripcion(self):
        """Observaciones largas (claim) se almacenan en descripcion intactas."""
        reg = RegistroFuente.objects.get(fuente="dtv", id_origen="eee5555555555555555")
        self.assertIn("Fue visto el 2 de julio", reg.descripcion)
        self.assertIn("parecía desorientado", reg.descripcion)


class IdempotenciaFixturaCentinelasTests(TestCase):
    def test_primera_corrida_inserta_distintos_y_sin_cambio_duplicado(self):
        """Primera corrida: 5 insertados (únicos) + 1 sin_cambio (el duplicado interno)."""
        stats = ingest_file(FIXTURE_CENTINELAS)
        self.assertEqual(stats.insertados, DISTINTOS_CENTINELAS)
        self.assertEqual(stats.sin_cambio, 1)
        self.assertEqual(stats.errores, 0)
        self.assertEqual(RegistroFuente.objects.count(), DISTINTOS_CENTINELAS)

    def test_segunda_corrida_todo_sin_cambio(self):
        """Segunda corrida: 0 insertados, 0 actualizados, 6 sin_cambio."""
        ingest_file(FIXTURE_CENTINELAS)
        stats = ingest_file(FIXTURE_CENTINELAS)
        self.assertEqual(stats.insertados, 0)
        self.assertEqual(stats.actualizados, 0)
        self.assertEqual(stats.sin_cambio, 6)  # 5 únicos + 1 duplicado
        self.assertEqual(RegistroFuente.objects.count(), DISTINTOS_CENTINELAS)


class JSONInvalidoTests(TestCase):
    """JSON mal formado → IngestaParseError con posición + SyncRun.fallida=True."""

    def _archivo_invalido(self, contenido: str) -> str:
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write(contenido)
        return f.name

    def test_ingest_file_lanza_error_con_posicion(self):
        path = self._archivo_invalido('[{"id": "1", "fuente": "dtv",}]')  # coma final
        try:
            with self.assertRaises(IngestaParseError) as ctx:
                ingest_file(path)
            msg = str(ctx.exception)
            self.assertIn("línea", msg)
            self.assertIn("columna", msg)
        finally:
            import os
            os.unlink(path)

    def test_ingest_file_no_inserta_nada_antes_de_abortar(self):
        path = self._archivo_invalido('no es json')
        try:
            with self.assertRaises(IngestaParseError):
                ingest_file(path)
            self.assertEqual(RegistroFuente.objects.count(), 0)
        finally:
            import os
            os.unlink(path)

    def test_task_marca_syncrun_fallida(self):
        """ingesta_consolidador marca run.fallida=True y guarda error_msg."""
        path = self._archivo_invalido('{"esto": "no es array"}')
        try:
            with self.assertRaises(IngestaParseError):
                ingesta_consolidador(archivo=path)
        finally:
            import os
            os.unlink(path)

        run = SyncRun.objects.get()
        self.assertTrue(run.fallida)
        self.assertIsNotNone(run.error_msg)
        self.assertEqual(RegistroFuente.objects.count(), 0)

    def test_task_json_invalido_syncrun_fallida_con_posicion(self):
        """error_msg del SyncRun incluye información de posición."""
        path = self._archivo_invalido('[{roto')
        try:
            with self.assertRaises(IngestaParseError):
                ingesta_consolidador(archivo=path)
        finally:
            import os
            os.unlink(path)

        run = SyncRun.objects.get()
        self.assertTrue(run.fallida)
        self.assertIn("línea", run.error_msg)
