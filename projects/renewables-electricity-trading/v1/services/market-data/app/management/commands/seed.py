import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from rest_framework.authtoken.models import Token
from app.models import ConsumerGuard


class Command(BaseCommand):
    help = "Idempotently seed local identities and service control rows"

    def handle(self, *args, **options):
        ConsumerGuard.objects.get_or_create(name="events")
        for role in ["trader", "risk", "viewer"]:
            user, _ = User.objects.get_or_create(username=role)
            user.set_unusable_password()
            user.save()
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)
            key = os.environ[f"{role.upper()}_TOKEN"]
            if len(key) != 40:
                raise ValueError("Demo API tokens must be 40 characters")
            existing = Token.objects.filter(user=user).first()
            if existing and existing.key != key:
                existing.delete()
            Token.objects.get_or_create(user=user, defaults={"key": key})
        from app.domain import seed_domain

        seed_domain()
        self.stdout.write("Local identities and domain seeded")
