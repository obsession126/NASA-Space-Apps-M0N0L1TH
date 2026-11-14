import unittest
from unittest.mock import patch

import numpy as np

from analytics.trend_forecaster import (
    MIN_HISTORY_SAMPLES,
    MODEL_VERSION,
    _adaptive_scalar_kalman,
    _lagged_samples,
    forecast_feature,
)


class TrendForecasterTests(unittest.TestCase):
    def test_numeric_feature_reports_forecast_direction_and_holdout_error(self):
        values = [60.0 + index * 0.5 for index in range(MIN_HISTORY_SAMPLES + 12)]

        class FakeRegressor:
            def fit(self, features, targets):
                self.feature_count = len(features[0])
                return self

            def predict(self, features):
                return [0.0] * len(features)

        with patch(
            "analytics.trend_forecaster._regressor", side_effect=FakeRegressor
        ):
            result = forecast_feature(values, unit="bpm")

        self.assertEqual(result["model"], MODEL_VERSION)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["direction"], "rising")
        self.assertIsInstance(result["forecast_value"], float)
        self.assertIsInstance(result["holdout_median_absolute_error"], float)
        self.assertGreater(result["normalized_trend"], 0)

    def test_kalman_filter_reduces_noise_and_tracks_a_sustained_shift(self):
        noisy_values = [0.0, 1.0] * 8
        filtered = _adaptive_scalar_kalman(np.asarray(noisy_values, dtype=float))
        self.assertLess(float(filtered.var()), float(np.var(noisy_values)))

        shifted_values = [0.0] * 8 + [10.0] * 3
        shifted = _adaptive_scalar_kalman(np.asarray(shifted_values, dtype=float))
        self.assertGreater(float(shifted[-1]), 9.0)

    def test_filter_changes_input_history_without_changing_forecast_targets(self):
        values = np.asarray([0.0, 1.0] * 8, dtype=float)
        filtered = _adaptive_scalar_kalman(values)
        contexts = np.empty((len(values), 0), dtype=float)

        features, targets = _lagged_samples(
            values,
            contexts,
            history_values=filtered,
        )

        np.testing.assert_array_equal(targets, values[8:])
        self.assertFalse(np.array_equal(features[0][:8], values[:8]))

    def test_filter_noise_estimation_can_be_limited_to_training_history(self):
        training_history = np.asarray([0.0, 1.0] * 8, dtype=float)
        full_history = np.concatenate((training_history, [20.0, -20.0, 30.0]))

        training_filter = _adaptive_scalar_kalman(
            training_history,
            noise_reference=training_history,
        )
        full_filter = _adaptive_scalar_kalman(
            full_history,
            noise_reference=training_history,
        )

        np.testing.assert_array_equal(
            full_filter[:len(training_history)],
            training_filter,
        )

    def test_kalman_filter_is_reported_only_for_supported_sensor_features(self):
        values = [60.0 + index * 0.5 for index in range(MIN_HISTORY_SAMPLES + 12)]

        class FakeRegressor:
            def fit(self, features, targets):
                return self

            def predict(self, features):
                return [0.0] * len(features)

        with patch(
            "analytics.trend_forecaster._regressor", side_effect=FakeRegressor
        ):
            sensor_result = forecast_feature(
                values,
                unit="bpm",
                feature_name="hr_bpm",
            )
            category_result = forecast_feature(
                values,
                unit="score_1_5",
                feature_name="sleep_quality_1_5",
            )

        self.assertEqual(
            sensor_result["input_filter"]["method"],
            "adaptive_scalar_kalman",
        )
        self.assertTrue(sensor_result["input_filter"]["applied"])
        self.assertFalse(category_result["input_filter"]["applied"])

    def test_missing_and_non_finite_samples_are_excluded(self):
        values = [float(index) for index in range(MIN_HISTORY_SAMPLES + 8)]
        values[2] = None
        values[3] = float("nan")

        class FakeRegressor:
            def fit(self, features, targets):
                return self

            def predict(self, features):
                return [0.0] * len(features)

        with patch(
            "analytics.trend_forecaster._regressor", side_effect=FakeRegressor
        ):
            result = forecast_feature(values, unit="score")

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["history_samples"], len(values) - 2)

    def test_insufficient_history_does_not_make_a_forecast(self):
        result = forecast_feature([float(index) for index in range(12)], unit="bpm")

        self.assertEqual(result["status"], "building_history")
        self.assertIsNone(result["forecast_value"])

    def test_categorical_history_uses_classifier_for_multiple_classes(self):
        values = [float(index % 2) for index in range(MIN_HISTORY_SAMPLES + 12)]

        class FakeClassifier:
            def fit(self, features, targets):
                return self

            def predict(self, features):
                return [1]

        with patch(
            "analytics.trend_forecaster._classifier", return_value=FakeClassifier()
        ):
            result = forecast_feature(values, unit="category_code")

        self.assertEqual(result["status"], "ready")
        self.assertIn(result["forecast_value"], (0, 1))

    def test_single_class_categorical_series_does_not_make_fake_forecast(self):
        values = [0.0 for _ in range(MIN_HISTORY_SAMPLES + 12)]

        result = forecast_feature(values, unit="category_code")

        self.assertEqual(result["status"], "categorical_not_forecast")
        self.assertIsNone(result["forecast_value"])


if __name__ == "__main__":
    unittest.main()
