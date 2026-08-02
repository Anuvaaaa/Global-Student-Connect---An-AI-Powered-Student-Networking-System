from django.urls import path

from . import views

app_name = 'social'

urlpatterns = [
    path('home/', views.feed_view, name='home'),
    path('post/create/', views.create_post_view, name='create_post'),
    path('post/<int:post_id>/like/', views.toggle_like_view, name='toggle_like'),
    path('post/<int:post_id>/comment/', views.add_comment_view, name='add_comment'),
    path('comment/<int:comment_id>/delete/', views.delete_comment_view, name='delete_comment'),
    path('post/<int:post_id>/delete/', views.delete_post_view, name='delete_post'),
]
