"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path, reverse

from passports.access import is_site_admin


def root_redirect(request):
    """Routes by role rather than a single fixed destination — a
    superuser's post-login `next` shouldn't get hijacked into the
    intake-only landing page meant for Passport Logger-type staff.
    Site Admin permission is checked first and overrides the
    superuser branch too — a superuser who's also a Site Admin still
    lands on the dashboard, not the raw admin index."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('admin:login')}?next=/")
    if is_site_admin(request.user):
        return redirect('dashboard')
    if request.user.is_superuser:
        return redirect('admin:index')
    return redirect('landing')


urlpatterns = [
    path('', root_redirect),
    path('admin/', admin.site.urls),
    path('passports/', include('passports.urls')),
]
