"""Load a ZENLENET SQLite snapshot into NetBox IPAM and circuits."""

import sqlite3

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from circuits.models import Circuit, CircuitType, Provider
from dcim.models import Site
from extras.choices import CustomFieldTypeChoices
from extras.models import CustomField, CustomFieldChoiceSet
from ipam.models import IPAddress, Prefix
from tenancy.models import Tenant, TenantGroup

from zenlenet.naming import STATUS_TO_NETBOX, prefix_of, slugify_name

MARKER = 'zenlenet:'
BATCH = 1000


class Command(BaseCommand):
    help = 'Import customers, prefixes, addresses, and circuits from a snapshot database.'

    def add_arguments(self, parser):
        parser.add_argument('--sqlite', required=True)
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        try:
            connection = sqlite3.connect(options['sqlite'])
            connection.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise CommandError(str(exc)) from exc
        customers = list(connection.execute('select * from customers'))
        addresses = list(connection.execute('select * from ip_records'))
        circuits = list(connection.execute('select * from circuits'))
        links = list(connection.execute('select * from vxlan_links'))
        if not addresses:
            raise CommandError('snapshot has no addresses')
        existing = IPAddress.objects.filter(comments__startswith=MARKER).count()
        if existing and not options['force']:
            raise CommandError(f'{existing} imported addresses already exist; pass --force to replace them')
        with transaction.atomic():
            if options['force']:
                self._clear()
            self._fields()
            tenant_group, _ = TenantGroup.objects.get_or_create(name='客户', defaults={'slug': 'customers'})
            tenants = self._tenants(customers, tenant_group)
            sites = self._sites(addresses)
            self._prefixes(addresses, sites, tenants)
            count = self._addresses(addresses, tenants)
            circuit_count = self._circuits(circuits, links)
        self.stdout.write(f'tenants={len(tenants)} addresses={count} circuits={circuit_count}')

    def _clear(self):
        IPAddress.objects.filter(comments__startswith=MARKER).delete()
        Prefix.objects.filter(comments__startswith=MARKER).delete()
        Circuit.objects.filter(comments__startswith=MARKER).delete()
        Tenant.objects.filter(comments__startswith=MARKER).delete()
        Site.objects.filter(comments__startswith=MARKER).delete()
        Provider.objects.filter(comments__startswith=MARKER).delete()

    def _fields(self):
        ip_type = ContentType.objects.get_for_model(IPAddress)
        self._select_field('dc_type', '数据中心类型', ip_type, (
            ('主营机房', '主营机房'),
            ('第三方', '第三方'),
            ('POP点', 'POP点'),
            ('公有云', '公有云'),
        ))
        self._select_field('net_attr', '网络属性', ip_type, (
            ('公网', '公网'),
            ('内网', '内网'),
        ))
        self._select_field('resource_role', '资源属性', ip_type, (
            ('idc', 'IDC'),
            ('local', '本地'),
            ('native', '原生'),
            ('home', '家庭'),
            ('bgp', 'BGP'),
            ('other', '其他'),
        ))
        for name, label, kind in (
            ('usage', '用途', CustomFieldTypeChoices.TYPE_TEXT),
            ('expires_on', '到期日', CustomFieldTypeChoices.TYPE_DATE),
        ):
            field, _ = CustomField.objects.get_or_create(
                name=name,
                defaults={'label': label, 'type': kind, 'group_name': 'ZENLENET'},
            )
            field.object_types.add(ip_type)

    def _select_field(self, name, label, content_type, choices):
        choice_set, _ = CustomFieldChoiceSet.objects.get_or_create(
            name=f'ZENLENET {label}',
            defaults={'extra_choices': choices},
        )
        field, _ = CustomField.objects.get_or_create(
            name=name,
            defaults={
                'label': label,
                'type': CustomFieldTypeChoices.TYPE_SELECT,
                'choice_set': choice_set,
                'group_name': 'ZENLENET',
            },
        )
        if field.choice_set_id != choice_set.id:
            field.choice_set = choice_set
            field.save()
        field.object_types.add(content_type)

    def _tenants(self, customers, group):
        found = {}
        for row in customers:
            name = (row['name'] or '')[:100]
            if not name:
                continue
            tenant, _ = Tenant.objects.get_or_create(
                name=name,
                group=group,
                defaults={
                    'slug': slugify_name(name),
                    'description': (row['status'] or '')[:200],
                    'comments': f'{MARKER}customer',
                },
            )
            found[row['id']] = tenant
        return found

    def _sites(self, addresses):
        found = {}
        for row in addresses:
            pop = (row['pop'] or '未标注')[:100]
            if pop in found:
                continue
            site, _ = Site.objects.get_or_create(
                name=pop,
                defaults={
                    'slug': slugify_name(pop),
                    'status': 'active',
                    'comments': f'{MARKER}pop',
                },
            )
            found[pop] = site
        return found

    def _prefixes(self, addresses, sites, tenants):
        buckets = {}
        for row in addresses:
            prefix = prefix_of(row['version'], row['address'], row['prefixlen'])
            pop = row['pop'] or '未标注'
            buckets.setdefault(prefix, {
                'pop': pop,
                'tenant_id': row['customer_id'],
                'supplier': row['supplier'] or '',
            })
        for cidr, meta in buckets.items():
            if Prefix.objects.filter(prefix=cidr, vrf=None).exists():
                continue
            prefix = Prefix(
                prefix=cidr,
                status='active',
                description=(meta['supplier'] or '')[:200],
                comments=f'{MARKER}prefix',
                tenant=tenants.get(meta['tenant_id']),
            )
            prefix.scope = sites.get(meta['pop'])
            prefix.save()

    def _addresses(self, addresses, tenants):
        now = timezone.now()
        batch = []
        stored = 0
        seen = set()
        for row in addresses:
            address = f"{row['address']}/{row['prefixlen']}"
            if address in seen:
                continue
            seen.add(address)
            data = {}
            if row['dc_type']:
                data['dc_type'] = row['dc_type']
            if row['net_attr']:
                data['net_attr'] = row['net_attr']
            if row['role']:
                data['resource_role'] = row['role']
            if row['usage']:
                data['usage'] = row['usage'][:200]
            if row['expires_on']:
                data['expires_on'] = str(row['expires_on'])[:10]
            batch.append(IPAddress(
                address=address,
                status=STATUS_TO_NETBOX.get(row['status'], 'active'),
                tenant=tenants.get(row['customer_id']),
                description=(row['remark'] or '')[:200],
                comments=f"{MARKER}{row['source'] or 'import'}",
                custom_field_data=data,
                created=now,
                last_updated=now,
            ))
            if len(batch) >= BATCH:
                IPAddress.objects.bulk_create(batch, batch_size=BATCH)
                stored += len(batch)
                batch = []
        if batch:
            IPAddress.objects.bulk_create(batch, batch_size=BATCH)
            stored += len(batch)
        return stored

    def _circuits(self, circuits, links):
        provider, _ = Provider.objects.get_or_create(
            name='专线',
            defaults={'slug': 'circuits', 'comments': f'{MARKER}provider'},
        )
        private, _ = CircuitType.objects.get_or_create(name='专线', defaults={'slug': 'private-line'})
        vxlan, _ = CircuitType.objects.get_or_create(name='VXLAN', defaults={'slug': 'vxlan'})
        used = set(Circuit.objects.values_list('cid', flat=True))
        created = 0
        for row in circuits:
            cid = _unique_cid(row['circuit_no'] or f"{row['a_city']}-{row['z_city']}", used)
            rate = int(row['bandwidth_mbps'] or 0) * 1000
            Circuit.objects.create(
                cid=cid,
                provider=provider,
                type=private,
                status='active',
                commit_rate=rate or None,
                description=f"{row['a_city']} → {row['z_city']}"[:200],
                comments=f"{MARKER}vlan {row['a_vlan'] or ''}/{row['z_vlan'] or ''}",
            )
            created += 1
        for index, row in enumerate(links, start=1):
            cid = _unique_cid(f"VNI-{row['vni'] or index}", used)
            Circuit.objects.create(
                cid=cid,
                provider=provider,
                type=vxlan,
                status='active' if not row['stopped'] else 'decommissioned',
                description=f"{row['a_end']} → {row['z_end']}"[:200],
                comments=f"{MARKER}{row['customer_name'] or ''} {row['purpose'] or ''}"[:500],
            )
            created += 1
        return created


def _unique_cid(raw, used):
    base = (raw or 'circuit').strip()[:80] or 'circuit'
    cid = base
    number = 2
    while cid in used:
        cid = f'{base}-{number}'[:100]
        number += 1
    used.add(cid)
    return cid
