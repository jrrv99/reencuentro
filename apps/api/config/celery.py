"""App de Celery. Aún sin tareas: los conectores de ingesta y el motor de dedup
(que corren como tareas) llegan en hitos siguientes. Esto es el esqueleto que respira."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("reencuentro")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
