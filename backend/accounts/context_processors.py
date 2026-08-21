# accounts/context_processors.py
"""
A dedicated view (profile_setup_view specifically) can't be trusted to
always be the first page rendered after sign-in — a returning user who
already completed profile setup skips straight to social:home instead.
A context processor runs on every render(request, ...) call across the
whole project, so the flag gets shown exactly once no matter which page
happens to load first, without accounts needing to know anything about
the social app's views.

Register in settings.py under TEMPLATES -> OPTIONS -> 'context_processors':
    'accounts.context_processors.verified_notice',
"""
from .verification import pop_verified_notice_flag


def verified_notice(request):
    # Cheap early exit for the overwhelming majority of requests where
    # the flag was never set, so pop_verified_notice_flag's session
    # write only happens on the one request that actually needs it.
    if not request.session.get('show_verified_notice'):
        return {}
    return {'show_verified_notice': pop_verified_notice_flag(request)}
