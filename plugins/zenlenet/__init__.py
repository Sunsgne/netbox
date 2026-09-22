from netbox.plugins import PluginConfig


class ZenlenetConfig(PluginConfig):
    name = 'zenlenet'
    verbose_name = 'ZENLENET'
    description = 'Keep NetBox behind the ZENLENET operations console.'
    version = '1.1.0'
    middleware = ['zenlenet.middleware.FrontDoorMiddleware']
    author = 'ZENLENET PTE. LTD.'
    base_url = 'zenlenet'
    min_version = '4.7.0'
    default_settings = {
        'odoo_path': '/odoo',
    }

    def ready(self):
        super().ready()
        from netbox.navigation import menu as menu_mod
        from utilities.templatetags import navigation as nav_tags

        from netbox.navigation import MenuGroup, get_model_item

        ipam = menu_mod.IPAM_MENU
        circuits = menu_mod.CIRCUITS_MENU
        ipam.label = 'IP资源'
        ipam.groups = (
            MenuGroup(label='地址', items=(get_model_item('ipam', 'ipaddress', '地址'),)),
            MenuGroup(label='网段', items=(get_model_item('ipam', 'prefix', '网段'),)),
        )
        circuits.label = '线路'
        circuits.groups = (
            MenuGroup(label='线路', items=(get_model_item('circuits', 'circuit', '线路'),)),
        )
        original = menu_mod.get_menus.__wrapped__

        def trimmed():
            found = []
            for item in original():
                if item is ipam or item is circuits:
                    found.append(item)
            return found

        if hasattr(menu_mod.get_menus, 'cache_clear'):
            menu_mod.get_menus.cache_clear()
        nav_tags.get_menus = trimmed
        from django.conf import settings
        settings.BANNER_TOP = '<a href="/odoo">返回尊领</a>'


config = ZenlenetConfig
