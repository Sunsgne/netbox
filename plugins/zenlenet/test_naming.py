import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location('zenlenet_naming', Path(__file__).resolve().parent / 'naming.py')
_naming = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_naming)
STATUS_TO_NETBOX = _naming.STATUS_TO_NETBOX
slugify_name = _naming.slugify_name


class NamingTests(unittest.TestCase):
    def test_ascii_slug(self):
        self.assertEqual(slugify_name('LightWAN'), 'lightwan')

    def test_cjk_slug_is_stable(self):
        self.assertEqual(slugify_name('云森处'), slugify_name('云森处'))
        self.assertTrue(slugify_name('云森处').startswith('zl-'))

    def test_status_map(self):
        self.assertEqual(STATUS_TO_NETBOX['allocated'], 'active')
        self.assertEqual(STATUS_TO_NETBOX['free'], 'available')


if __name__ == '__main__':
    unittest.main()
