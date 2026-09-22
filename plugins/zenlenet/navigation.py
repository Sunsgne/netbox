from netbox.plugins import PluginMenu, PluginMenuItem

menu = PluginMenu(
    label='业务',
    icon_class='mdi mdi-briefcase-outline',
    groups=(
        ('Odoo', (
            PluginMenuItem(
                link='plugins:zenlenet:odoo',
                link_text='客户 / 订单 / 出账',
            ),
        )),
    ),
)
