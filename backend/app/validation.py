"""Semantic, locatable validation on top of the request JSON payload."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .models import FieldError


def _diag_lengths(R: int, C: int) -> List[int]:
    """Line lengths in index order for either diagonal family.

    Both families (r-c keys -(C-1)..R-1 and r+c keys 0..R+C-2) have the
    same ordered lengths: 1,2,...,min(R,C),...,2,1.
    """
    nd = R + C - 1
    return [min(k + 1, R, C, nd - k) for k in range(nd)]


def validate_payload(payload: Any) -> Tuple[Dict[str, Any], List[FieldError]]:
    """Validate a decoded JSON payload.

    Returns (clean payload, errors).  When errors is non-empty the clean
    payload is undefined.  Every error carries a dotted ``field`` path such
    as ``row[2]`` or ``known[3].col`` so the UI can locate the problem.
    """
    errors: List[FieldError] = []

    if not isinstance(payload, dict):
        return {}, [FieldError(field="$", code="not_object",
                               message="请求体必须是 JSON 对象")]

    def is_int(x: Any) -> bool:
        return isinstance(x, int) and not isinstance(x, bool)

    R = payload.get("rows")
    C = payload.get("cols")
    for name, v in (("rows", R), ("cols", C)):
        if not is_int(v):
            errors.append(FieldError(field=name, code="not_integer",
                                     message=f"{name} 必须是整数"))
        elif not (4 <= v <= 12):
            errors.append(FieldError(field=name, code="out_of_range",
                                     message=f"{name} 必须在 4 到 12 之间（当前 {v}）"))
    if not (is_int(R) and is_int(C) and 4 <= R <= 12 and 4 <= C <= 12):
        return payload, errors

    nd = R + C - 1
    diag_len = _diag_lengths(R, C)

    def check_vector(name: str, value: Any, length: int, bounds: List[int]) -> List[int]:
        if not isinstance(value, list):
            errors.append(FieldError(field=name, code="not_array",
                                     message=f"{name} 必须是长度为 {length} 的数组"))
            return []
        if len(value) != length:
            errors.append(FieldError(
                field=name, code="bad_length",
                message=f"{name} 长度必须为 {length}（当前 {len(value)}）"))
        clean: List[int] = []
        for i, x in enumerate(value):
            loc = f"{name}[{i}]"
            if not is_int(x):
                errors.append(FieldError(field=loc, code="not_integer",
                                         message=f"{loc} 必须是整数"))
                continue
            clean.append(x)
            if x < 0:
                errors.append(FieldError(field=loc, code="negative",
                                         message=f"{loc} 不能为负数"))
            elif i < len(bounds) and x > bounds[i]:
                errors.append(FieldError(
                    field=loc, code="too_large",
                    message=f"{loc}={x} 超过该线单元数 {bounds[i]}"))
        return clean

    rowv = check_vector("row", payload.get("row"), R, [C] * R)
    colv = check_vector("col", payload.get("col"), C, [R] * C)
    diffv = check_vector("diff", payload.get("diff"), nd, diag_len)
    sumv = check_vector("sum", payload.get("sum"), nd, diag_len)

    # Known cells: duplicate or conflicting declarations are rejected.
    raw_known = payload.get("known", [])
    if not isinstance(raw_known, list):
        errors.append(FieldError(field="known", code="not_array",
                                 message="known 必须是数组"))
        raw_known = []
    seen: Dict[Tuple[int, int], Tuple[int, int]] = {}
    clean_known: List[Dict[str, int]] = []
    for i, cell in enumerate(raw_known):
        if not isinstance(cell, dict):
            errors.append(FieldError(field=f"known[{i}]", code="not_object",
                                     message="已知单元必须是对象"))
            continue
        r, c, v = cell.get("row"), cell.get("col"), cell.get("value")
        coords_ok = all(is_int(x) for x in (r, c))
        if not is_int(v) or v not in (0, 1):
            errors.append(FieldError(field=f"known[{i}].value", code="bad_value",
                                     message=f"known[{i}].value 必须是 0 或 1"))
        if coords_ok and not (0 <= r < R):
            errors.append(FieldError(field=f"known[{i}].row", code="out_of_range",
                                     message=f"known[{i}].row={r} 超出 [0,{R - 1}]"))
        if coords_ok and not (0 <= c < C):
            errors.append(FieldError(field=f"known[{i}].col", code="out_of_range",
                                     message=f"known[{i}].col={c} 超出 [0,{C - 1}]"))
        if not (coords_ok and is_int(v) and v in (0, 1)):
            continue
        if (r, c) in seen:
            prev_i, prev_v = seen[(r, c)]
            code = "duplicate" if prev_v == v else "conflict"
            desc = "重复" if prev_v == v else f"冲突（known[{prev_i}]={prev_v}）"
            errors.append(FieldError(
                field=f"known[{i}]", code=code,
                message=f"单元 ({r},{c}) {desc}，不得重复或冲突"))
        else:
            seen[(r, c)] = (i, v)
            clean_known.append({"row": r, "col": c, "value": v})

    # Global total consistency: every family counts the same number of 1s.
    vectors = {"row": rowv, "col": colv, "diff": diffv, "sum": sumv}
    totals = {name: sum(v) for name, v in vectors.items() if len(v) == (
        R if name == "row" else C if name == "col" else nd)}
    if len(set(totals.values())) > 1:
        ref_name = next(iter(totals))
        ref_total = totals[ref_name]
        for name, t in totals.items():
            if t != ref_total:
                errors.append(FieldError(
                    field=name, code="total_mismatch",
                    message=(f"{name} 投影总和为 {t}，与 {ref_name} 总和 {ref_total} 不一致"
                             "（四向投影必须统计同样多的夹杂）")))

    # Known cell vs. every incident line target:
    #   v=1 requires target >= 1; v=0 requires target <= line_length - 1.
    if len(rowv) == R and len(colv) == C and len(diffv) == nd and len(sumv) == nd:
        for cell in clean_known:
            r, c, v = cell["row"], cell["col"], cell["value"]
            incident = [
                (f"row[{r}]", rowv[r], C),
                (f"col[{c}]", colv[c], R),
                (f"diff[{r - c + C - 1}]", diffv[r - c + C - 1],
                 diag_len[r - c + C - 1]),
                (f"sum[{r + c}]", sumv[r + c], diag_len[r + c]),
            ]
            for loc, t, length in incident:
                if v == 1 and t < 1:
                    errors.append(FieldError(
                        field=loc, code="known_contradicts_line",
                        message=f"已知单元 ({r},{c})=1，但 {loc} 的目标值为 {t}"))
                if v == 0 and t > length - 1:
                    errors.append(FieldError(
                        field=loc, code="known_contradicts_line",
                        message=(f"已知单元 ({r},{c})=0，但 {loc} 的 {length} 个单元"
                                 f"必须全部为 1（目标值 {t}）")))

    if errors:
        return payload, errors

    return {
        "rows": R,
        "cols": C,
        "row": rowv,
        "col": colv,
        "diff": diffv,
        "sum": sumv,
        "known": clean_known,
    }, []
