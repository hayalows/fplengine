import unittest

from fplengine.rules import next_free_transfers, selling_price_tenths, transfer_hit_cost


class RulesTests(unittest.TestCase):
    def test_selling_price_keeps_half_profit_rounded_down(self) -> None:
        self.assertEqual(selling_price_tenths(50, 54), 52)
        self.assertEqual(selling_price_tenths(50, 53), 51)
        self.assertEqual(selling_price_tenths(50, 51), 50)

    def test_selling_price_realizes_full_loss(self) -> None:
        self.assertEqual(selling_price_tenths(50, 47), 47)

    def test_transfer_hits_and_banking(self) -> None:
        self.assertEqual(transfer_hit_cost(1, 1), 0)
        self.assertEqual(transfer_hit_cost(3, 1), 8)
        self.assertEqual(next_free_transfers(1, 0), 2)
        self.assertEqual(next_free_transfers(5, 0), 5)
        self.assertEqual(next_free_transfers(3, 2), 2)
        self.assertEqual(next_free_transfers(2, 4), 1)


if __name__ == "__main__":
    unittest.main()
