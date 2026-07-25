from django.http import HttpResponse

# PLACEHOLDER — delete this whole file once Person C's real chat/views.py
# (inbox_view, conversation_view, group_conversation_view, send_message_view)
# lands. Exists only so base.html's {% url 'chat:inbox' %} resolves.


def inbox_placeholder(request):
    return HttpResponse("chat app — not built yet")
