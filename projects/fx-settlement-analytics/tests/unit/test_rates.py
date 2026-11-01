import hashlib
import io
import unittest
import zipfile
from datetime import date
from decimal import Decimal

from pipeline.prepare_rates import prepare


def archive(rows, header="Date,USD,GBP"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        target.writestr("eurofxref-hist.csv", header + "\n" + rows)
    return output.getvalue()


class RateTests(unittest.TestCase):
    def prepare(self, data):
        return prepare(data, date(2025, 1, 1), date(2025, 1, 31))

    def test_cross_direction_and_lineage(self):
        data = archive("2025-01-02,1.25,0.80\n")
        cross = next(r for r in self.prepare(data) if r["pair"] == "GBP/USD")
        self.assertEqual(Decimal(cross["rate"]), Decimal("1.5625"))
        self.assertEqual(cross["source_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(cross["source_row"], 2)
        self.assertEqual(cross["input_currencies"], "USD+GBP")

    def test_missing_inputs_never_cross_dates(self):
        rows = self.prepare(archive("2025-01-02,1.25,N/A\n2025-01-03,N/A,0.80\n"))
        self.assertEqual([r["pair"] for r in rows], ["EUR/USD", "EUR/GBP"])

    def test_invalid_rates_fail_batch(self):
        for value in ["0", "-1", "NaN", "Infinity", "oops"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.prepare(archive(f"2025-01-02,{value},0.80\n"))

    def test_duplicates_fail(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.prepare(archive("2025-01-02,1.25,0.80\n2025-01-02,1.26,0.81\n"))

    def test_schema_drift_fails(self):
        with self.assertRaisesRegex(ValueError, "requires"):
            self.prepare(archive("2025-01-02,1.25\n", "Date,USD"))

    def test_bounds_and_no_forward_fill(self):
        rows = self.prepare(archive("2024-12-31,1.25,0.80\n2025-01-03,1.25,0.80\n"))
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["rate_date"] for r in rows}, {"2025-01-03"})

    def test_empty_window_fails(self):
        with self.assertRaisesRegex(ValueError, "No usable"):
            self.prepare(archive("2024-12-31,1.25,0.80\n"))
