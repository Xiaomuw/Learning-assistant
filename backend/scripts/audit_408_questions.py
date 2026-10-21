"""408 题库抽检审阅脚本。

执行目标：
1) 全量规则复检（字段、分布、选项、重复、可疑占位符）
2) 按 12% 或自定义比例分层抽检
3) 输出可解释报告（通过/警告/不建议保留 + 风险 Top）

请仅使用合法取得的私有题库（需显式传入文件路径）：
  python scripts/audit_408_questions.py --path /secure/authorized-questions.json --seed 2026
  python scripts/audit_408_questions.py --path /secure/authorized-questions.json --sample-size 64 --json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.knowledge.concept_registry import get_concept_registry


VALID_OPTIONS = {"A", "B", "C", "D"}
DIFFICULTY_CANON = {
    "basic": "basic",
    "easy": "basic",
    "简单": "basic",
    "simple": "basic",
    "medium": "medium",
    "中等": "medium",
    "变式": "medium",
    "hard": "hard",
    "困难": "hard",
    "难": "hard",
    "易错": "hard",
    "基础": "basic",
}


@dataclass(frozen=True)
class RuleIssue:
    index: int
    question_id: str
    code: str
    field: str
    level: str
    message: str


@dataclass(frozen=True)
class SampleResult:
    index: int
    question_id: str
    subject_id: str
    concept_id: str
    difficulty: str
    status: str
    score: int
    risk_tags: list[str]
    issues: list[str]
    suggestions: list[str]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _clean_option_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _normalize_difficulty(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized in DIFFICULTY_CANON:
        return DIFFICULTY_CANON[normalized]
    normalized_low = normalized.lower()
    return DIFFICULTY_CANON.get(normalized_low, "")


def _load_items(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("题库文件必须是 JSON 数组")
    return [dict(item) if isinstance(item, dict) else {} for item in raw]


def _is_template_like(text: str) -> list[str]:
    raw = str(text or "")
    normalized = raw.lower()
    reasons: list[str] = []

    explicit_words = ["todo", "待补充", "模板", "模板题", "示例题", "占位"]
    if any(word in normalized for word in explicit_words):
        reasons.append("explicit_template_marker")

    # 只把疑似“占位符风格”文本作为高优先告警，不一概把公式字符判为异常
    for match in re.findall(r"\[[^\[\]\n]{1,80}\]", raw):
        inner = match.strip("[]")
        if inner and not re.fullmatch(r"[0-9,\-+*/=.<> ()]+", inner):
            reasons.append("placeholder_square_bracket")
            break

    for match in re.findall(r"\{[^{}\n]{1,80}\}", raw):
        inner = match.strip("{}")
        if inner and not re.fullmatch(r"[0-9,\-+*/=.<> ()]+", inner):
            reasons.append("placeholder_curly_bracket")
            break

    for match in re.findall(r"<[^<>\n]{1,80}>", raw):
        inner = match.strip("<>")
        if inner and not re.fullmatch(r"[0-9,\-+*/=.<> ()]+", inner):
            reasons.append("placeholder_angle")
            break

    return reasons


def _option_texts(item: dict[str, Any]) -> dict[str, str]:
    options = item.get("options")
    if isinstance(options, dict):
        return {str(key).strip().upper(): str(value or "").strip() for key, value in options.items()}
    if isinstance(options, list):
        converted: dict[str, str] = {}
        for option in options:
            if not isinstance(option, dict):
                continue
            key = str(option.get("key") or "").strip().upper()
            value = str(option.get("text") or "").strip()
            if key:
                converted[key] = value
        return converted
    return {}


def _token_hits(term_set: set[str], text: str) -> bool:
    normalized = _normalize_text(text)
    return any(token and token in normalized for token in term_set)


def _infer_subject_id(concept_id: str, concept_registry) -> str:
    if not concept_id:
        return "unknown"
    concept = concept_registry.get_concept(concept_id)
    if concept is not None:
        return concept.subject_id or "unknown"
    return concept_id.split(".")[0] or "unknown"


def _build_concept_terms(item: dict[str, Any], concept_registry) -> set[str]:
    concept_id = str(item.get("concept_id") or "").strip()
    concept = concept_registry.get_concept(concept_id)
    if concept is None:
        return {part for part in re.split(r"[\s\-_.]+", concept_id) if part}
    terms = {str(concept.concept_name).replace(" ", ""), str(concept.topic_name).replace(" ", "")}
    for alias in list(concept.aliases or []):
        terms.add(str(alias).replace(" ", ""))
    return {t for t in terms if t}


def run_rule_audit(items: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[RuleIssue] = []
    concept_counter: Counter[str] = Counter()
    diff_counter_by_concept: dict[str, Counter[str]] = defaultdict(Counter)
    stem_seen: dict[str, int] = {}
    id_seen: dict[str, int] = {}
    duplicate_stems: list[dict[str, Any]] = []
    duplicate_ids: list[dict[str, Any]] = []
    placeholder_warns: list[dict[str, Any]] = []
    valid_items: list[dict[str, Any]] = []

    total = len(items)

    for index, item in enumerate(items, start=1):
        has_issue = False
        question_id = str(item.get("question_id") or "").strip()
        stem = str(item.get("stem") or "").strip()
        explanation = str(item.get("explanation") or "").strip()
        concept_id = str(item.get("concept_id") or "").strip()
        raw_answer = str(item.get("answer") or "").strip().upper()
        answer = re.sub(r"\s+", "", raw_answer)
        options = _option_texts(item)
        difficulty = _normalize_difficulty(item.get("difficulty"))

        if not question_id:
            issues.append(RuleIssue(index, question_id, "question_id", "question_id", "error", "question_id 不能为空"))
            has_issue = True
        elif question_id in id_seen:
            duplicate_ids.append({"index": index, "question_id": question_id, "first_seen": id_seen[question_id]})
            issues.append(RuleIssue(index, question_id, "question_id", "question_id", "warning", "question_id 重复"))
            has_issue = True
        else:
            id_seen[question_id] = index

        if not stem:
            issues.append(RuleIssue(index, question_id, "stem", "stem", "error", "stem 不能为空"))
            has_issue = True
        elif len(stem) < 8:
            issues.append(RuleIssue(index, question_id, "stem", "stem", "warning", "题干过短，可能导致歧义"))
            has_issue = True

        if stem:
            normalized_stem = _normalize_text(stem)
            if normalized_stem:
                if normalized_stem in stem_seen:
                    duplicate_stems.append({"index": index, "question_id": question_id or "<empty>", "first_seen": stem_seen[normalized_stem]})
                    issues.append(RuleIssue(index, question_id, "stem", "stem", "warning", "stem 重复"))
                    has_issue = True
                else:
                    stem_seen[normalized_stem] = index

        if not explanation:
            issues.append(RuleIssue(index, question_id, "explanation", "explanation", "error", "explanation 不能为空"))
            has_issue = True

        if not concept_id:
            issues.append(RuleIssue(index, question_id, "concept_id", "concept_id", "error", "concept_id 不能为空"))
            has_issue = True

        if not difficulty:
            issues.append(RuleIssue(index, question_id, "difficulty", "difficulty", "error", "难度字段非法（需 basic/medium/hard 或 基础/变式/易错）"))
            has_issue = True
        else:
            concept_counter[concept_id or "<unknown>"] += 1
            diff_counter_by_concept[concept_id or "<unknown>"][difficulty] += 1

        if set(options.keys()) != VALID_OPTIONS:
            issues.append(RuleIssue(index, question_id, "options", "options", "error", "选项必须为 A/B/C/D"))
            has_issue = True

        if re.search(r"[,/，|]", raw_answer):
            issues.append(RuleIssue(index, question_id, "answer", "answer", "error", "answer 存在多个候选项，不满足单答案要求"))
            has_issue = True
        elif not answer or answer not in VALID_OPTIONS:
            issues.append(RuleIssue(index, question_id, "answer", "answer", "error", "answer 必须属于 A/B/C/D"))
            has_issue = True
        elif answer not in options:
            issues.append(RuleIssue(index, question_id, "answer", "answer", "error", "answer 不存在于选项"))
            has_issue = True

        for reason in _is_template_like(stem):
            issues.append(RuleIssue(index, question_id, reason, "placeholder", "warning", "stem 存在疑似占位符/模板化文本"))
            placeholder_warns.append({"index": index, "question_id": question_id or "<empty>", "field": "stem", "reason": reason})
            has_issue = True

        for reason in _is_template_like(explanation):
            issues.append(RuleIssue(index, question_id, reason, "placeholder", "warning", "explanation 存在疑似占位符/模板化文本"))
            placeholder_warns.append({"index": index, "question_id": question_id or "<empty>", "field": "explanation", "reason": reason})
            has_issue = True

        if not has_issue:
            valid_items.append(item)

    invalid_concepts = [
        {"concept_id": concept_id, "count": count}
        for concept_id, count in sorted(concept_counter.items())
        if count != 10 and concept_id != "<unknown>"
    ]

    invalid_diff = []
    for concept_id, counter in sorted(diff_counter_by_concept.items()):
        if concept_id == "<unknown>":
            continue
        if counter != Counter({"basic": 3, "medium": 5, "hard": 2}):
            invalid_diff.append({"concept_id": concept_id, "difficulty": dict(counter)})

    error_count = sum(1 for issue in issues if issue.level == "error")
    warning_count = sum(1 for issue in issues if issue.level == "warning")

    return {
        "summary": {
            "total_questions": total,
            "valid_questions": len(valid_items),
            "error_count": error_count,
            "warning_count": warning_count,
            "placeholder_warning_count": len(placeholder_warns),
            "duplicate_id_count": len(duplicate_ids),
            "duplicate_stem_count": len(duplicate_stems),
        },
        "concept_count": len(set(concept_counter) - {"<unknown>"}),
        "concept_distribution_ok": len(invalid_concepts) == 0,
        "difficulty_distribution_ok": len(invalid_diff) == 0,
        "invalid_concept_counts": invalid_concepts,
        "invalid_difficulty_counts": invalid_diff,
        "issue_samples": [
            {
                "index": issue.index,
                "question_id": issue.question_id or "<empty>",
                "code": issue.code,
                "field": issue.field,
                "level": issue.level,
                "message": issue.message,
            }
            for issue in issues[:200]
        ],
        "duplicate_ids": duplicate_ids[:200],
        "duplicate_stems": duplicate_stems[:200],
        "placeholder_warnings": placeholder_warns[:200],
        "concept_counts": {k: v for k, v in sorted(concept_counter.items())},
        "difficulty_by_concept": {k: dict(v) for k, v in sorted(diff_counter_by_concept.items())},
    }


def _stratified_sample(
    items: list[dict[str, Any]], target: int, seed: int, concept_registry
) -> list[tuple[int, dict[str, Any]]]:
    if target <= 0:
        return []
    if target >= len(items):
        return list(enumerate(items, start=1))

    strata: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, item in enumerate(items, start=1):
        concept_id = str(item.get("concept_id") or "<unknown>").strip()
        subject_id = _infer_subject_id(concept_id, concept_registry)
        difficulty = _normalize_difficulty(item.get("difficulty")) or "unknown"
        strata[(subject_id, concept_id, difficulty)].append((index, item))

    total = len(items)
    quotas: dict[tuple[str, str, str], int] = {}
    remainders: list[tuple[float, tuple[str, str, str]]] = []

    fixed_total = 0
    for key, members in strata.items():
        exact = target * len(members) / total
        floor_n = int(exact)
        quotas[key] = min(floor_n, len(members))
        fixed_total += quotas[key]
        remainders.append((exact - floor_n, key))

    remaining = target - fixed_total
    remainders.sort(reverse=True)

    # 补齐到目标抽样量
    remainders.sort(reverse=True, key=lambda entry: entry[0])
    rng = random.Random(seed)
    cursor = 0
    while remaining > 0:
        if cursor >= len(remainders):
            fillable = [key for key in strata if quotas[key] < len(strata[key])]
            if not fillable:
                break
            rng.shuffle(fillable)
            for key in fillable:
                if remaining <= 0:
                    break
                quotas[key] += 1
                remaining -= 1
            break

        _, key = remainders[cursor]
        if quotas[key] < len(strata[key]):
            quotas[key] += 1
            remaining -= 1
        cursor += 1
    sampled: list[dict[str, Any]] = []
    for key, members in sorted(strata.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
        quota = quotas.get(key, 0)
        if quota <= 0:
            continue
        chosen = rng.sample(members, k=quota)
        sampled.extend(chosen)

    # 避免可能超抽：按需要修剪为 target
    if len(sampled) > target:
        sampled = rng.sample(sampled, k=target)

    return sampled


def _similarity_ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def _assess_question(index: int, item: dict[str, Any], concept_registry) -> SampleResult:
    question_id = str(item.get("question_id") or f"idx_{index}").strip()
    concept_id = str(item.get("concept_id") or "<unknown>").strip()
    difficulty = _normalize_difficulty(item.get("difficulty")) or "unknown"
    subject_id = _infer_subject_id(concept_id, concept_registry)

    stem = str(item.get("stem") or "").strip()
    explanation = str(item.get("explanation") or "").strip()
    answer_raw = str(item.get("answer") or "").strip().upper()
    answer = re.sub(r"\s+", "", answer_raw)
    options = _option_texts(item)

    issues: list[str] = []
    suggestions: list[str] = []
    risk_tags: set[str] = set()
    score = 100

    if not stem:
        issues.append("题干缺失")
        risk_tags.add("missing_stem")
        score -= 100

    if not explanation:
        issues.append("解析缺失")
        risk_tags.add("missing_explanation")
        score -= 100

    if not options:
        issues.append("选项结构不合法")
        risk_tags.add("invalid_options")
        score -= 100
    else:
        if set(options.keys()) != VALID_OPTIONS:
            issues.append("选项缺失或键名不为 A/B/C/D")
            risk_tags.add("invalid_options")
            score -= 60

        option_text_list = [options.get(k, "") for k in ["A", "B", "C", "D"] if k in options]
        normalized = [_clean_option_text(text) for text in option_text_list]
        if len({text for text in normalized}) != len(normalized):
            issues.append("存在重复或几乎重复的选项")
            risk_tags.add("duplicate_option_text")
            score -= 45

        short_options = [k for k, text in options.items() if len(str(text).strip()) < 4]
        if short_options:
            issues.append(f"部分选项过短（{','.join(sorted(short_options))}）")
            risk_tags.add("option_text_too_short")
            score -= 20

        for key, text in options.items():
            if not str(text or "").strip():
                issues.append(f"{key} 选项为空")
                risk_tags.add("empty_option")
                score -= 30

    if answer and answer in options:
        answer_text = _clean_option_text(options.get(answer, ""))
        normalized_stem = _clean_option_text(stem)
        if answer_text and answer_text not in normalized_stem and answer_text not in _clean_option_text(explanation):
            issues.append("解析未围绕正确选项展开")
            risk_tags.add("weak_rationale_alignment")
            score -= 20

        if any(_clean_option_text(value) in {"以上都是", "以上都对", "以上都不对", "无法判断", "都可以", "不正确", "对"} for value in options.values()):
            issues.append("存在过于模板化或无区分度选项")
            risk_tags.add("weak_distractors")
            score -= 25

        for i, k1 in enumerate("ABCD"):
            for k2 in "ABCD"[i + 1 :]:
                if k1 not in options or k2 not in options:
                    continue
                a = options[k1]
                b = options[k2]
                ratio = _similarity_ratio(_clean_option_text(a), _clean_option_text(b))
                if ratio >= 0.88:
                    issues.append(f"选项 {k1} 与 {k2} 高度相似（疑似干扰项质量不足）")
                    risk_tags.add("weak_distractors")
                    score -= 18

    if len(stem) < 12:
        issues.append("题干长度较短，容易歧义")
        risk_tags.add("stem_too_short")
        score -= 15

    ambiguity_markers = [
        "可能",
        "大致",
        "一般",
        "通常",
        "也许",
        "有时",
        "或者",
        "及其",
    ]
    normalized_stem = _normalize_text(stem)
    if any(marker in normalized_stem for marker in ambiguity_markers):
        issues.append("题干表述偏泛化，存在一定歧义" )
        risk_tags.add("ambiguity")
        score -= 18

    # 409 风格一致性：题面与知识点关键词应可对齐
    concept_terms = _build_concept_terms(item, concept_registry)
    combined = f"{stem} {explanation}"
    if concept_terms and not _token_hits(concept_terms, combined):
        issues.append("题干解析未明显体现目标知识点关键词")
        risk_tags.add("topic_mismatch")
        score -= 25

    # 题解闭环性：解析需具备推理链
    explain_markers = [
        "因为",
        "由于",
        "可得",
        "所以",
        "则",
        "因而",
        "根据",
        "说明",
        "例如",
        "故",
    ]
    if explanation and not any(marker in explanation for marker in explain_markers):
        issues.append("解析缺少推理链词" )
        risk_tags.add("weak_explanation")
        score -= 12
        suggestions.append("补齐闭环推理：条件 -> 计算/变形 -> 结论")

    if len(explanation) < 18:
        issues.append("解析文本过短")
        risk_tags.add("short_explanation")
        score -= 12
        suggestions.append("补齐解析文本长度，给出关键公式或步骤")

    combined_text = f"{stem} {explanation}"
    if any(marker in combined_text for marker in ["____", "_____", "……", "___", "□", "[]", "{}", "<>"]):
        issues.append("公式/表达存在不完整或占位片段")
        risk_tags.add("formula_incomplete")
        score -= 20
        suggestions.append("补齐公式缺失部分，避免留空位点")

    for reason in _is_template_like(f"{stem} {explanation}"):
        issues.append("存在疑似占位符/模板化文本")
        risk_tags.add("placeholder")
        score -= 12
        break

    if not answer:
        issues.append("答案缺失")
        risk_tags.add("invalid_answer")
        score -= 100
    elif re.search(r"[,/，|]", answer_raw):
        issues.append("答案包含多个候选项，不满足单答案要求")
        risk_tags.add("invalid_answer")
        score -= 100
    elif answer not in VALID_OPTIONS:
        issues.append("答案键非标准单选项（A/B/C/D）")
        risk_tags.add("invalid_answer")
        score -= 100

    if answer and answer in options:
        if options.get(answer, "") == options.get("A", "") and options.get("A", "") == options.get("B", "") == options.get("C", "") == options.get("D", ""):
            issues.append("所有选项内容极端重复，无法区分")
            risk_tags.add("weak_distractors")
            score -= 40

    if score <= 0:
        score = 0

    if any(tag in {"invalid_options", "invalid_answer", "missing_stem", "missing_explanation"} for tag in risk_tags):
        status = "不建议保留"
    elif score >= 75:
        status = "通过"
    elif score >= 56:
        status = "警告"
    else:
        status = "不建议保留"

    if status == "警告" and "weak_distractors" in risk_tags and score < 66:
        suggestions.append("建议补充干扰项细节，增加区分点")
    if "topic_mismatch" in risk_tags:
        suggestions.append("建议检查知识点归属与 stem/解析关键词，避免偏离目标概念")
    if "short_explanation" in risk_tags or "weak_explanation" in risk_tags:
        suggestions.append("建议补充完整推导链（条件->过程->结论），避免直接给答案")
    if "placeholder" in risk_tags:
        suggestions.append("替换疑似占位符文本，改为具体且唯一的表达")

    return SampleResult(
        index=index,
        question_id=question_id,
        subject_id=subject_id,
        concept_id=concept_id,
        difficulty=difficulty,
        status=status,
        score=max(0, min(100, int(round(score)))),
        risk_tags=sorted(risk_tags),
        issues=issues,
        suggestions=sorted(set(suggestions)),
    )


def _build_sample_report(sample_items: list[tuple[int, dict[str, Any]]], concept_registry) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results: list[SampleResult] = []
    status_counter: Counter[str] = Counter()
    risk_counter: Counter[str] = Counter()
    by_subject: dict[str, Counter[str]] = defaultdict(Counter)
    by_difficulty: dict[str, Counter[str]] = defaultdict(Counter)

    for index, item in sample_items:
        assessment = _assess_question(index, item, concept_registry)
        results.append(assessment)
        status_counter[assessment.status] += 1
        by_subject[assessment.subject_id][assessment.status] += 1
        by_difficulty[assessment.difficulty][assessment.status] += 1
        for tag in assessment.risk_tags:
            risk_counter[tag] += 1

    total = len(results)
    status_rate = {
        key: {
            "count": value,
            "rate": round(value / total, 4) if total else 0.0,
        }
        for key, value in status_counter.items()
    }
    topic_distribution = {
        status: {
            "passed": cnt.get("通过", 0),
            "warned": cnt.get("警告", 0),
            "rejected": cnt.get("不建议保留", 0),
        }
        for status, cnt in by_subject.items()
    }
    difficulty_distribution = {
        diff: {
            "passed": cnt.get("通过", 0),
            "warned": cnt.get("警告", 0),
            "rejected": cnt.get("不建议保留", 0),
        }
        for diff, cnt in by_difficulty.items()
    }

    top_risk = sorted(
        (
            (
                len(item.issues) * 3 + len(item.risk_tags) * 2 + (100 - item.score),
                item,
            )
            for item in results
        ),
        key=lambda entry: entry[0],
        reverse=True,
    )[:20]

    top_risk_questions = [
        {
            "index": item.index,
            "question_id": item.question_id,
            "subject_id": item.subject_id,
            "concept_id": item.concept_id,
            "difficulty": item.difficulty,
            "status": item.status,
            "score": item.score,
            "risk_tags": item.risk_tags,
            "issues": item.issues,
            "suggestions": item.suggestions,
            "risk_score": risk_score,
        }
        for risk_score, item in top_risk
    ]

    sample_rows = [
        {
            "index": item.index,
            "question_id": item.question_id,
            "subject_id": item.subject_id,
            "concept_id": item.concept_id,
            "difficulty": item.difficulty,
            "status": item.status,
            "score": item.score,
            "risk_tags": item.risk_tags,
            "issues": item.issues,
            "suggestions": item.suggestions,
        }
        for item in results
    ]

    summary_payload = {
        "total": total,
        "pass_count": status_counter.get("通过", 0),
        "warn_count": status_counter.get("警告", 0),
        "reject_count": status_counter.get("不建议保留", 0),
        "pass_rate": round(status_counter.get("通过", 0) / total, 4) if total else 0.0,
        "warn_rate": round(status_counter.get("警告", 0) / total, 4) if total else 0.0,
        "reject_rate": round(status_counter.get("不建议保留", 0) / total, 4) if total else 0.0,
        "status_breakdown": status_rate,
        "top_risk_tags": risk_counter.most_common(),
        "by_subject": topic_distribution,
        "by_difficulty": difficulty_distribution,
        "top_risk_questions": top_risk_questions,
    }

    return sample_rows, summary_payload


def run_audit(path: Path, *, sample_ratio: float, sample_size: int | None, seed: int) -> dict[str, Any]:
    items = _load_items(path)
    concept_registry = get_concept_registry()

    rule_report = run_rule_audit(items)

    target = sample_size
    if target is None:
        target = int(round(len(items) * sample_ratio))
    target = max(0, min(len(items), target))

    sampled_with_index = _stratified_sample(items, target=target, seed=seed, concept_registry=concept_registry)
    sample_details, sample_summary = _build_sample_report(sampled_with_index, concept_registry)

    by_subject_diffs: dict[str, float] = {}
    for subject_id, counts in sample_summary["by_subject"].items():
        total = counts.get("passed", 0) + counts.get("warned", 0) + counts.get("rejected", 0)
        by_subject_diffs[subject_id] = round(counts.get("passed", 0) / total, 4) if total else 0.0

    by_difficulty_diffs: dict[str, float] = {}
    for difficulty, counts in sample_summary["by_difficulty"].items():
        total = counts.get("passed", 0) + counts.get("warned", 0) + counts.get("rejected", 0)
        by_difficulty_diffs[difficulty] = round(counts.get("passed", 0) / total, 4) if total else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_path": str(path),
        "seed": seed,
        "sample_ratio": sample_ratio,
        "sample_size_target": target,
        "sample_size_actual": len(sample_details),
        "rule_audit": rule_report,
        "sample_summary": {
            **sample_summary,
            "passed_rate_by_subject": by_subject_diffs,
            "pass_rate_by_difficulty": by_difficulty_diffs,
        },
        "sample_results": sample_details,
        "top_20_risk_questions": sorted(
            sample_details,
            key=lambda item: (
                -len(item.get("issues", [])),
                -len(item.get("risk_tags", [])),
                item["score"],
                item["question_id"],
            ),
        )[:20],
    }


def print_markdown(report: dict[str, Any]) -> None:
    rule = report["rule_audit"]
    sample = report["sample_summary"]
    print("# 408 题库抽检报告")
    print(f"- 生成时间: {report['generated_at']}")
    print(f"- 题库文件: {report['input_path']}")
    print(f"- 题目总数: {rule['summary']['total_questions']}")
    print(f"- 规则复检: error={rule['summary']['error_count']}, warning={rule['summary']['warning_count']}")
    print(f"- 分层抽检: 目标={report['sample_size_target']}，实际={report['sample_size_actual']}")

    print("\n## 全量规则复检")
    print(f"- 重复 question_id: {rule['summary']['duplicate_id_count']}")
    print(f"- 重复 stem: {rule['summary']['duplicate_stem_count']}")
    print(f"- 疑似占位/模板文本告警: {rule['summary']['placeholder_warning_count']}")
    print(f"- concept 数量是否满足10题规则: {'通过' if rule['concept_distribution_ok'] else '未通过'}")
    print(f"- 难度比例是否符合3/5/2: {'通过' if rule['difficulty_distribution_ok'] else '未通过'}")

    if rule['invalid_concept_counts']:
        print("\n### 异常概念计数")
        for item in rule['invalid_concept_counts']:
            print(f"- {item['concept_id']}: {item['count']} 道")

    if rule['invalid_difficulty_counts']:
        print("\n### 异常难度分布")
        for item in rule['invalid_difficulty_counts']:
            print(f"- {item['concept_id']}: {item['difficulty']}")

    print("\n## 抽检聚合结果（按题目）")
    print(f"- 可通过: {sample['pass_count']}（{sample['pass_rate']:.2%}）")
    print(f"- 警告: {sample['warn_count']}（{sample['warn_rate']:.2%}）")
    print(f"- 不建议保留: {sample['reject_count']}（{sample['reject_rate']:.2%}）")
    print(f"- 可通过率: {sample['pass_rate']:.2%} | 待复核率: {sample['warn_rate']:.2%} | 淘汰率: {sample['reject_rate']:.2%}")

    print("\n## 按学科通过率")
    by_subject = sample.get("passed_rate_by_subject", {})
    for subject_id, pass_rate in sorted(by_subject.items()):
        print(f"- {subject_id}: {pass_rate:.2%}")

    print("\n## 按难度通过率")
    by_difficulty = sample.get("pass_rate_by_difficulty", {})
    for difficulty, pass_rate in sorted(by_difficulty.items()):
        print(f"- {difficulty}: {pass_rate:.2%}")

    print("\n## 风险类型分布（Top20）")
    risk_name_map = {
        "ambiguity": "歧义",
        "duplicate_option_text": "干扰项过弱",
        "weak_distractors": "干扰项过弱",
        "weak_explanation": "解析偏口语/跳步",
        "placeholder": "题干或解析疑似占位",
        "topic_mismatch": "知识点偏离",
        "formula_incomplete": "公式不完整",
        "missing_stem": "歧义",
        "missing_explanation": "解析缺失",
        "invalid_options": "选项异常",
        "invalid_answer": "答案异常",
        "short_explanation": "解析偏口语/跳步",
        "option_text_too_short": "干扰项过弱",
        "empty_option": "选项异常",
        "weak_rationale_alignment": "解析偏口语/跳步",
        "topic_mismatch": "知识点偏离",
    }

    aggregated_risks = sample.get("top_risk_tags", [])
    for rank, (raw_tag, count) in enumerate(aggregated_risks[:20], start=1):
        print(f"- {rank:02d}. {risk_name_map.get(raw_tag, raw_tag)}: {count}")

    print("\n## 风险题目 Top 20（含问题点与整改建议）")
    for rank, item in enumerate(report["top_20_risk_questions"], start=1):
        print(f"{rank:02d}. {item['question_id']}（{item['status']}，score={item['score']}）")
        for issue in item["issues"]:
            print(f"- 问题点: {issue}")
        for suggest in item.get("suggestions", []):
            print(f"- 建议: {suggest}")
        print(f"- 学科/知识点: {item['subject_id']} / {item['concept_id']}")

    print("\n## 可直接修订清单（已按优先级）")
    risk_sorted = sorted(
        report["sample_results"],
        key=lambda item: (
            {"不建议保留": 0, "警告": 1, "通过": 2}.get(item["status"], 3),
            item["score"],
            item["question_id"],
        ),
    )
    action_map: dict[str, int] = {"不建议保留": 1, "警告": 2, "通过": 3}
    for item in risk_sorted[:20]:
        severity = action_map.get(item["status"], 3)
        priority = "P1" if severity == 1 else ("P2" if severity == 2 else "P3")
        print(f"- {item['question_id']} [{priority}] {item['status']}：{', '.join(item['issues'][:2])}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="408 题库质量抽检")
    parser.add_argument(
        "--path",
        required=True,
        help="显式提供具有合法使用权限的题库 JSON 文件路径",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="抽检题目数（默认按 sample-ratio 计算）",
    )
    parser.add_argument(
        "--sample-ratio",
        type=float,
        default=0.12,
        help="默认抽检比例，默认 12%",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=2026,
        help="抽样随机种子，默认 2026",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="仅输出 JSON 报告（便于接入 CI）",
    )
    parser.add_argument(
        "--json-output",
        default="",
        help="将完整报告写入 JSON 文件路径（可选）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    path = Path(args.path)
    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.exists():
        print(f"题库文件不存在: {path}", file=sys.stderr)
        return 1
    if args.sample_size is not None and args.sample_size <= 0:
        print("--sample-size 必须为正整数", file=sys.stderr)
        return 1

    report = run_audit(
        path,
        sample_ratio=max(0.0, min(1.0, args.sample_ratio)),
        sample_size=args.sample_size,
        seed=args.seed,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print_markdown(report)

    if args.json_output.strip():
        output_path = Path(args.json_output)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 报告已写入: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
