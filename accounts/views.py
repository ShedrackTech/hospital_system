from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import render

from .forms import LoginForm


class PortalLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
def dashboard(request):
    # Placeholder. Role-based dashboards come later.
    # Data is always loaded from request.user, never from an ID in the URL.
    return render(request, "accounts/dashboard.html", {"user": request.user})
