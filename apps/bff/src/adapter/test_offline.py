"""Offline adapter contract tests.

Run from the repository root with::

    PYTHONPATH=apps/bff/src python -m unittest adapter.test_offline
"""

from __future__ import annotations

import unittest
from collections.abc import Callable
from copy import deepcopy
from unittest.mock import patch

from . import offline as offline_module
from .offline import (
    FixtureContractError,
    OfflineFixtureAdapter,
    _load_json_fixture,
)


class OfflineFixtureAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.adapter = OfflineFixtureAdapter()

    def test_representative_ow_and_bff_cases_are_available(self) -> None:
        ow_response = self.adapter.get_ow_response("activity_summary")
        bff_response = self.adapter.get_bff_response("overview_mixed")

        self.assertEqual(ow_response["data"][0]["distance_meters"], 5300)
        self.assertEqual(
            bff_response["data"]["summary"]["activeCaloriesKcal"]["state"], "zero"
        )
        self.assertEqual(
            bff_response["data"]["summary"]["recoveryScore"]["value"], None
        )

    def test_supported_cases_cover_required_negative_and_error_states(self) -> None:
        bff_cases = {
            "overview_empty",
            "overview_error",
            "source_ready",
            "source_ambiguous",
            "runs_first_page",
            "runs_second_page",
            "settings_capabilities",
            "verification_run_create",
            "verification_run_partial",
            "verification_not_verifiable",
            "verification_run_mismatch",
            "verification_inconclusive",
            "session_anonymous_200",
            "cursor_context_mismatch_400",
        }
        bff_cases.update(
            {
                "session_required_401",
                "session_anonymous_401",
                "access_pending_403",
                "run_not_found_404",
                "upstream_invalid_502",
                "upstream_unavailable_503",
                "upstream_timeout_504",
                "invalid_query_400",
                "invalid_cursor_400",
                "invalid_scope_422",
                "cursor_expired_410",
                "access_blocked_403",
                "idempotency_conflict_409",
                "rate_limited_429",
                "internal_error_500",
            }
        )

        for case in sorted(bff_cases):
            response = self.adapter.get_bff_response(case)
            self.assertEqual(response["schemaVersion"], "1", case)

    def test_bff_response_does_not_expose_server_side_mapping(self) -> None:
        response = self.adapter.get_bff_response("runs_first_page")

        self.assertNotIn("adapterMappings", response)
        self.assertNotIn("owRunId", repr(response))
        self.assertNotIn("user_id", repr(response))

    def test_ow_case_state_is_available_without_returning_the_fixture_document(
        self,
    ) -> None:
        case = self.adapter.get_ow_case("zero")

        self.assertEqual(case["expected_result"], "zero")
        self.assertEqual(case["response"]["data"][0]["value"], 0)
        self.assertNotIn("responses", case)

    def test_results_are_defensive_copies(self) -> None:
        first = self.adapter.get_bff_response("overview_mixed")
        first["data"]["summary"]["steps"]["value"] = 0
        first["warnings"].clear()

        second = self.adapter.get_bff_response("overview_mixed")

        self.assertEqual(second["data"]["summary"]["steps"]["value"], 8123)
        self.assertEqual(len(second["warnings"]), 3)

    def test_unknown_case_is_rejected_without_path_lookup(self) -> None:
        with self.assertRaises(FixtureContractError):
            self.adapter.get_bff_response("../ui-verification-v1.json")

    def test_fixture_loader_rejects_a_non_fixture_json_path(self) -> None:
        with self.assertRaises(FixtureContractError):
            _load_json_fixture("skills-lock.json")

    def test_impossible_calendar_dates_are_rejected(self) -> None:
        for invalid_date in ("2024-02-30", "2023-02-29", "2024-13-01"):
            with self.subTest(invalid_date=invalid_date):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                activity_summary = ow_document["responses"]["activity_summary"]
                activity_summary["data"][0]["date"] = invalid_date

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_impossible_bff_logical_dates_are_rejected(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        overview = bff_document["responses"]["overview_mixed"]
        overview["data"]["logicalDate"] = "2024-02-30"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_named_cases_reject_wrong_fixture_semantics(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        overview = bff_document["responses"]["overview_mixed"]
        fixture = overview["extensions"]["fixture"]
        fixture["case"] = "overview_empty"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        ow_document["cases"]["zero"]["expected_result"] = "match"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_dynamic_bff_data_rejects_internal_identifier_spellings(self) -> None:
        identifier_keys = (
            "user_id",
            "ow_user_id",
            "userId",
            "owUserId",
            "user_connection_id",
            "userConnectionId",
            "connection_id",
            "connectionId",
            "primary_user_id",
            "primaryUserId",
            "uid",
            "user_uid",
            "userUid",
            "owUid",
            "source_connection_id",
            "sourceConnectionId",
            "batch_id",
            "batchId",
            "run_id",
            "runId",
            "owRunId",
            "ow_run_id",
        )

        for identifier_key in identifier_keys:
            with self.subTest(identifier_key=identifier_key):
                adapter = OfflineFixtureAdapter()
                response = adapter._bff_responses["overview_mixed"]
                steps = response["data"]["summary"]["steps"]
                steps[identifier_key] = "synthetic-id"

                with self.assertRaises(FixtureContractError):
                    adapter.get_bff_response("overview_mixed")

    def test_dynamic_bff_data_rejects_internal_identifier_content(self) -> None:
        adapter = OfflineFixtureAdapter()
        response = adapter._bff_responses["overview_mixed"]
        response["data"]["summary"]["steps"]["unit"] = "user_id"

        with self.assertRaises(FixtureContractError):
            adapter.get_bff_response("overview_mixed")

    def test_dynamic_bff_summary_keys_are_explicitly_allowlisted(self) -> None:
        injected_keys = (
            "https://api.example.test",
            "metadataCopy",
            "runKeySuffix",
        )

        for injected_key in injected_keys:
            with self.subTest(injected_key=injected_key):
                adapter = OfflineFixtureAdapter()
                summary = adapter._bff_responses["overview_mixed"]["data"]["summary"]
                summary[injected_key] = deepcopy(summary["steps"])

                with self.assertRaises(FixtureContractError):
                    adapter.get_bff_response("overview_mixed")

    def test_overview_empty_payload_semantics_are_bound_to_case(self) -> None:
        mutations = (
            lambda overview: overview["data"]["summary"].update(
                {
                    "steps": deepcopy(
                        self.adapter._bff_responses["overview_mixed"]["data"][
                            "summary"
                        ]["steps"]
                    )
                }
            ),
            lambda overview: overview["coverage"].update({"availableDays": 1}),
            lambda overview: overview["coverage"].update({"isPartial": True}),
        )

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(bff_document["responses"]["overview_empty"])

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_source_case_semantics_are_bound_to_payload(self) -> None:
        mutations = (
            (
                "source_ready",
                lambda response: response["data"]["items"].append(
                    deepcopy(response["data"]["items"][0])
                ),
            ),
            (
                "source_ready",
                lambda response: response["data"]["items"][0].update(
                    {"state": "source_ambiguous"}
                ),
            ),
            (
                "source_ambiguous",
                lambda response: response["data"]["items"].pop(),
            ),
            (
                "source_ambiguous",
                lambda response: response["warnings"].clear(),
            ),
        )

        for case, mutation in mutations:
            with self.subTest(case=case, mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(bff_document["responses"][case])

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_verification_run_case_semantics_are_bound_to_payload(self) -> None:
        mutations = (
            (
                "verification_run_create",
                lambda response: response["data"]["verificationRun"].update(
                    {"state": "persisted"}
                ),
            ),
            (
                "verification_run_partial",
                lambda response: response["data"]["verificationRun"][
                    "warnings"
                ].clear(),
            ),
            (
                "verification_run_partial",
                lambda response: response["data"]["verificationRun"]["counts"].update(
                    {"recordsAccepted": None}
                ),
            ),
            (
                "verification_run_mismatch",
                lambda response: response["data"]["verificationRun"].update(
                    {"state": "inconclusive"}
                ),
            ),
            (
                "verification_run_mismatch",
                lambda response: response["data"]["verificationRun"]["results"][
                    0
                ].update({"state": "match"}),
            ),
            (
                "verification_not_verifiable",
                lambda response: response["data"]["verificationRun"].update(
                    {"state": "persisted"}
                ),
            ),
            (
                "verification_not_verifiable",
                lambda response: response["data"]["verificationRun"]["results"].clear(),
            ),
            (
                "verification_inconclusive",
                lambda response: response["data"]["verificationRun"].update(
                    {"state": "persisted"}
                ),
            ),
            (
                "verification_inconclusive",
                lambda response: response["data"]["verificationRun"]["results"][
                    0
                ].update({"state": "match"}),
            ),
        )

        for case, mutation in mutations:
            with self.subTest(case=case, mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(bff_document["responses"][case])

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_metric_state_requires_semantically_matching_value(self) -> None:
        mutations = (
            (
                "activeCaloriesKcal",
                {"value": 1},
            ),
            (
                "recoveryScore",
                {"value": 1},
            ),
            (
                "stress",
                {"value": 1},
            ),
            (
                "stress",
                {"state": "not_verifiable", "value": 1},
            ),
        )

        for metric_name, changes in mutations:
            with self.subTest(metric_name=metric_name, changes=changes):
                adapter = OfflineFixtureAdapter()
                metric = adapter._bff_responses["overview_mixed"]["data"]["summary"][
                    metric_name
                ]
                metric.update(changes)

                with self.assertRaises(FixtureContractError):
                    adapter.get_bff_response("overview_mixed")

    def test_metric_state_requires_value_unit_zero_flag_and_partial_coverage(
        self,
    ) -> None:
        mutations = (
            ("steps", {"state": "value", "value": None}),
            ("distanceMeters", {"state": "partial", "value": None}),
            ("heartRate", {"state": "source_ambiguous", "value": None}),
            ("recoveryScore", {"state": "null", "unit": "count"}),
            ("activeCaloriesKcal", {"isDailyTotal": False}),
            ("activeCaloriesKcal", {"isDailyTotal": None}),
        )

        for metric_name, changes in mutations:
            with self.subTest(metric_name=metric_name, changes=changes):
                adapter = OfflineFixtureAdapter()
                metric = adapter._bff_responses["overview_mixed"]["data"]["summary"][
                    metric_name
                ]
                metric.update(changes)

                with self.assertRaises(FixtureContractError):
                    adapter.get_bff_response("overview_mixed")

        adapter = OfflineFixtureAdapter()
        del adapter._bff_responses["overview_mixed"]["data"]["summary"][
            "distanceMeters"
        ]["coverage"]

        with self.assertRaises(FixtureContractError):
            adapter.get_bff_response("overview_mixed")

    def test_recovery_score_accepts_unitless_integer_values_from_zero_to_100(
        self,
    ) -> None:
        for value, state in ((0, "zero"), (1, "value"), (100, "value")):
            with self.subTest(value=value):
                recovery_score = {
                    "state": state,
                    "value": value,
                    "unit": None,
                    "isDailyTotal": False,
                }

                offline_module._bff_metric(recovery_score, metric_name="recoveryScore")

    def test_only_recovery_score_may_be_non_null_without_a_mapped_unit(self) -> None:
        recovery_score = {
            "state": "value",
            "value": 82,
            "unit": None,
            "isDailyTotal": False,
        }

        with self.assertRaises(FixtureContractError):
            offline_module._bff_metric(recovery_score, metric_name="steps")
        with self.assertRaises(FixtureContractError):
            offline_module._bff_metric(recovery_score, metric_name="stress")

    def test_recovery_score_rejects_non_integer_or_out_of_range_values(self) -> None:
        for value in (-1, 101, 82.5, True):
            with self.subTest(value=value):
                recovery_score = {
                    "state": "value",
                    "value": value,
                    "unit": None,
                    "isDailyTotal": False,
                }

                with self.assertRaises(FixtureContractError):
                    offline_module._bff_metric(
                        recovery_score, metric_name="recoveryScore"
                    )

    def test_terminal_sync_case_rejects_active_incomplete_or_changed_terminal_fields(
        self,
    ) -> None:
        mutations = (
            ("active state", lambda run: run.update({"state": "processing"})),
            ("pending state", lambda run: run.update({"state": "pending"})),
            ("incomplete state", lambda run: run.update({"state": "partial"})),
            ("incomplete progress", lambda run: run.update({"progress": 0.5})),
            (
                "started timestamp",
                lambda run: run.update({"started_at": "2024-01-02T08:30:59Z"}),
            ),
            (
                "ended timestamp",
                lambda run: run.update({"ended_at": "2024-01-02T08:31:05Z"}),
            ),
            (
                "last update timestamp",
                lambda run: run.update({"last_update": "2024-01-02T08:31:05Z"}),
            ),
        )

        for description, mutation in mutations:
            with self.subTest(description=description):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(ow_document["responses"]["sync_runs_terminal"][0])

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_terminal_sync_case_requires_complete_counts_and_item_totals(self) -> None:
        mutations = (
            (
                "missing processed items",
                lambda run: run.update({"items_processed": None}),
            ),
            (
                "missing total items",
                lambda run: run.update({"items_total": None}),
            ),
            (
                "missing saved count",
                lambda run: run["counts"].update({"records_saved": None}),
            ),
            (
                "missing rejected count",
                lambda run: run["counts"].update({"records_rejected": None}),
            ),
        )

        for description, mutation in mutations:
            with self.subTest(description=description):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(ow_document["responses"]["sync_runs_terminal"][0])

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_runs_first_page_rejects_reversed_requested_at_order(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        items = bff_document["responses"]["runs_first_page"]["data"]["items"]
        items.reverse()

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_runs_first_page_allows_equal_requested_at_ties_in_source_order(
        self,
    ) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        items = bff_document["responses"]["runs_first_page"]["data"]["items"]
        items[0]["requestedAt"] = items[1]["requestedAt"]

        adapter = OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        self.assertEqual(
            [
                item["runKey"]
                for item in adapter.get_bff_response("runs_first_page")["data"]["items"]
            ],
            ["verify-demo-01", "verify-demo-02", "verify-demo-03"],
        )

    def test_pending_runs_cannot_carry_terminal_fields_or_results(self) -> None:
        mutations = (
            lambda run: run.update({"startedAt": "2024-01-02T08:00:01Z"}),
            lambda run: run.update({"finishedAt": "2024-01-02T08:00:03Z"}),
            lambda run: run["counts"].update({"recordsSeen": 0}),
            lambda run: run.update(
                {"results": [{"metric": "steps", "state": "match"}]}
            ),
        )

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                run = bff_document["responses"]["verification_run_create"]["data"][
                    "verificationRun"
                ]
                mutation(run)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_run_counts_results_and_warning_shapes_fail_closed(self) -> None:
        mutations = (
            (
                "verification_run_partial",
                lambda run: run["counts"].update({"recordsAccepted": -1}),
            ),
            (
                "verification_run_partial",
                lambda run: run["counts"].update({"recordsAccepted": 13}),
            ),
            (
                "verification_run_partial",
                lambda run: run["results"][0].update({"state": "unknown"}),
            ),
            (
                "verification_run_partial",
                lambda run: run["warnings"][0].update({"severity": "error"}),
            ),
            (
                "verification_run_mismatch",
                lambda run: run["results"][0].update(
                    {
                        "expected": 8123,
                        "observed": 8123,
                    }
                ),
            ),
        )

        for case, mutation in mutations:
            with self.subTest(case=case, mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                run = bff_document["responses"][case]["data"]["verificationRun"]
                mutation(run)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_non_null_sleep_sessions_are_rejected_until_the_shape_is_supported(
        self,
    ) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        sleep_summary = ow_document["responses"]["sleep_summary"]["data"][0]
        sleep_summary["sessions"] = [{"start_time": "2024-01-01T22:30:00Z"}]

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_inventory_keys_and_sync_states_use_safe_allowlisted_grammars(self) -> None:
        mutations = (
            lambda inventory: inventory["series_type_counts"].update(
                {"metric code": 1}
            ),
            lambda inventory: inventory["series_counts"].update({"metric/code": 1}),
            lambda inventory: inventory["by_provider"].update(
                {
                    "provider demo": {
                        "data_points": 1,
                        "workout_count": 0,
                        "sleep_count": 0,
                    }
                }
            ),
        )

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(ow_document["responses"]["summaries_data"])

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        ow_document["responses"]["sync_runs_terminal"][0]["state"] = "unknown"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_unknown_nested_coverage_state_and_result_shapes_fail_closed(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["responses"]["overview_mixed"]["coverage"]["byDomain"]["activity"][
            "state"
        ] = "unknown"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_malformed_enum_values_raise_fixture_contract_error_not_type_error(
        self,
    ) -> None:
        mutations = (
            (
                "overview_mixed",
                lambda response: response["data"]["summary"]["steps"].update(
                    {"state": []}
                ),
            ),
            (
                "source_ready",
                lambda response: response["data"]["items"][0].update({"state": []}),
            ),
            (
                "overview_mixed",
                lambda response: response["coverage"]["byDomain"]["activity"].update(
                    {"state": []}
                ),
            ),
            (
                "overview_mixed",
                lambda response: response["warnings"][0].update({"code": []}),
            ),
        )

        for case, mutation in mutations:
            with self.subTest(case=case, mutation=mutation):
                adapter = OfflineFixtureAdapter()
                mutation(adapter._bff_responses[case])

                with self.assertRaises(FixtureContractError):
                    adapter.get_bff_response(case)

        adapter = OfflineFixtureAdapter()
        adapter._ow_responses["sync_runs_terminal"][0]["state"] = []

        with self.assertRaises(FixtureContractError):
            adapter.get_ow_response("sync_runs_terminal")

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        result = bff_document["responses"]["verification_not_verifiable"]["data"][
            "verificationRun"
        ]["results"][0]
        result["reasonCode"] = "UNKNOWN_REASON"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_match_case_resolves_and_compares_its_observed_reference(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        ow_document["cases"]["match"]["expected"]["value"] = 8124

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        match_case = ow_document["cases"]["match"]
        match_case["observed_ref"] = "responses.timeseries_match.data[1]"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_match_case_compares_instant_offset_and_source_scope(self) -> None:
        mutations = (
            (
                "timestamp",
                lambda sample: sample.update({"timestamp": "2024-01-02T08:01:00Z"}),
            ),
            (
                "zone_offset",
                lambda sample: sample.update({"zone_offset": "+01:00"}),
            ),
            (
                "provider",
                lambda sample: sample["source"].update({"provider": "provider-demo-b"}),
            ),
            (
                "source",
                lambda sample: sample["source"].update({"source": "source-demo-b"}),
            ),
        )

        for field, mutation in mutations:
            with self.subTest(field=field):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                sample = ow_document["responses"]["timeseries_match"]["data"][0]
                mutation(sample)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_adapter_assertions_enforce_the_documented_state_mapping(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["adapter_assertions"][2]["ui_state"] = "persisted"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["adapter_assertions"][0]["ow_stage"] = "unknown"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["adapter_assertions"][0]["ow_status"] = []

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_overview_payload_binds_date_timezone_and_body_warning(self) -> None:
        mutations = (
            lambda response: response["coverage"]["requested"].update(
                {"logicalDate": "2024-01-03"}
            ),
            lambda response: response["coverage"]["requested"].update(
                {"timezone": "Europe/Madrid"}
            ),
            lambda response: response.update({"timezone": "Europe/Madrid"}),
            lambda response: response["warnings"].pop(),
            lambda response: response["coverage"]["byDomain"]["body"].update(
                {"state": "complete"}
            ),
        )

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(bff_document["responses"]["overview_mixed"])

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_free_form_strings_reject_schemes_slashes_nested_escapes_hosts_and_ipv6(
        self,
    ) -> None:
        rejected_values = (
            "label contains javascript:payload",
            "label // another value",
            "%2525252e%2525252e%2525252fprivate",
            "connect to api.example.test now",
            "connect to 2001:db8::1 now",
        )

        for rejected_value in rejected_values:
            with self.subTest(rejected_value=rejected_value):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                bff_document["responses"]["source_ready"]["data"]["items"][0][
                    "label"
                ] = rejected_value

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_recursive_and_oversized_documents_fail_with_fixture_contract_error(
        self,
    ) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["notes"].append(bff_document)

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["notes"].extend(["synthetic"] * 20_000)

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_error_case_semantics_retain_code_field_and_retryability(self) -> None:
        expected = {
            "session_required_401": ("SESSION_REQUIRED", None, False),
            "session_anonymous_401": ("SESSION_REQUIRED", None, False),
            "access_pending_403": ("ACCESS_PENDING", None, False),
            "run_not_found_404": ("RUN_NOT_FOUND", None, False),
            "upstream_invalid_502": ("UPSTREAM_INVALID", None, False),
            "upstream_unavailable_503": ("UPSTREAM_UNAVAILABLE", None, True),
            "upstream_timeout_504": ("UPSTREAM_TIMEOUT", None, True),
            "invalid_query_400": ("INVALID_QUERY", "date", False),
            "invalid_cursor_400": ("INVALID_CURSOR", "cursor", False),
            "cursor_context_mismatch_400": (
                "CURSOR_CONTEXT_MISMATCH",
                "cursor",
                False,
            ),
            "invalid_scope_422": ("INVALID_SCOPE", "domains", False),
            "cursor_expired_410": ("CURSOR_EXPIRED", "cursor", True),
            "access_blocked_403": ("ACCESS_BLOCKED", None, False),
            "idempotency_conflict_409": ("IDEMPOTENCY_CONFLICT", None, False),
            "rate_limited_429": ("RATE_LIMITED", None, True),
            "internal_error_500": ("INTERNAL_ERROR", None, False),
        }

        for case, (code, field, retryable) in expected.items():
            with self.subTest(case=case):
                response = self.adapter.get_bff_response(case)
                error = response["error"]
                self.assertEqual(error["code"], code)
                self.assertEqual(error["field"], field)
                self.assertEqual(error["retryable"], retryable)

                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                error = bff_document["responses"]["errors"][case]["error"]
                error["field"] = "date" if field != "date" else "timezone"
                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                error = bff_document["responses"]["errors"][case]["error"]
                error["retryable"] = not retryable
                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_public_strings_reject_encoded_network_and_identifier_content(self) -> None:
        rejected_values = (
            "javascript:alert(1)",
            "data:text/plain,synthetic",
            "%2e%2e%2fprivate",
            "%252e%252e%252fprivate",
            "2001:db8::1",
            "[2001:db8::1]:443",
            "runIdSuffix leaked",
            "OW user identifier leaked",
            "connection identifier leaked",
            "batch identifier leaked",
        )

        for rejected_value in rejected_values:
            with self.subTest(rejected_value=rejected_value):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                bff_document["responses"]["source_ready"]["data"]["items"][0][
                    "label"
                ] = rejected_value

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_documented_public_string_forms_remain_allowed(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        response = bff_document["responses"]["source_ready"]
        response["timezone"] = "America/New_York"
        response["data"]["items"][0]["label"] = "Fuente sintética A"

        adapter = OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        self.assertEqual(
            adapter.get_bff_response("source_ready")["timezone"], "America/New_York"
        )
        self.assertEqual(
            adapter.get_ow_response("timeseries_match")["data"][0]["zone_offset"],
            "+00:00",
        )

    def test_non_null_internal_connection_ids_are_rejected(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        data_sources = ow_document["responses"]["data_sources"]
        source = data_sources["items"][0]
        source["user_connection_id"] = "connection-demo-01"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_recursive_public_string_validation_rejects_traceable_content(
        self,
    ) -> None:
        uuid_like = "-".join(("a" * 8, "b" * 4, "c" * 4, "d" * 4, "e" * 12))
        mac_like = ":".join(["aa"] * 6)
        email_like = "synthetic" + "@" + "example.invalid"
        host_like = "api" + ".example" + ".test"
        rejected_values = (
            "/" + "synthetic-root/example",
            "C:" + "\\synthetic-root\\example",
            "../private/example",
            host_like,
            "provider exception: details",
            uuid_like,
            mac_like,
            email_like,
        )

        for rejected_value in rejected_values:
            with self.subTest(rejected_value=rejected_value):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                overview = bff_document["responses"]["overview_mixed"]
                warning = overview["warnings"][0]
                warning["message"] = rejected_value

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_recursive_public_string_validation_covers_root_metadata(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        host_like = "api" + ".example" + ".test"
        bff_document["notes"][0] = host_like

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_bff_document_privacy_scan_precedes_specialized_validation(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        source_item = bff_document["responses"]["source_ready"]["data"]["items"][0]
        source_item["label"] = "api.example.test"
        calls: list[str] = []
        original_scan = offline_module._check_keys_recursively
        original_response_validator = offline_module._validate_bff_response

        def record_scan(value: object, *, bff: bool, ow_response: bool = False) -> None:
            if bff:
                calls.append("privacy")
            original_scan(value, bff=bff, ow_response=ow_response)

        def record_response_validator(*args: object, **kwargs: object) -> None:
            calls.append("specialized")
            original_response_validator(*args, **kwargs)

        with (
            patch.object(
                offline_module, "_check_keys_recursively", side_effect=record_scan
            ),
            patch.object(
                offline_module,
                "_validate_bff_response",
                side_effect=record_response_validator,
            ),
            self.assertRaises(FixtureContractError),
        ):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        self.assertEqual(calls[0], "privacy")
        self.assertNotIn("specialized", calls)

    def test_direct_getters_scan_privacy_before_specialized_validation(self) -> None:
        getters = (
            (
                "BFF response",
                lambda: self.adapter.get_bff_response("source_ready"),
                "_validate_bff_response",
            ),
            (
                "OW response",
                lambda: self.adapter.get_ow_response("activity_summary"),
                "_validate_ow_response",
            ),
            (
                "OW case",
                lambda: self.adapter.get_ow_case("match"),
                "_validate_ow_case",
            ),
        )

        for description, getter, validator_name in getters:
            with self.subTest(description=description):
                calls: list[str] = []
                original_scan = offline_module._check_keys_recursively
                original_validator = getattr(offline_module, validator_name)

                def record_scan(
                    value: object,
                    *,
                    bff: bool,
                    ow_response: bool = False,
                    _calls: list[str] = calls,
                    _original_scan: Callable[..., None] = original_scan,
                ) -> None:
                    _calls.append("privacy")
                    _original_scan(value, bff=bff, ow_response=ow_response)

                def record_validator(
                    *args: object,
                    _calls: list[str] = calls,
                    _original_validator: Callable[..., None] = original_validator,
                    **kwargs: object,
                ) -> None:
                    _calls.append("specialized")
                    _original_validator(*args, **kwargs)

                with (
                    patch.object(
                        offline_module,
                        "_check_keys_recursively",
                        side_effect=record_scan,
                    ),
                    patch.object(
                        offline_module,
                        validator_name,
                        side_effect=record_validator,
                    ),
                ):
                    getter()

                expected_calls = ["privacy", "privacy", "specialized"]
                if description != "OW case":
                    expected_calls = ["privacy", "specialized"]
                self.assertEqual(calls, expected_calls)

    def test_ow_case_rejects_unsafe_value_in_ignored_referenced_response_field(
        self,
    ) -> None:
        adapter = OfflineFixtureAdapter()
        observed = adapter._ow_responses["timeseries_match"]["data"][0]
        observed["source"]["device"] = "api" + ".example" + ".test"
        calls: list[str] = []
        original_validator = offline_module._validate_ow_case

        def record_validator(*args: object, **kwargs: object) -> None:
            calls.append("specialized")
            original_validator(*args, **kwargs)

        with (
            patch.object(
                offline_module, "_validate_ow_case", side_effect=record_validator
            ),
            self.assertRaises(FixtureContractError),
        ):
            adapter.get_ow_case("match")

        self.assertEqual(calls, [])

    def test_ow_document_privacy_scan_precedes_specialized_validation(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        activity_summary = ow_document["responses"]["activity_summary"]
        activity_summary["data"][0]["source"]["device"] = "api.example.test"
        calls: list[str] = []
        original_scan = offline_module._check_keys_recursively
        original_response_validator = offline_module._validate_ow_response

        def record_scan(value: object, *, bff: bool, ow_response: bool = False) -> None:
            if not bff and ow_response:
                calls.append("privacy")
            original_scan(value, bff=bff, ow_response=ow_response)

        def record_response_validator(*args: object, **kwargs: object) -> None:
            calls.append("specialized")
            original_response_validator(*args, **kwargs)

        with (
            patch.object(
                offline_module, "_check_keys_recursively", side_effect=record_scan
            ),
            patch.object(
                offline_module,
                "_validate_ow_response",
                side_effect=record_response_validator,
            ),
            self.assertRaises(FixtureContractError),
        ):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        self.assertEqual(calls[0], "privacy")
        self.assertNotIn("specialized", calls)

    def test_warning_and_error_copy_are_allowlisted(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        overview = bff_document["responses"]["overview_mixed"]
        warning = overview["warnings"][0]
        warning["message"] = "provider detail"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["responses"]["errors"]["upstream_timeout_504"]["error"][
            "message"
        ] = "provider timeout details"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_unallowlisted_warning_and_error_keys_are_rejected(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["responses"]["overview_mixed"]["warnings"][0][
            "providerMessage"
        ] = "provider detail"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["responses"]["errors"]["upstream_timeout_504"]["error"][
            "providerError"
        ] = "provider detail"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_warning_and_error_context_values_are_allowlisted(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        warning = bff_document["responses"]["overview_mixed"]["warnings"][0]
        warning["domain"] = "user_id"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        error = bff_document["responses"]["errors"]["upstream_timeout_504"]["error"]
        error["field"] = "user_id"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_missing_required_structure_fails_closed(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        del ow_document["responses"]["activity_summary"]

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_unsafe_safety_flag_fails_closed(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        ow_document["safety"]["contains_secrets"] = True

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_raw_ow_metadata_fails_closed(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        ow_document["responses"]["activity_summary"]["message"] = "provider detail"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_raw_sync_allowlist_fails_closed(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        ow_document["public_sync_projection"]["allowlisted_fields"] = ["metadata"]

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_internal_bff_mapping_in_response_fails_closed(self) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        overview = bff_document["responses"]["overview_mixed"]
        overview["data"]["owRunId"] = "ow-run-demo-99"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_metric_states_require_units_and_reject_zero_as_value(self) -> None:
        missing_unit_cases = (
            "steps",
            "distanceMeters",
            "heartRate",
            "activeCaloriesKcal",
        )

        for metric_name in missing_unit_cases:
            with self.subTest(metric_name=metric_name):
                adapter = OfflineFixtureAdapter()
                metric = adapter._bff_responses["overview_mixed"]["data"]["summary"][
                    metric_name
                ]
                metric["unit"] = None

                with self.assertRaises(FixtureContractError):
                    adapter.get_bff_response("overview_mixed")

        adapter = OfflineFixtureAdapter()
        adapter._bff_responses["overview_mixed"]["data"]["summary"]["steps"][
            "value"
        ] = 0

        with self.assertRaises(FixtureContractError):
            adapter.get_bff_response("overview_mixed")

    def test_metric_units_are_bound_to_their_documented_field_or_type(self) -> None:
        bff_overview_mutations = (
            ("steps", "bpm"),
            ("distanceMeters", "count"),
            ("activeCaloriesKcal", "meters"),
            ("sleepDurationSeconds", "kcal"),
            ("heartRate", "count"),
        )
        for metric_name, unit in bff_overview_mutations:
            with self.subTest(scope="BFF overview", metric_name=metric_name):
                adapter = OfflineFixtureAdapter()
                metric = adapter._bff_responses["overview_mixed"]["data"]["summary"][
                    metric_name
                ]
                metric["unit"] = unit

                with self.assertRaises(FixtureContractError):
                    adapter.get_bff_response("overview_mixed")

        ow_timeseries_mutations = (
            ("timeseries_match", 0, "bpm"),
            ("timeseries_match", 1, "count"),
            ("timeseries_value_null", 0, "count"),
            ("timeseries_is_daily_total_null", 0, "bpm"),
        )
        for case, index, unit in ow_timeseries_mutations:
            with self.subTest(scope="OW timeseries", case=case, index=index):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                ow_document["responses"][case]["data"][index]["unit"] = unit

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        coverage_metric = ow_document["responses"]["coverage"]["timeseries"][0][
            "metrics"
        ][0]
        coverage_metric["unit"] = "bpm"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        ow_document["cases"]["match"]["expected"]["unit"] = "bpm"
        ow_document["responses"]["timeseries_match"]["data"][0]["unit"] = "bpm"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        mismatch_result = bff_document["responses"]["verification_run_mismatch"][
            "data"
        ]["verificationRun"]["results"][0]
        mismatch_result["unit"] = "bpm"

        with self.assertRaises(FixtureContractError):
            OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_metric_unit_values_must_be_strings_before_cross_validation(self) -> None:
        mutations = (
            (
                "BFF overview",
                lambda ow, bff: bff["responses"]["overview_mixed"]["data"]["summary"][
                    "steps"
                ].update({"unit": []}),
            ),
            (
                "OW timeseries",
                lambda ow, bff: ow["responses"]["timeseries_match"]["data"][0].update(
                    {"unit": []}
                ),
            ),
            (
                "OW coverage",
                lambda ow, bff: ow["responses"]["coverage"]["timeseries"][0]["metrics"][
                    0
                ].update({"unit": {}}),
            ),
            (
                "BFF mismatch result",
                lambda ow, bff: bff["responses"]["verification_run_mismatch"]["data"][
                    "verificationRun"
                ]["results"][0].update({"unit": None}),
            ),
        )

        for description, mutation in mutations:
            with self.subTest(description=description):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(ow_document, bff_document)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_overview_window_is_exact_local_midnight_window(self) -> None:
        mutations = (
            lambda requested: requested.update(
                {"from": "2024-01-02T01:00:00Z", "to": "2024-01-03T01:00:00Z"}
            ),
            lambda requested: requested.update(
                {"from": "2024-01-03T00:00:00Z", "to": "2024-01-02T00:00:00Z"}
            ),
            lambda requested: requested.update({"from": 1}),
        )

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                requested = bff_document["responses"]["overview_mixed"]["coverage"][
                    "requested"
                ]
                mutation(requested)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_bound_warning_domains_are_required_and_exact(self) -> None:
        mutations = (
            ("missing body domain", lambda warnings: warnings[2].pop("domain")),
            (
                "wrong source domain",
                lambda warnings: warnings[1].update({"domain": "body"}),
            ),
            (
                "wrong partial domain",
                lambda warnings: warnings[0].update({"domain": "sleep"}),
            ),
        )

        for description, mutation in mutations:
            with self.subTest(description=description):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(bff_document["responses"]["overview_mixed"]["warnings"])

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_sync_mapping_accepts_active_null_status_and_maps_typed_unknown_combinations(
        self,
    ) -> None:
        ow_document = deepcopy(self.adapter._ow_document)
        bff_document = deepcopy(self.adapter._bff_document)
        bff_document["adapter_assertions"].append(
            {"ow_stage": "queued", "ow_status": None, "ui_state": "pending"}
        )
        bff_document["adapter_assertions"].append(
            {
                "ow_stage": "new-demo-stage",
                "ow_status": "new-demo-status",
                "ui_state": "inconclusive",
            }
        )
        bff_document["adapterMappings"]["verificationRuns"].append(
            {
                "runKey": "verify-demo-09",
                "owRunId": "ow-run-demo-09",
                "owStage": "new-demo-stage",
                "owStatus": "new-demo-status",
            }
        )

        adapter = OfflineFixtureAdapter.from_documents(ow_document, bff_document)
        self.assertEqual(
            adapter.get_bff_response("overview_mixed")["schemaVersion"], "1"
        )

    def test_integer_metric_fields_reject_fractional_values(self) -> None:
        mutations = (
            (
                "timeseries count",
                lambda ow, bff: ow["responses"]["timeseries_match"]["data"][0].update(
                    {"value": 8123.5}
                ),
            ),
            (
                "match expected and observed count",
                lambda ow, bff: (
                    ow["cases"]["match"]["expected"].update({"value": 8123.5}),
                    ow["responses"]["timeseries_match"]["data"][0].update(
                        {"value": 8123.5}
                    ),
                ),
            ),
            (
                "activity steps",
                lambda ow, bff: ow["responses"]["activity_summary"]["data"][0].update(
                    {"steps": 8123.5}
                ),
            ),
            (
                "activity floors",
                lambda ow, bff: ow["responses"]["activity_summary"]["data"][0].update(
                    {"floors_climbed": 4.5}
                ),
            ),
            (
                "activity active minutes",
                lambda ow, bff: ow["responses"]["activity_summary"]["data"][0].update(
                    {"active_minutes": 35.5}
                ),
            ),
            (
                "activity sedentary minutes",
                lambda ow, bff: ow["responses"]["activity_summary"]["data"][0].update(
                    {"sedentary_minutes": 1.5}
                ),
            ),
            (
                "sleep duration minutes",
                lambda ow, bff: ow["responses"]["sleep_summary"]["data"][0].update(
                    {"duration_minutes": 420.5}
                ),
            ),
            (
                "sleep nap count",
                lambda ow, bff: ow["responses"]["sleep_summary"]["data"][0].update(
                    {"nap_count": 0.5}
                ),
            ),
            (
                "recovery score",
                lambda ow, bff: ow["responses"]["recovery_summary"]["data"][0].update(
                    {"recovery_score": 82.5}
                ),
            ),
            (
                "BFF steps",
                lambda ow, bff: bff["responses"]["overview_mixed"]["data"]["summary"][
                    "steps"
                ].update({"value": 8123.5}),
            ),
            (
                "BFF sleep duration",
                lambda ow, bff: bff["responses"]["overview_mixed"]["data"]["summary"][
                    "sleepDurationSeconds"
                ].update({"value": 25200.5}),
            ),
            (
                "BFF mismatch counts",
                lambda ow, bff: bff["responses"]["verification_run_mismatch"]["data"][
                    "verificationRun"
                ]["results"][0].update({"expected": 8123.5, "observed": 8124.5}),
            ),
        )

        for field, mutation in mutations:
            with self.subTest(field=field):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(ow_document, bff_document)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_integer_metric_fields_reject_boolean_values(self) -> None:
        mutations = (
            (
                "activity steps",
                lambda ow, bff: ow["responses"]["activity_summary"]["data"][0].update(
                    {"steps": True}
                ),
            ),
            (
                "recovery score",
                lambda ow, bff: ow["responses"]["recovery_summary"]["data"][0].update(
                    {"recovery_score": True}
                ),
            ),
            (
                "BFF count",
                lambda ow, bff: bff["responses"]["verification_run_partial"]["data"][
                    "verificationRun"
                ]["counts"].update({"recordsSeen": True}),
            ),
        )

        for field, mutation in mutations:
            with self.subTest(field=field):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(ow_document, bff_document)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_partial_metric_coverage_requires_strict_fraction_and_observation(
        self,
    ) -> None:
        mutations = (
            ("zero fraction", {"observedFraction": 0}),
            ("complete fraction", {"observedFraction": 1}),
            ("zero available days", {"availableDays": 0}),
        )

        for description, changes in mutations:
            with self.subTest(description=description):
                adapter = OfflineFixtureAdapter()
                coverage = adapter._bff_responses["overview_mixed"]["data"]["summary"][
                    "distanceMeters"
                ]["coverage"]
                coverage.update(changes)

                with self.assertRaises(FixtureContractError):
                    adapter.get_bff_response("overview_mixed")

    def test_sync_stream_replay_is_bounded_to_the_documented_range(self) -> None:
        for replay in (0, 201):
            with self.subTest(replay=replay):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                ow_document["responses"]["sync_stream"]["replay"] = replay

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_reserved_content_is_checked_in_metric_provider_and_code_positions(
        self,
    ) -> None:
        mutations = (
            (
                "metric type",
                lambda ow, bff: ow["responses"]["timeseries_value_null"]["data"][
                    0
                ].update({"type": "user_id"}),
            ),
            (
                "provider",
                lambda ow, bff: ow["responses"]["timeseries_value_null"]["data"][0][
                    "source"
                ].update({"provider": "run-id"}),
            ),
            (
                "coverage code",
                lambda ow, bff: ow["responses"]["coverage"]["timeseries"][0]["metrics"][
                    0
                ].update({"code": "batch_id"}),
            ),
            (
                "raw upstream code",
                lambda ow, bff: ow["responses"]["coverage"]["timeseries"][0]["metrics"][
                    0
                ].update({"code": "provider_error"}),
            ),
        )

        for field, mutation in mutations:
            with self.subTest(field=field):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(ow_document, bff_document)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_numeric_ranges_reject_negative_values_and_out_of_range_percentages(
        self,
    ) -> None:
        mutations = (
            lambda document: document["responses"]["activity_summary"]["data"][
                0
            ].update({"distance_meters": -1}),
            lambda document: document["responses"]["sleep_summary"]["data"][0].update(
                {"efficiency_percent": 101}
            ),
            lambda document: document["responses"]["recovery_summary"]["data"][
                0
            ].update({"recovery_score": -1}),
            lambda document: document["responses"]["body_summary_relative_now"][
                "slow_changing"
            ].update({"body_fat_percent": 101}),
            lambda document: document["responses"]["workouts_aggregate"]["data"][
                0
            ].update({"distance_meters": -1}),
        )

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(ow_document)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_body_request_ranges_and_reversed_intervals_are_rejected(self) -> None:
        mutations = (
            lambda body: body["request"].update({"average_period": 0}),
            lambda body: body["request"].update({"average_period": 8}),
            lambda body: body["request"].update({"latest_window_hours": 0}),
            lambda body: body["request"].update({"latest_window_hours": 25}),
            lambda body: body["latest"].update(
                {
                    "body_temperature_celsius": 1,
                    "body_temperature_measured_at": "2024-01-03T00:00:00Z",
                }
            ),
        )

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                body = ow_document["responses"]["body_summary_relative_now"]
                mutation(body)
                if mutation is mutations[-1]:
                    body["averaged"]["period_end"] = "2023-12-27T12:00:00Z"

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_every_observed_reference_must_resolve(self) -> None:
        reference_cases = (
            "summaries_data",
            "events_sleep",
            "sync_stream",
            "value_null",
            "is_daily_total_null",
        )

        for case in reference_cases:
            with self.subTest(case=case):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                ow_document["cases"][case]["observed_ref"] = "responses.missing"

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_free_form_labels_notes_and_exception_copy_are_closed(self) -> None:
        mutations = (
            lambda document: document["responses"]["source_ready"]["data"]["items"][
                0
            ].update({"label": "Fuente sintética Z"}),
            lambda document: document["notes"].__setitem__(0, "Nueva nota sintética"),
            lambda document: document["responses"]["source_ready"]["data"]["items"][
                0
            ].update({"label": "api-key token leaked"}),
            lambda document: document["responses"]["source_ready"]["data"]["items"][
                0
            ].update({"label": "RuntimeError: provider details"}),
        )

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(bff_document)

                with self.assertRaises(FixtureContractError):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

    def test_metadata_enum_narrative_text_is_rejected_before_specialized_validation(
        self,
    ) -> None:
        mutations = (
            (
                "software_version",
                lambda ow, bff: ow["responses"]["data_sources"]["items"][0].update(
                    {"software_version": "fixture release notes"}
                ),
                "_validate_ow_response",
            ),
            (
                "requested_capability",
                lambda ow, bff: ow["cases"]["unsupported"].update(
                    {"requested_capability": "extended workout details are unavailable"}
                ),
                "_validate_ow_case",
            ),
            (
                "owStage",
                lambda ow, bff: bff["adapterMappings"]["verificationRuns"][0].update(
                    {"owStage": "sync stage narrative"}
                ),
                "_validate_adapter_mapping",
            ),
            (
                "owStatus",
                lambda ow, bff: bff["adapterMappings"]["verificationRuns"][0].update(
                    {"owStatus": "sync status narrative"}
                ),
                "_validate_adapter_mapping",
            ),
            (
                "adapter assertion stage",
                lambda ow, bff: bff["adapter_assertions"][2].update(
                    {"ow_stage": "assertion stage narrative"}
                ),
                "_validate_adapter_assertion",
            ),
            (
                "adapter assertion status",
                lambda ow, bff: bff["adapter_assertions"][2].update(
                    {"ow_status": "assertion status narrative"}
                ),
                "_validate_adapter_assertion",
            ),
            (
                "adapter assertion UI state",
                lambda ow, bff: bff["adapter_assertions"][0].update(
                    {"ui_state": "assertion UI state narrative"}
                ),
                "_validate_adapter_assertion",
            ),
            (
                "fixture case",
                lambda ow, bff: bff["responses"]["overview_mixed"]["extensions"][
                    "fixture"
                ].update({"case": "fixture narrative case"}),
                "_validate_bff_response",
            ),
        )

        for description, mutation, validator_name in mutations:
            with self.subTest(description=description):
                ow_document = deepcopy(self.adapter._ow_document)
                bff_document = deepcopy(self.adapter._bff_document)
                mutation(ow_document, bff_document)
                calls: list[str] = []
                original_validator = getattr(offline_module, validator_name)

                def record_validator(
                    *args: object,
                    _calls: list[str] = calls,
                    _original_validator: Callable[..., None] = original_validator,
                    **kwargs: object,
                ) -> None:
                    _calls.append("specialized")
                    _original_validator(*args, **kwargs)

                with (
                    patch.object(
                        offline_module,
                        validator_name,
                        side_effect=record_validator,
                    ),
                    self.assertRaises(FixtureContractError),
                ):
                    OfflineFixtureAdapter.from_documents(ow_document, bff_document)

                self.assertEqual(calls, [], description)


if __name__ == "__main__":
    unittest.main()
