from django.http import HttpResponse

# PLACEHOLDER — delete this whole file once Person B's real social/views.py
# (feed_view, create_post_view, toggle_like_view, add_comment_view) lands.
# This exists only so base.html's {% url 'social:home' %} has somewhere
# valid to resolve to while accounts/engagement templates are being tested
# in isolation.


def home_placeholder(request):
    return HttpResponse("social app — not built yet")
