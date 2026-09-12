from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone


TAIPEI = timezone(timedelta(hours=8))


def contract_only_sealed_result(
    *,
    now: datetime | None = None,
    generation_id: str = "20260912T000000_000000",
) -> dict[str, object]:
    """Return the smallest schema-valid result for pure validator tests.

    This object is never served over HTTP and is not evidence of a LIVE run.
    """
    current = now or datetime.now(timezone.utc)
    generated_at = current.astimezone(TAIPEI).isoformat(timespec="seconds")
    return {
        "schema_version": "youbike.sealed_result.v1",
        "generated_at": generated_at,
        "runtime_mode": "LIVE",
        "live_scope": {
            "city": "新北市",
            "data_class": "sanitized_live_dispatch_result",
            "generation_id": generation_id,
            "manifest_sha256": "0" * 64,
            "private_input_sha256": "1" * 64,
            "source_snapshot_at": generated_at,
        },
        "proof_boundary": {
            "algorithm_visibility": "black_box",
            "raw_data_visibility": "not_in_public_response",
            "frontend_calculation_policy": "display_only",
            "integrity_policy": "manifest_and_payload_hash_required",
        },
        "summary": {
            "district_count": 1,
            "critical_count": 0,
            "warning_count": 0,
            "stable_count": 1,
            "active_case_count": 1,
            "mode_banner": "契約驗證專用",
            "operator_message": "此資料只驗證公開契約與欄位邊界。",
        },
        "districts": [
            {
                "district_id": "ntpc-contract",
                "name": "契約測試區",
                "priority_band": "low",
                "action_label": "observe",
                "explanation_text": "只驗證公開欄位，不執行或模擬黑箱演算。",
            }
        ],
        "selected_cases": [
            {
                "case_id": "case-contract-primary",
                "district_id": "ntpc-contract",
                "display_name": "契約狀態機測試",
                "priority_band": "low",
                "action_label": "observe",
                "route_handoff": {
                    "present": True,
                    "label": "契約測試路線",
                },
                "explanation_text": "只驗證任務資料契約與狀態轉移。",
            }
        ],
    }


def task_store_seed(case_count: int = 2) -> dict[str, object]:
    """Return a minimal TaskStore input without any runtime-mode claim."""
    template = contract_only_sealed_result()["selected_cases"][0]
    cases = []
    for index in range(case_count):
        case = deepcopy(template)
        suffix = "primary" if index == 0 else f"secondary-{index}"
        case["case_id"] = f"case-contract-{suffix}"
        case["display_name"] = f"契約狀態機測試 {index + 1}"
        cases.append(case)
    return {
        "live_scope": {"generation_id": "20260912T000000_000001"},
        "selected_cases": cases,
    }
