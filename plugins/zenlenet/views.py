from django.shortcuts import redirect

from netbox.plugins.utils import get_plugin_config


def odoo_home(request):
    return redirect(get_plugin_config('zenlenet', 'odoo_path'))
