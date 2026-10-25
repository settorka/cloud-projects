import pytest
from django.contrib.auth.models import User, Group
from rest_framework.test import APIClient
from app.models import ConsumerGuard


@pytest.fixture
def user(db):
    user = User.objects.create_user(username="test-trader")
    group, _ = Group.objects.get_or_create(name="trader")
    user.groups.add(group)
    return user


@pytest.fixture
def client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def event_guard(db):
    ConsumerGuard.objects.get_or_create(name="events")
