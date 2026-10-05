import unittest

from measurement_plan import create_measurement_plan, first_measurable_index


def translation_config_with_obstacle_at_start() -> dict:
    return {
        "line": {
            "method": "translation",
            "parameters": {
                "line_length": 400.0,
                "increment": 100.0,
                "direction_start_end": [1.0, 0.0, 0.0],
            },
        },
        "obstacle": {
            "start": 0.0,
            "end": 150.0,
        },
    }


class MeasurementPlanIndexTests(unittest.TestCase):
    def test_first_measurable_index_uses_actual_plan_index(self):
        config = translation_config_with_obstacle_at_start()

        self.assertEqual(first_measurable_index(config), 3)

    def test_plan_keeps_original_indexes_for_skipped_start_points(self):
        plan = create_measurement_plan(translation_config_with_obstacle_at_start())

        self.assertEqual(
            [
                (point["measurement_index"], point["measured"])
                for point in plan["points"][:3]
            ],
            [(1, False), (2, False), (3, True)],
        )


if __name__ == "__main__":
    unittest.main()
