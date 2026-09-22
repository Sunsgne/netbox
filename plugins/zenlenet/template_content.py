from urllib.parse import quote

from netbox.plugins import PluginTemplateExtension


class TenantOdooLink(PluginTemplateExtension):
    models = ['tenancy.tenant']

    def right_page(self):
        tenant = self.context['object']
        name = quote(tenant.name)
        return (
            '<div class="card">'
            '<div class="card-header">Odoo</div>'
            '<div class="card-body">'
            f'<a class="btn btn-primary" href="/zenlenet/partner?name={name}">打开这个客户</a>'
            '<p class="text-secondary mt-2 mb-0">订单、账单和割接通知在 Odoo。</p>'
            '</div></div>'
        )


template_extensions = [TenantOdooLink]
