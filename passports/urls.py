from django.urls import path

from . import views

urlpatterns = [
    path('', views.landing_view, name='landing'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('raffle/export/', views.raffle_export_view, name='raffle_export'),
    path('raffle/draw/', views.raffle_draw_view, name='raffle_draw'),
    path('raffle/draw/spin/', views.raffle_draw_spin_view, name='raffle_draw_spin'),
    path('audit-log/', views.audit_log_view, name='audit_log'),
    path('submissions/new/', views.submission_form_view, name='submission_new'),
    path('submissions/<int:pk>/edit/', views.submission_form_view, name='submission_edit'),
    path('submissions/save/', views.submission_save_view, name='submission_save'),
    path('bearers/search/', views.bearer_search_view, name='bearer_search'),
    path('bearers/save/', views.bearer_save_view, name='bearer_save'),
    path('emails/', views.email_campaign_list_view, name='email_campaign_list'),
    path('emails/new/', views.email_campaign_form_view, name='email_campaign_new'),
    path('emails/<int:pk>/edit/', views.email_campaign_form_view, name='email_campaign_edit'),
    path(
        'emails/recipient-count/',
        views.email_campaign_recipient_count_view,
        name='email_campaign_recipient_count',
    ),
    path('emails/<int:pk>/preview/', views.email_campaign_preview_view, name='email_campaign_preview'),
    path('emails/<int:pk>/send/', views.email_campaign_send_view, name='email_campaign_send'),
    path('emails/<int:pk>/status/', views.email_campaign_status_view, name='email_campaign_status'),
    path(
        'emails/<int:pk>/status.json',
        views.email_campaign_status_json_view,
        name='email_campaign_status_json',
    ),
    path(
        'email/unsubscribe/<uuid:token>/<str:purpose>/',
        views.email_unsubscribe_view,
        name='email_unsubscribe',
    ),
]
