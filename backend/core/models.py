from django.db import models

class ApiKey(models.Model):
    user = models.CharField(max_length=50, unique=True)
    key = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return f"{self.user}"