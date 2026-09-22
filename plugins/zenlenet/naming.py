"""Pure helpers shared by the NetBox loader."""

import hashlib
import re

STATUS_TO_NETBOX = {
    'allocated': 'active',
    'free': 'available',
    'reserved': 'reserved',
    'testing': 'testing',
    'returning': 'returning',
    'internal': 'internal',
}


def slugify_name(name: str) -> str:
    ascii_name = re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')
    if ascii_name:
        return ascii_name[:80]
    digest = hashlib.sha1((name or '').encode()).hexdigest()[:12]
    return f'zl-{digest}'
