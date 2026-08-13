from django.contrib.auth.models import AbstractUser
from django.db import models


class University(models.Model):
    domain = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class User(AbstractUser):
    email = models.EmailField(unique=True)
    google_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    university = models.ForeignKey(
        University, on_delete=models.SET_NULL, null=True, blank=True, related_name='users'
    )
    is_verified = models.BooleanField(default=False)
    suspended_until = models.DateTimeField(null=True, blank=True)
    is_banned = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)


class Profile(models.Model):
    GENDER_CHOICES = [('Male', 'Male'), ('Female', 'Female')]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField(max_length=255)
    country = models.CharField(max_length=100, null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    primary_language = models.CharField(max_length=50, null=True, blank=True)
    secondary_language = models.CharField(max_length=50, null=True, blank=True)
    auto_translate = models.BooleanField(default=False)
    translate_into = models.CharField(max_length=50, null=True, blank=True)
    profile_setup_complete = models.BooleanField(default=False)

    def __str__(self):
        return self.display_name
