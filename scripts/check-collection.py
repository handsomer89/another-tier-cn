#!/usr/bin/env python3
"""Exercise collection ordering/update safety, then check the current catalog."""

import copy
import json
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = runpy.run_path(str(ROOT / "scripts/generate-collection.py"))
build_catalog = COLLECTION["build_catalog"]
validate_catalog = COLLECTION["validate_catalog"]


def card(slug, can_sa=False):
    return {"slug": slug, "canSA": can_sa, "name": slug.title(), "style": "NS"}


class CollectionChecks(unittest.TestCase):
    def test_rank_merge_uses_tiers_before_source_and_source_before_position(self):
        snapshots = {"paid": [card("paid-a"), card("paid-s")],
                     "free": [card("free-a"), card("free-s")]}
        tiers = {"paid": [("A", ["paid-a"]), ("S", ["paid-s"])],
                 "free": [("S", ["free-s"]), ("A", ["free-a"])]}
        before = copy.deepcopy((snapshots, tiers))
        catalog, diagnostics = build_catalog(snapshots, tiers)
        self.assertEqual([c["slug"] for c in catalog["characters"]],
                         ["paid-s", "free-s", "paid-a", "free-a"])
        self.assertEqual([c["source"] for c in catalog["characters"]], ["paid", "free", "paid", "free"])
        self.assertFalse(diagnostics)
        self.assertEqual((snapshots, tiers), before, "Generating the collection must not mutate source data")

    def test_duplicate_slug_retains_best_unified_position(self):
        shared = card("shared")
        snapshots = {"paid": [shared, card("paid")], "free": [card("shared", True), card("free")]}
        tiers = {"paid": [("A", ["shared", "paid"]), ("S", ["paid"])],
                 "free": [("S", ["shared", "free"])]}
        catalog, diagnostics = build_catalog(snapshots, tiers)
        self.assertEqual([(c["slug"], c["source"]) for c in catalog["characters"]],
                         [("paid", "paid"), ("shared", "free"), ("free", "free")])
        self.assertTrue(catalog["characters"][1]["canSA"], "Duplicate fields must come from the retained occurrence")
        self.assertTrue(any("Duplicate" in item for item in diagnostics))

    def test_unknown_tier_and_unranked_character_follow_known_tiers(self):
        snapshots = {"paid": [card("unranked"), card("unknown"), card("known")], "free": [card("free")]}
        tiers = {"paid": [("Future", ["unknown"]), ("Slave", ["known"])], "free": [("F", ["free"])]}
        catalog, diagnostics = build_catalog(snapshots, tiers)
        self.assertEqual([c["slug"] for c in catalog["characters"]], ["free", "known", "unknown", "unranked"])
        self.assertTrue(any("Unknown" in item for item in diagnostics))
        self.assertTrue(any("Unranked" in item for item in diagnostics))

    def test_new_character_and_new_sa_change_version_without_losing_fields(self):
        snapshots = {"paid": [card("paid")], "free": [card("free")]}
        tiers = {"paid": [("S", ["paid"])], "free": [("A", ["free"])]}
        original, _ = build_catalog(snapshots, tiers)
        self.assertEqual(original, build_catalog(snapshots, tiers)[0], "Unchanged input must retain its version")
        snapshots["paid"].append(card("new-character", True))
        tiers["paid"][0][1].append("new-character")
        added, _ = build_catalog(snapshots, tiers)
        self.assertEqual({c["slug"] for c in added["characters"]}, {"paid", "free", "new-character"})
        self.assertNotEqual(original["catalogVersion"], added["catalogVersion"])
        snapshots["paid"][0]["canSA"] = True
        awakened, _ = build_catalog(snapshots, tiers)
        self.assertNotEqual(added["catalogVersion"], awakened["catalogVersion"])
        self.assertTrue(next(c for c in awakened["characters"] if c["slug"] == "paid")["canSA"])

    def test_invalid_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "absent"):
            build_catalog({"paid": [card("paid")], "free": [card("free")]},
                          {"paid": [("S", ["missing"])], "free": [("A", ["free"])]})
        invalid = {"slug": "invalid", "canSA": "true"}
        with self.assertRaisesRegex(ValueError, "canSA"):
            build_catalog({"paid": [invalid], "free": [card("free")]},
                          {"paid": [("S", ["invalid"])], "free": [("A", ["free"])]})

    def test_failed_validation_preserves_previous_catalog_and_cleans_temporary_file(self):
        expected, _ = build_catalog({"paid": [card("paid")], "free": [card("free")]},
                                    {"paid": [("S", ["paid"])], "free": [("A", ["free"])]})
        broken = copy.deepcopy(expected)
        broken["characters"][0]["order"] = 99
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "collection.json"
            destination.write_text("previous good catalog\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                COLLECTION["write_catalog"](broken, expected, destination)
            self.assertEqual(destination.read_text(encoding="utf-8"), "previous good catalog\n")
            self.assertEqual(list(Path(directory).iterdir()), [destination])
            COLLECTION["write_catalog"](expected, expected, destination)
            validate_catalog(json.loads(destination.read_text(encoding="utf-8")), expected)


def main():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CollectionChecks))
    if not result.wasSuccessful():
        return 1
    expected, diagnostics = build_catalog(*COLLECTION["load_inputs"]())
    validate_catalog(json.loads((ROOT / "data/collection.json").read_text(encoding="utf-8")), expected)
    image_count = COLLECTION["validate_images"](expected)
    for diagnostic in diagnostics:
        print("[WARN] " + diagnostic)
    print(f"[OK] Current catalog: {len(expected['characters'])} unique forms; {image_count} image backups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
