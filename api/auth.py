from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.middleware.csrf import get_token
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .diagnostics import CopilotError
from .serializers import UserSerializer
from .throttles import AuthThrottle


class CredentialsSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


@api_view(["GET"])
@permission_classes([AllowAny])
def me(request):
    get_token(request)  # makes Django set the CSRF cookie the frontend echoes back
    user = UserSerializer(request.user).data if request.user.is_authenticated else None
    return Response({"user": user})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def login_view(request):
    creds = CredentialsSerializer(data=request.data)
    creds.is_valid(raise_exception=True)
    user = authenticate(request, **creds.validated_data)
    if user is None:
        raise CopilotError("invalid_credentials", "Wrong username or password.", status=400)
    login(request, user)
    return Response({"user": UserSerializer(user).data})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def register(request):
    if not settings.ALLOW_REGISTRATION:
        raise CopilotError("registration_closed", "Sign-ups are closed.", status=403)
    creds = CredentialsSerializer(data=request.data)
    creds.is_valid(raise_exception=True)
    username, password = creds.validated_data["username"], creds.validated_data["password"]

    if User.objects.filter(username__iexact=username).exists():
        raise CopilotError("username_taken", "That username is already taken.")
    try:
        validate_password(password, user=User(username=username))
    except DjangoValidationError as exc:
        raise CopilotError("weak_password", " ".join(exc.messages)) from exc

    user = User.objects.create_user(username=username, password=password)
    login(request, user)
    return Response({"user": UserSerializer(user).data}, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
def logout_view(request):
    logout(request)
    return Response(status=204)
