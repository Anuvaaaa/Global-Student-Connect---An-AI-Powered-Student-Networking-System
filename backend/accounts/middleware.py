class NoCacheForAuthenticatedUsersMiddleware:
    """
    Prevents the browser back button from showing a stale, cached copy
    of a page after logout (Chrome's bfcache can restore a frozen
    snapshot without hitting the server at all). Doesn't affect actual
    security — @login_required already blocks real access on any real
    request — this only stops a misleading stale visual.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return response
