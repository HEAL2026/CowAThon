import unittest

import pandas as pd

from cleaning.optional_milk import (
    MENDELEY_DOI,
    load_optional_milk,
    normalize_optional_milk,
    optional_milk_metadata,
)


class TestOptionalMilk(unittest.TestCase):
    def test_normalizes_optional_source_without_fabricating_ids(self):
        raw = pd.DataFrame(
            {
                "Cow Number": ["B01", "B01"],
                "Sampling Date": ["2024-01-03", "2024-01-04"],
                "Milk Yield": ["18.2", "17.9"],
                "Milk Fat (%)": [3.4, 3.2],
                "THI Group": ["<=75", "75-80"],
                "Rectal Temperature": [38.5, 38.7],
                "DMI": [17.0, 16.8],
            }
        )
        out = normalize_optional_milk(raw)
        self.assertEqual(out["cow_id"].tolist(), ["B01", "B01"])
        self.assertEqual(out["milk_yield_kg"].tolist(), [18.2, 17.9])
        self.assertEqual(out["source_dataset"].unique().tolist(), [MENDELEY_DOI])
        self.assertEqual(out["rectal_temp_c"].tolist(), [38.5, 38.7])
        self.assertEqual(out["dmi_kg"].tolist(), [17.0, 16.8])
        self.assertFalse(out["is_synthetic"].any())

    def test_missing_keys_are_explicit(self):
        with self.assertRaisesRegex(ValueError, "cow_id"):
            normalize_optional_milk(pd.DataFrame({"date": ["2024-01-01"]}))

    def test_loader_and_metadata(self, tmp_path=None):
        # Metadata is available without a network download; loader behavior is
        # exercised through the pure normalizer above.
        metadata = optional_milk_metadata()
        self.assertEqual(metadata["doi"], MENDELEY_DOI)
        self.assertEqual(metadata["license"], "CC BY 4.0")
        self.assertIn("explicit", metadata["join_policy"])

    def test_missing_file_is_explicit(self):
        with self.assertRaises(FileNotFoundError):
            load_optional_milk("/tmp/does-not-exist-optional-milk.csv")


if __name__ == "__main__":
    unittest.main()
