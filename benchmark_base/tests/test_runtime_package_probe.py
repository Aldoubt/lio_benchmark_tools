from __future__ import annotations

import unittest

from benchmark_base.lib.runtime_package_probe import resolve_runtime_package_prefixes


class RuntimePackageProbeTest(unittest.TestCase):
    @staticmethod
    def _manifest() -> dict:
        return {
            "algorithms": {
                "fast_livo2": {
                    "execution_implementation": {"package": "fast_livo"},
                },
                "fast_lio2": {
                    "execution_implementation": {"package": "fast_lio"},
                },
                "kiss_icp": {
                    "execution_implementation": {"package": "kiss_icp"},
                },
            },
            "execution_overrides": {
                "fast_lio2": {"executable": "/standalone/fastlio_mapping"},
            },
        }

    def test_only_registry_default_packages_are_probed(self) -> None:
        calls: list[str] = []

        def probe(package: str) -> str | None:
            calls.append(package)
            return {
                "fast_livo": "/ws/install/fast_livo",
                "kiss_icp": None,
            }[package]

        result = resolve_runtime_package_prefixes(
            self._manifest(),
            ["fast_livo2", "fast_lio2", "kiss_icp"],
            probe=probe,
        )

        self.assertEqual(["fast_livo", "kiss_icp"], calls)
        self.assertEqual(
            {
                "fast_livo": "/ws/install/fast_livo",
                "kiss_icp": None,
            },
            result,
        )

    def test_duplicate_runtime_package_is_probed_once(self) -> None:
        manifest = self._manifest()
        manifest["algorithms"]["second_livo"] = {
            "execution_implementation": {"package": "fast_livo"},
        }
        calls: list[str] = []

        def probe(package: str) -> str | None:
            calls.append(package)
            return "/ws/install/fast_livo"

        result = resolve_runtime_package_prefixes(
            manifest,
            ["fast_livo2", "second_livo"],
            probe=probe,
        )

        self.assertEqual(["fast_livo"], calls)
        self.assertEqual({"fast_livo": "/ws/install/fast_livo"}, result)


if __name__ == "__main__":
    unittest.main()
