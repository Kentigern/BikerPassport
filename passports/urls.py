from django.urls import path

from . import views

urlpatterns = [
    path('submissions/new/', views.submission_form_view, name='submission_new'),
    path('submissions/<int:pk>/edit/', views.submission_form_view, name='submission_edit'),
    path('bearers/search/', views.bearer_search_view, name='bearer_search'),
]
