from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('setup/', views.profile_setup_view, name='profile_setup'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/delete/', views.delete_account_view, name='delete_account'),
    path('profile/update-name/', views.update_display_name_view, name='update_display_name'),
    path('profile/toggle-translate/', views.toggle_auto_translate_view, name='toggle_auto_translate'),
    path('profile/update-translate-into/', views.update_translate_into_view, name='update_translate_into'),
]
