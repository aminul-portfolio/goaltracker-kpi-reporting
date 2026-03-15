# apps/goals/rbac.py
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect


def require_login(view_func):
    """
    Phase-1 gate: if GOALTRACKER_REQUIRE_LOGIN True, user must be authenticated.
    Otherwise allow (dev/local mode).
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if getattr(settings, "GOALTRACKER_REQUIRE_LOGIN", False):
            if not request.user.is_authenticated:
                messages.error(request, "Please sign in to access this page.")
                return redirect("admin:login")
        return view_func(request, *args, **kwargs)
    return _wrapped


def require_staff(view_func):
    """
    Phase-1 gate for 'admin-grade' pages (exports).
    If GOALTRACKER_EXPORTS_REQUIRE_STAFF True, require request.user.is_staff.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if getattr(settings, "GOALTRACKER_EXPORTS_REQUIRE_STAFF", False):
            if not request.user.is_authenticated:
                messages.error(request, "Please sign in to access this page.")
                return redirect("admin:login")
            if not request.user.is_staff:
                messages.error(request, "Not permitted.")
                return redirect("dashboard:home")
        return view_func(request, *args, **kwargs)
    return _wrapped
