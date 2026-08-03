from django.urls import path

from . import views

app_name = "matching"

urlpatterns = [
    path("", views.connect_view, name="connect"),

    # Step 2 — 1:1 matching
    path("find-friend/", views.find_friend_view, name="find_friend"),
    path("request/<int:request_id>/status/", views.match_status_view, name="match_status"),
    path("request/<int:request_id>/cancel/", views.cancel_match_request_view, name="cancel_request"),
    path("requests/incoming/", views.incoming_requests_view, name="incoming_requests"),
    path("request/<int:request_id>/accept/", views.accept_match_view, name="accept_match"),
    path("request/<int:request_id>/decline/", views.decline_match_view, name="decline_match"),

    # Step 3 — groups
    path("join-group/", views.join_group_view, name="join_group"),
    path("group/<int:group_id>/status/", views.group_status_view, name="group_status"),
    path("group/<int:group_id>/cancel-wait/", views.cancel_group_wait_view, name="cancel_group_wait"),

    # State recovery — asks the server what's actually still pending,
    # since JS state resets on every page navigation
    path("my-pending-state/", views.my_pending_state_view, name="my_pending_state"),

    # Step 4 — block
    path("block/<int:user_id>/", views.block_user_view, name="block_user"),
]
