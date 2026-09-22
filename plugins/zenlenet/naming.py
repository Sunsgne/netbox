"""Pure helpers shared by the NetBox loader."""

import hashlib
import ipaddress
import re

STATUS_TO_NETBOX = {
    'allocated': 'active',
    'free': 'available',
    'reserved': 'reserved',
    'testing': 'testing',
    'returning': 'returning',
    'internal': 'internal',
}


def prefix_of(version, address, prefixlen) -> str:
    if int(version) == 4 and int(prefixlen) == 32:
        raw = '.'.join(str(address).split('.')[:3]) + '.0/24'
    else:
        raw = f'{address}/{prefixlen}'
    return str(ipaddress.ip_network(raw, strict=False))


def slugify_name(name: str) -> str:
    ascii_name = re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')
    if ascii_name:
        return ascii_name[:80]
    digest = hashlib.sha1((name or '').encode()).hexdigest()[:12]
    return f'zl-{digest}'


def unique_slug(name: str, used: set[str]) -> str:
    base = slugify_name(name)[:90] or 'item'
    slug = base
    number = 2
    while slug in used:
        suffix = f'-{number}'
        slug = f'{base[:100 - len(suffix)]}{suffix}'
        number += 1
    used.add(slug)
    return slug
