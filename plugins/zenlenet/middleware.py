from django.http import HttpResponseRedirect


class FrontDoorMiddleware:
    """Send the public homepage to the single operations console."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        accept = request.META.get('HTTP_ACCEPT', '')
        if request.method == 'GET' and request.path == '/' and 'text/html' in accept:
            return HttpResponseRedirect('/odoo')
        return self.get_response(request)
