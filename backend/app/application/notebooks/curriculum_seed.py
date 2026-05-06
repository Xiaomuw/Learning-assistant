from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[3]
CURRICULUM_DIR = BACKEND_ROOT / "storage" / "data" / "curriculum"


def _normalize_package_id(package_id: str) -> str:
    return package_id.strip().lower()


def list_curriculum_package_ids() -> list[str]:
    if not CURRICULUM_DIR.exists():
        return []
    return sorted(path.stem for path in CURRICULUM_DIR.glob("*.json"))


def load_curriculum_package(package_id: str) -> dict[str, Any]:
    normalized_id = _normalize_package_id(package_id)
    path = CURRICULUM_DIR / f"{normalized_id}.json"
    if not path.exists():
        raise ValueError(f"未知 curriculum 包: {package_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("subjects"):
        raise ValueError(f"curriculum 包格式不正确: {path}")
    payload.setdefault("id", normalized_id)
    return payload


def load_curriculum_packages(package_ids: list[str] | None = None) -> list[dict[str, Any]]:
    effective_ids = package_ids or list_curriculum_package_ids()
    return [load_curriculum_package(package_id) for package_id in effective_ids]


def iter_curriculum_branches(
    package_ids: list[str] | None = None,
    *,
    subject_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    for package in load_curriculum_packages(package_ids):
        package_id = str(package.get("id") or "").strip()
        default_source_name = str(package.get("default_source_name") or f"原创-{package_id}常考题型")
        default_exam_scopes = list(package.get("exam_scopes") or [])
        for subject in package.get("subjects", []):
            subject_id = str(subject.get("subject_id") or "").strip()
            if subject_ids and subject_id not in subject_ids:
                continue
            for chapter in subject.get("chapters", []):
                chapter_key = str(chapter.get("chapter_key") or "").strip()
                chapter_title = str(chapter.get("chapter_title") or "").strip()
                for branch in chapter.get("branches", []):
                    branch_key = str(branch.get("branch_key") or "").strip()
                    if not subject_id or not branch_key:
                        continue
                    branch_payload = dict(branch)
                    branch_payload.update(
                        {
                            "package_id": package_id,
                            "package_title": str(package.get("title") or package_id),
                            "source_name": default_source_name,
                            "subject_id": subject_id,
                            "subject_name": str(subject.get("subject_name") or subject_id),
                            "chapter_key": chapter_key,
                            "chapter_title": chapter_title,
                            "exam_scopes": list(branch.get("exam_scopes") or default_exam_scopes),
                        }
                    )
                    branches.append(branch_payload)
    return branches


def _unit_key(prefix: str, index: int, text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-").lower()
    if not slug:
        slug = f"{prefix}-{index}"
    return f"{prefix}-{index}-{slug[:32]}"


def iter_curriculum_learning_units(
    package_ids: list[str] | None = None,
    *,
    subject_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Expand each branch into granular knowledge points for RAG and mastery tracking."""
    units: list[dict[str, Any]] = []
    for branch in iter_curriculum_branches(package_ids, subject_ids=subject_ids):
        base_point = str(branch.get("knowledge_point") or branch.get("branch_title") or "").strip()
        units.append(
            {
                **branch,
                "unit_key": "core",
                "unit_kind": "chapter",
                "doc_type": "chapter",
                "knowledge_point": base_point,
                "unit_title": str(branch.get("branch_title") or base_point),
                "unit_content": str(branch.get("core_explanation") or ""),
            }
        )
        for index, pattern in enumerate(branch.get("exam_patterns") or [], start=1):
            pattern_text = str(pattern).strip()
            if not pattern_text:
                continue
            units.append(
                {
                    **branch,
                    "unit_key": _unit_key("pattern", index, pattern_text),
                    "unit_kind": "exam_pattern",
                    "doc_type": "exam_pattern",
                    "knowledge_point": f"{base_point}：{pattern_text}",
                    "unit_title": f"{base_point} 常考题型 {index}",
                    "unit_content": pattern_text,
                }
            )
        for index, check in enumerate(branch.get("mastery_checks") or [], start=1):
            check_text = str(check).strip()
            if not check_text:
                continue
            units.append(
                {
                    **branch,
                    "unit_key": _unit_key("check", index, check_text),
                    "unit_kind": "mastery_check",
                    "doc_type": "exam_pattern",
                    "knowledge_point": f"{base_point}：{check_text}",
                    "unit_title": f"{base_point} 掌握度检查 {index}",
                    "unit_content": check_text,
                }
            )
    return units


def _lines(title: str, values: list[str]) -> str:
    if not values:
        return ""
    return f"{title}\n" + "\n".join(f"- {value}" for value in values if value)


def build_curriculum_seed_payload(
    package_ids: list[str] | None = None,
    *,
    subject_ids: set[str] | None = None,
) -> dict[str, tuple[list[str], list[dict[str, Any]]]]:
    """Build chapter and exam-pattern vector payloads grouped by notebook."""
    grouped: dict[str, tuple[list[str], list[dict[str, Any]]]] = {}
    for unit in iter_curriculum_learning_units(package_ids, subject_ids=subject_ids):
        subject_id = unit["subject_id"]
        texts, metadatas = grouped.setdefault(subject_id, ([], []))
        package_id = unit["package_id"]
        branch_key = unit["branch_key"]
        unit_key = unit["unit_key"]
        chapter_title = unit["chapter_title"]
        branch_title = str(unit.get("branch_title") or branch_key)
        knowledge_point = str(unit.get("knowledge_point") or branch_title)
        exam_scopes = list(unit.get("exam_scopes") or [])
        common_metadata = {
            "subject_id": subject_id,
            "source": f"seed:curriculum:{package_id}",
            "knowledge_point": knowledge_point,
            "chapter": chapter_title,
            "branch": branch_title,
            "unit_kind": unit["unit_kind"],
            "exam_scope": exam_scopes,
            "package_id": package_id,
        }

        text = "\n\n".join(
            part
            for part in [
                f"{chapter_title} / {branch_title} / {unit['unit_title']}",
                str(unit.get("unit_content") or "").strip(),
                f"核心解释：{unit.get('core_explanation')}" if unit.get("unit_kind") != "chapter" else "",
                _lines("常考题型", list(unit.get("exam_patterns") or [])),
                _lines("易错点", list(unit.get("pitfalls") or [])),
                _lines("掌握度检查点", list(unit.get("mastery_checks") or [])),
            ]
            if part
        )
        texts.append(text)
        metadatas.append(
            {
                **common_metadata,
                "doc_type": unit["doc_type"],
                "source_id": f"curriculum:{package_id}:{subject_id}:{branch_key}:{unit_key}",
            }
        )
    return grouped


def _generated_options(
    *,
    correct_text: str,
    knowledge_point: str,
    pitfall: str,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    options = [
        {"key": "A", "text": correct_text},
        {"key": "B", "text": f"只要记住 {knowledge_point} 的定义，就不需要分析题目条件。"},
        {"key": "C", "text": pitfall or "可以忽略边界条件和适用前提，直接套用固定公式。"},
        {"key": "D", "text": "所有相关题目都能用同一种步骤解决，复杂度和条件不会影响答案。"},
    ]
    rationales = {
        "A": "该选项抓住了本知识点在考试中的关键判断依据。",
        "B": "定义是起点，但考试通常会结合条件、复杂度或边界场景考查。",
        "C": "这是常见误区，容易在条件变化或边界情况下得到错误结论。",
        "D": "该说法过于绝对，忽略了题型差异和适用条件。",
    }
    return options, rationales


def _generated_check_options(
    *,
    correct_text: str,
    knowledge_point: str,
    pitfall: str,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    options = [
        {"key": "A", "text": correct_text},
        {"key": "B", "text": f"只看一遍 {knowledge_point} 的结论，不做条件判断。"},
        {"key": "C", "text": pitfall or "把相近概念混用，只要结果看起来合理即可。"},
        {"key": "D", "text": "优先背答案模板，不需要解释为什么其他选项不成立。"},
    ]
    rationales = {
        "A": "掌握度检查应能验证概念、条件和步骤，而不是只记忆结论。",
        "B": "被动阅读无法确认是否会在题目中正确使用该知识点。",
        "C": "混用概念是常见错误，恰好需要通过检查点暴露出来。",
        "D": "只背模板无法支持迁移应用，也不利于错题复盘。",
    }
    return options, rationales


def _question_items_for_unit(unit: dict[str, Any]) -> list[dict[str, Any]]:
    explicit_questions = unit.get("questions")
    if isinstance(explicit_questions, list) and explicit_questions:
        items: list[dict[str, Any]] = []
        for index, raw_question in enumerate(explicit_questions, start=1):
            item = dict(raw_question)
            item.setdefault(
                "id",
                f"curriculum:{unit['package_id']}:{unit['subject_id']}:{unit['branch_key']}:{unit['unit_key']}:q{index}",
            )
            item.setdefault("subject_id", unit["subject_id"])
            item.setdefault("knowledge_point", unit.get("knowledge_point") or unit.get("branch_title"))
            item.setdefault("source_name", unit["source_name"])
            item.setdefault("source_year", None)
            item.setdefault("difficulty", "基础")
            item.setdefault("tags", [unit["package_id"], "原创模拟", "curriculum-seed"])
            items.append(item)
        return items

    knowledge_point = str(unit.get("knowledge_point") or unit.get("branch_title") or "")
    patterns = [str(value) for value in (unit.get("exam_patterns") or []) if str(value).strip()]
    checks = [str(value) for value in (unit.get("mastery_checks") or []) if str(value).strip()]
    pitfalls = [str(value) for value in (unit.get("pitfalls") or []) if str(value).strip()]
    pattern = str(unit.get("unit_content") or "").strip() or (
        patterns[0] if patterns else f"围绕 {knowledge_point} 判断条件、复杂度和适用场景"
    )
    check = checks[0] if checks else f"能解释 {knowledge_point} 的核心条件并完成一道基础题"
    pitfall = pitfalls[0] if pitfalls else ""

    first_options, first_rationales = _generated_options(
        correct_text=pattern,
        knowledge_point=knowledge_point,
        pitfall=pitfall,
    )
    second_options, second_rationales = _generated_check_options(
        correct_text=check,
        knowledge_point=knowledge_point,
        pitfall=pitfall,
    )
    base_id = f"curriculum:{unit['package_id']}:{unit['subject_id']}:{unit['branch_key']}:{unit['unit_key']}"
    common = {
        "subject_id": unit["subject_id"],
        "knowledge_point": knowledge_point,
        "source_name": unit["source_name"],
        "source_year": None,
        "tags": [
            unit["package_id"],
            "原创模拟",
            "curriculum-seed",
            str(unit.get("unit_kind") or ""),
            *[str(scope) for scope in unit.get("exam_scopes", [])],
        ],
    }
    return [
        {
            **common,
            "id": f"{base_id}:q1",
            "question": f"关于“{knowledge_point}”的常考判断，哪一项最符合考试要求？",
            "options": first_options,
            "correct_option": "A",
            "explanation": f"本题考查 {knowledge_point} 的题型识别。应优先抓住：{pattern}",
            "option_rationales": first_rationales,
            "difficulty": "基础",
        },
        {
            **common,
            "id": f"{base_id}:q2",
            "question": f"复习“{knowledge_point}”时，下列哪项最适合作为掌握度检查？",
            "options": second_options,
            "correct_option": "A",
            "explanation": f"掌握度检查应能验证是否真的会用 {knowledge_point}，推荐检查点是：{check}",
            "option_rationales": second_rationales,
            "difficulty": "提高",
        },
    ]


def build_curriculum_question_items(
    package_ids: list[str] | None = None,
    *,
    subject_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for unit in iter_curriculum_learning_units(package_ids, subject_ids=subject_ids):
        items.extend(_question_items_for_unit(unit))
    return items
