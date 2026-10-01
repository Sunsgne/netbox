from django.shortcuts import redirect

from netbox.plugins.utils import get_plugin_config


def obss_home(request):
    return redirect(get_plugin_config('zenlenet', 'obss_path'))
