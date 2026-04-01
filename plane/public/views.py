"""Public marketing page views."""

from django.shortcuts import render


def landing(request):
    return render(request, "public/landing.html")


def pricing(request):
    return render(request, "public/pricing.html")


def status(request):
    return render(request, "public/status.html")


def security(request):
    return render(request, "public/security.html")


def terms(request):
    return render(request, "legal/terms.html")


def privacy(request):
    return render(request, "legal/privacy.html")


def cookies(request):
    return render(request, "legal/cookies.html")


def docs(request):
    return render(request, "public/docs.html")


def sign_in(request, rest=None):
    """Sign-in page with embedded Clerk SignIn component."""
    return render(request, "auth/sign_in.html")


def sign_up(request, rest=None):
    """Sign-up page with embedded Clerk SignUp component."""
    return render(request, "auth/sign_up.html")
