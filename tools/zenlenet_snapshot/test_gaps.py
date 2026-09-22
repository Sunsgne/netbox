import unittest

from zenlenet_snapshot.parsing import ai_note_from_row, ai_status


class GapParsingTests(unittest.TestCase):
    def test_ai_note_drops_the_secret_column(self):
        row = ["客户甲", "平台A", "供应商", "Key", "密码：s3cret-value", "5000", "", "", "", "商务"]
        note = ai_note_from_row(row)
        self.assertNotIn("s3cret", note)
        self.assertNotIn("密码", note)
        self.assertIn("平台A", note)
        self.assertIn("5000", note)

    def test_ai_status(self):
        self.assertEqual(ai_status("已回收", "商务"), "terminated")
        self.assertEqual(ai_status("", "测试"), "testing")
        self.assertEqual(ai_status("", "商务"), "active")


if __name__ == "__main__":
    unittest.main()
