from django.http import HttpResponse

# PLACEHOLDER — delete this whole file once Person C's real matching/views.py
# (connect_view, send/accept/decline, join_group_view, block_user_view)
# lands. Exists only so base.html's {% url 'matching:connect' %} resolves.


def connect_placeholder(request):
    return HttpResponse("matching app — not built yet")
