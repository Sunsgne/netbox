from netbox.plugins import PluginConfig


class ZenlenetConfig(PluginConfig):
    name = 'zenlenet'
    verbose_name = 'ZENLENET'
    description = 'Hide unused NetBox menus and link customers to Odoo.'
    version = '1.0.0'
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

        hidden = [
            menu
            for menu in (
                getattr(menu_mod, 'RACKS_MENU', None),
                getattr(menu_mod, 'DEVICES_MENU', None),
                getattr(menu_mod, 'CONNECTIONS_MENU', None),
                getattr(menu_mod, 'WIRELESS_MENU', None),
                getattr(menu_mod, 'VPN_MENU', None),
                getattr(menu_mod, 'VIRTUALIZATION_MENU', None),
                getattr(menu_mod, 'POWER_MENU', None),
                getattr(menu_mod, 'COOLING_MENU', None),
                getattr(menu_mod, 'PROVISIONING_MENU', None),
                getattr(menu_mod, 'CUSTOMIZATION_MENU', None),
            )
            if menu is not None
        ]
        original = menu_mod.get_menus.__wrapped__

        def trimmed():
            return [item for item in original() if all(item is not menu for menu in hidden)]

        if hasattr(menu_mod.get_menus, 'cache_clear'):
            menu_mod.get_menus.cache_clear()
        nav_tags.get_menus = trimmed


config = ZenlenetConfig
