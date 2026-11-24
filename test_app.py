import csv
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from app import (
    BearRiverApp,
    USGS_API,
    create_work_file,
    summarize_daily_series,
    validate_work_file,
    write_daily_csv,
    write_daily_excel,
)


class PaginationTests(unittest.TestCase):
    def test_request_all_features_accepts_api_url_and_rejects_other_origins(self):
        class RequestHarness:
            def request_json(self, url, label):
                return {"features": [{"id": "site-1"}]}

        app = RequestHarness()
        features = BearRiverApp.request_all_features(
            app, USGS_API + "/collections/monitoring-locations/items", "test"
        )

        self.assertEqual(features, [{"id": "site-1"}])
        with self.assertRaisesRegex(RuntimeError, "unexpected pagination link"):
            BearRiverApp.request_all_features(
                app, "https://example.com/collections/test/items", "test"
            )


class WorkFileTests(unittest.TestCase):
    def test_work_file_round_trip(self):
        state = create_work_file("10000000", "bear river", True)
        self.assertEqual(validate_work_file(state), state)

    def test_work_file_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            validate_work_file({
                "version": 1,
                "selected_site_number": 123,
                "search_text": "",
                "show_historical": False,
            })
        with self.assertRaises(ValueError):
            validate_work_file({
                "version": True,
                "selected_site_number": None,
                "search_text": "",
                "show_historical": False,
            })


class DailyExportTests(unittest.TestCase):
    daily_series = [
        {"date": "2026-01-01", "value": 12.0},
        {"date": "2026-01-02", "value": None},
        {"date": "2026-01-03", "value": 18.5},
    ]

    def test_csv_keeps_missing_day_blank_and_includes_site_and_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flow.csv"
            write_daily_csv(path, "10000000", self.daily_series)
            with path.open(newline="", encoding="utf-8") as source:
                rows = list(csv.reader(source))

        self.assertEqual(
            rows[0], ["date", "site_number", "daily_mean_cfs", "unit"])
        self.assertEqual(rows[1], ["2026-01-01", "10000000", "12", "cfs"])
        self.assertEqual(rows[2], ["2026-01-02", "10000000", "", "cfs"])

    def test_excel_keeps_missing_day_empty_and_flow_numeric(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flow.xlsx"
            write_daily_excel(path, "10000000", self.daily_series)
            workbook = load_workbook(path, data_only=True)
            sheet = workbook["Daily Mean Flow"]

        self.assertEqual(sheet["C2"].value, 12.0)
        self.assertIsNone(sheet["C3"].value)
        self.assertEqual(sheet["B3"].value, "10000000")
        self.assertEqual(sheet["D3"].value, "cfs")


class DailyMeanValidationTests(unittest.TestCase):
    def test_handwritten_mean_excludes_missing_day(self):
        series = [
            {"date": "2026-01-01", "value": 12.0},
            {"date": "2026-01-02", "value": None},
            {"date": "2026-01-03", "value": 18.0},
            {"date": "2026-01-04", "value": 30.0},
        ]
        result = summarize_daily_series(series)

        self.assertEqual(result["mean"], 20.0)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["missing"], 1)


if __name__ == "__main__":
    unittest.main()
