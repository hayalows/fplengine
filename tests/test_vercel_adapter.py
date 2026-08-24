from __future__ import annotations

import unittest

from api.index import _requested_tab


class VercelAdapterTests(unittest.TestCase):
    def test_query_tab_is_resolved(self) -> None:
        self.assertEqual(_requested_tab('/api/index?tab=transfers'), 'transfers')

    def test_site_path_is_resolved(self) -> None:
        self.assertEqual(_requested_tab('/site/captain'), 'captain')

    def test_unknown_tab_falls_back_to_home(self) -> None:
        self.assertEqual(_requested_tab('/site/not-a-tab'), 'home')


if __name__ == '__main__':
    unittest.main()
