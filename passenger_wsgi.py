"""Entrypoint Krystal's cPanel Python Selector (Phusion Passenger) looks for
by this exact filename -- config/wsgi.py (used by Railway's gunicorn) isn't
picked up by Passenger directly."""

from config.wsgi import application  # noqa: F401
