from django.db import models
 
 
class Boletin(models.Model):
    """Boletín vigente: una sola fila por año, que se reemplaza en cada subida."""
 
    anio = models.PositiveIntegerField(unique=True)
    filas = models.JSONField()
    actualizado = models.DateTimeField(auto_now=True)
 
    def __str__(self):
        return f"Boletín {self.anio} ({self.actualizado:%d-%m-%Y %H:%M})"
 