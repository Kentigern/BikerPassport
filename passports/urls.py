from django.urls import path

from . import views

urlpatterns = [
    path('', views.landing_view, name='landing'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('raffle/export/', views.raffle_export_view, name='raffle_export'),
    path('submissions/new/', views.submission_form_view, name='submission_new'),
    path('submissions/<int:pk>/edit/', views.submission_form_view, name='submission_edit'),
    path('submissions/save/', views.submission_save_view, name='submission_save'),
    path('bearers/search/', views.bearer_search_view, name='bearer_search'),
    path('bearers/save/', views.bearer_save_view, name='bearer_save'),
]
