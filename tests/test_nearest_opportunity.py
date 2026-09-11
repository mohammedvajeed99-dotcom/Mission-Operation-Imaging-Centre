"""Unit tests for core.nearest_opportunity and the haversine distance
function it's built on. Run with:

    python -m unittest tests.test_nearest_opportunity -v

Uses real-world coordinates (Vijayawada, Hyderabad, Visakhapatnam, Chennai)
so distances are independently checkable against known real-world figures,
not just internally self-consistent.
"""

import math
import unittest

import pandas as pd

from core.location_dataset import haversine_km
from core.nearest_opportunity import find_nearest_opportunity

# Real coordinates, not invented, used as fixed points throughout.
VIJAYAWADA = (16.52, 80.63)
HYDERABAD = (17.39, 78.49)
VISAKHAPATNAM = (17.69, 83.22)
CHENNAI = (13.08, 80.27)


def _row(image_id, satellite, lat, lon, state, status="Not Generated", cloud=5.0, quality=80.0):
    return {
        "imageId": image_id, "satellite": satellite,
        "latitude": lat, "longitude": lon,
        "australianState": state, "generationStatus": status,
        "cloudCoverPercent": cloud, "imageQualityScore": quality,
    }


class HaversineTests(unittest.TestCase):
    def test_zero_distance_for_identical_points(self):
        self.assertAlmostEqual(haversine_km(*VIJAYAWADA, *VIJAYAWADA), 0.0, places=6)

    def test_known_real_world_distance(self):
        # Vijayawada -> Hyderabad is a well-known real road/air distance,
        # roughly 275 km great-circle. Sanity range, not an exact literal,
        # since "well-known" figures are road distance, not geodesic.
        d = haversine_km(*VIJAYAWADA, *HYDERABAD)
        self.assertTrue(240 <= d <= 300, f"unexpected distance {d} km")

    def test_symmetric(self):
        d1 = haversine_km(*VIJAYAWADA, *CHENNAI)
        d2 = haversine_km(*CHENNAI, *VIJAYAWADA)
        self.assertAlmostEqual(d1, d2, places=9)

    def test_triangle_consistency(self):
        # Visakhapatnam is further from Chennai than Vijayawada is --
        # a real, checkable geographic fact, used here to confirm the
        # formula orders real distances correctly, not just computes *a*
        # number.
        d_vja_chn = haversine_km(*VIJAYAWADA, *CHENNAI)
        d_vsk_chn = haversine_km(*VISAKHAPATNAM, *CHENNAI)
        self.assertLess(d_vja_chn, d_vsk_chn)


class FindNearestOpportunityTests(unittest.TestCase):
    def test_picks_the_geographically_nearest_not_first_or_alphabetical(self):
        # Deliberately ordered so the FIRST row and the ALPHABETICALLY
        # FIRST satellite are both far away -- only genuine distance
        # should win.
        df = pd.DataFrame([
            _row("ASC-999-FAR", "ASC_074_01", *CHENNAI, "Tamil Nadu"),
            _row("ASC-001-NEAR", "ASC_074_99", 16.60, 80.70, "Andhra Pradesh"),  # ~13 km from Vijayawada
            _row("ASC-500-MID", "ASC_074_50", *HYDERABAD, "Telangana"),
        ])
        row, dist_km, within_state = find_nearest_opportunity(df, *VIJAYAWADA)
        self.assertEqual(row["imageId"], "ASC-001-NEAR")
        self.assertLess(dist_km, 20)

    def test_prefers_within_state_over_a_closer_out_of_state_candidate(self):
        # The Telangana row is geographically CLOSER to Vijayawada than the
        # Andhra Pradesh row is, but Level 2 must still prefer the
        # same-state match when one exists.
        df = pd.DataFrame([
            _row("OUT-OF-STATE-CLOSER", "ASC_074_01", 16.9, 79.9, "Telangana"),
            _row("IN-STATE-FARTHER", "ASC_074_02", 17.2, 82.0, "Andhra Pradesh"),
        ])
        closer_dist = haversine_km(*VIJAYAWADA, 16.9, 79.9)
        farther_dist = haversine_km(*VIJAYAWADA, 17.2, 82.0)
        self.assertLess(closer_dist, farther_dist)  # sanity: confirms the test's own premise

        row, dist_km, within_state = find_nearest_opportunity(
            df, *VIJAYAWADA, preferred_state="Andhra Pradesh"
        )
        self.assertEqual(row["imageId"], "IN-STATE-FARTHER")
        self.assertTrue(within_state)

    def test_widens_to_other_states_when_none_match_preferred_state(self):
        df = pd.DataFrame([
            _row("ONLY-OPTION", "ASC_074_01", *HYDERABAD, "Telangana"),
        ])
        row, dist_km, within_state = find_nearest_opportunity(
            df, *VIJAYAWADA, preferred_state="Andhra Pradesh"
        )
        self.assertEqual(row["imageId"], "ONLY-OPTION")
        self.assertFalse(within_state)

    def test_excludes_rows_with_missing_coordinates(self):
        df = pd.DataFrame([
            _row("NO-COORDS", "ASC_074_01", None, None, "Andhra Pradesh"),
            _row("HAS-COORDS", "ASC_074_02", 16.9, 80.9, "Andhra Pradesh"),
        ])
        row, dist_km, within_state = find_nearest_opportunity(df, *VIJAYAWADA)
        self.assertEqual(row["imageId"], "HAS-COORDS")

    def test_empty_dataframe_returns_none_not_a_fabricated_result(self):
        df = pd.DataFrame(columns=["imageId", "latitude", "longitude", "australianState"])
        row, dist_km, within_state = find_nearest_opportunity(df, *VIJAYAWADA)
        self.assertIsNone(row)
        self.assertIsNone(dist_km)
        self.assertFalse(within_state)

    def test_none_dataframe_returns_none(self):
        row, dist_km, within_state = find_nearest_opportunity(None, *VIJAYAWADA)
        self.assertIsNone(row)

    def test_all_missing_coordinates_returns_none(self):
        df = pd.DataFrame([_row("NO-COORDS", "ASC_074_01", None, None, "Andhra Pradesh")])
        row, dist_km, within_state = find_nearest_opportunity(df, *VIJAYAWADA)
        self.assertIsNone(row)

    def test_distance_is_computed_not_guessed(self):
        # The returned distance must equal the actual haversine value for
        # the chosen row, not an approximation or a rounded-differently one.
        lat, lon = 16.9, 80.9
        df = pd.DataFrame([_row("X", "ASC_074_01", lat, lon, "Andhra Pradesh")])
        row, dist_km, _ = find_nearest_opportunity(df, *VIJAYAWADA)
        expected = round(haversine_km(*VIJAYAWADA, lat, lon), 1)
        self.assertEqual(dist_km, expected)


if __name__ == "__main__":
    unittest.main()
