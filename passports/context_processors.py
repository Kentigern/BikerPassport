from .access import is_site_admin


def dashboard_link(request):
    """Which dashboard a "Back to Dashboard" button on any other page
    should point to — mirrors the role logic in config/urls.py's
    root_redirect, so a Site Admin/superuser and a Passport Logger are
    always sent back to their own landing page, not a fixed one."""
    user = request.user
    if not user.is_authenticated:
        return {}
    if user.is_superuser or is_site_admin(user):
        return {'dashboard_url_name': 'dashboard'}
    return {'dashboard_url_name': 'landing'}
