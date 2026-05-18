import json
import re
import difflib
from collections import defaultdict

def normalize_text(text):
    if not isinstance(text, str):
        return ""
    # remove spaces and punctuation
    return re.sub(r'\W+', '', text.lower())

def is_pure_number_or_symbol(text):
    # true if no chinese characters and no english letters
    return not bool(re.search(r'[a-zA-Z\u4e00-\u9fa5]', text))

def calc_sim(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()

def process_questions(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    summary = {
        "total_questions": len(data),
        "kept_count": 0,
        "review_count": 0,
        "drop_count": 0,
        "kept_rate": 0.0,
        "drop_rate": 0.0
    }

    kept_questions = []
    discarded_questions = []
    review_questions = []
    
    subject_pass = defaultdict(lambda: {"total": 0, "kept": 0})
    difficulty_pass = defaultdict(lambda: {"total": 0, "kept": 0})
    risk_tag_counts = defaultdict(int)

    seen_ids = set()
    seen_stems = set()

    diff_map = {
        "basic": "basic", "基础": "basic", "简单": "basic", "简单题": "basic",
        "medium": "medium", "中等": "medium", "变式": "medium",
        "hard": "hard", "困难": "hard", "难": "hard", "易错": "hard"
    }

    for item in data:
        score = 100
        hard_violations = []
        risk_tags = []
        issues = []
        fix_suggestions = []

        q_id = item.get("question_id", "")
        stem = item.get("stem", "")
        exp = item.get("explanation", "")
        cid = item.get("concept_id", "")
        ans = item.get("answer", "")
        diff_raw = item.get("difficulty", "")
        opts = item.get("options", {})

        subject = cid.split('.')[0] if cid else "unknown"

        # 1. Hard Rule: fields presence
        if not q_id or not stem or not exp or not cid or not ans:
            hard_violations.append("missing_field")
            issues.append("关键字段缺失或为空")
            fix_suggestions.append("补充完整的 question_id, stem, explanation, concept_id, answer")

        # 2. Options standard and Hard Rule
        standard_opts = {}
        if isinstance(opts, dict):
            standard_opts = {k.upper(): v for k, v in opts.items()}
        elif isinstance(opts, list):
            for o in opts:
                o_str = str(o).strip()
                if o_str:
                    key = o_str[0].upper()
                    if key in ['A','B','C','D']:
                        val = re.sub(r'^[A-D][.、\s]*', '', o_str)
                        standard_opts[key] = val

        valid_opt_keys = ['A', 'B', 'C', 'D']
        if len(standard_opts) != 4 or any(k not in valid_opt_keys for k in standard_opts) or any(not v for v in standard_opts.values()):
            hard_violations.append("invalid_options")
            issues.append("选项格式不合法（必须为A/B/C/D四个非空选项）")
            fix_suggestions.append("检查并规范化 options 字段")
        
        # 3. Answer valid
        ans = str(ans).strip().upper()
        if ans not in valid_opt_keys:
            hard_violations.append("invalid_answer")
            issues.append("答案格式不合法（必须是 A/B/C/D）")
            fix_suggestions.append("修改 answer 为单个大写字母 A/B/C/D")

        # 4. Difficulty valid
        diff = diff_map.get(diff_raw.lower() if isinstance(diff_raw, str) else diff_raw, None)
        if not diff:
            hard_violations.append("invalid_difficulty")
            issues.append(f"难度值不合法: {diff_raw}")
            fix_suggestions.append("难度必须为 basic/medium/hard 或对应中文")
            diff = "medium" # fallback for stats

        # 5. Duplicate ID
        if q_id in seen_ids:
            hard_violations.append("duplicate_id")
            issues.append(f"重复的 question_id: {q_id}")
            fix_suggestions.append("修改为唯一的 question_id 或移除重复项")
        else:
            if q_id: seen_ids.add(q_id)

        # 6. Duplicate Stem
        norm_stem = normalize_text(stem)
        if norm_stem in seen_stems and norm_stem:
            hard_violations.append("duplicate_stem")
            issues.append("题干内容与其他题目高度重复")
            fix_suggestions.append("重写题干或删除重复题")
        else:
            if norm_stem: seen_stems.add(norm_stem)

        # Quality Rules
        # Stem short
        if isinstance(stem, str) and len(stem.strip()) < 15:
            score -= 6
            risk_tags.append("short_stem")
            issues.append("题干过短(<15字)")
            fix_suggestions.append("丰富题干描述，提供充分的上下文")

        # Fuzzy words
        if isinstance(stem, str) and re.search(r'可能|大致|一般|通常|也许|或者', stem):
            score -= 8
            risk_tags.append("ambiguous_stem")
            issues.append("题干包含模糊词汇")
            fix_suggestions.append("删除“可能/大致/一般”等模糊词，使题意明确")

        # Options highly similar
        opts_vals = list(standard_opts.values())
        similar_pairs = 0
        for i in range(len(opts_vals)):
            for j in range(i+1, len(opts_vals)):
                if calc_sim(opts_vals[i], opts_vals[j]) >= 0.88:
                    similar_pairs += 1
        if similar_pairs > 0:
            score -= 25 * similar_pairs
            risk_tags.append("duplicate_option")
            issues.append("选项之间文本高度相似")
            fix_suggestions.append("增加选项之间的区分度")

        # Option empty -> handled in hard rule, but adding penalty if missing
        if any(not v for v in opts_vals):
            score -= 20

        # Option too short
        short_opts = 0
        for v in opts_vals:
            if len(v) < 4 and not is_pure_number_or_symbol(v):
                short_opts += 1
        if short_opts > 0:
            score -= 10 * short_opts
            risk_tags.append("option_too_short")
            issues.append("部分选项过短且不纯为数字符号")
            fix_suggestions.append("补充选项的解释性文字")

        # Templated expression
        if re.search(r'\{[a-zA-Z\u4e00-\u9fa5]+\}|\[[a-zA-Z\u4e00-\u9fa5]+\]|<[a-zA-Z\u4e00-\u9fa5]+>', stem + exp):
            score -= 18
            risk_tags.append("placeholder_like")
            issues.append("文本中包含模板化占位符")
            fix_suggestions.append("将模板化符号替换为实际内容")

        # Explanation missing keywords
        if isinstance(exp, str) and not re.search(r'因为|由于|可得|则|所以|故|根据|故可得', exp):
            score -= 15
            risk_tags.append("weak_explanation")
            issues.append("解析缺少推理链关键词")
            fix_suggestions.append("在解析中增加推理关联词如“因为”、“所以”、“可得”")

        # Explanation too short
        if isinstance(exp, str) and len(exp.strip()) < 18:
            score -= 10
            risk_tags.append("short_explanation")
            issues.append("解析文本过短(<18字)")
            fix_suggestions.append("提供更详细的解析内容")

        # Explanation not around answer
        ans_text = standard_opts.get(ans, "")
        if ans_text and isinstance(exp, str):
            # very basic check: does a large chunk of answer text appear in explanation, or is overlap sufficient
            # If answer is very short, just string matching.
            if len(ans_text) >= 2 and ans_text not in exp:
                # let's be more lenient, maybe check overlap
                if calc_sim(ans_text, exp) < 0.1 and not re.search(fr'{ans}项|{ans}选项|选{ans}', exp):
                    score -= 15
                    risk_tags.append("weak_rationale_alignment")
                    issues.append("解析未围绕标准答案展开")
                    fix_suggestions.append("在解析中明确指出答案的正确理由")

        # Concept keywords missing
        kp = item.get("knowledge_points", [])
        if not kp:
            kp = cid.replace('.', '-').split('-') if cid else []
        kp_matched = False
        combined_text = str(stem) + str(exp)
        for k in kp:
            if k and len(k) > 1 and k in combined_text:
                kp_matched = True
                break
        if not kp_matched and kp:
            score -= 12
            risk_tags.append("topic_mismatch")
            issues.append("未体现目标知识点关键词")
            fix_suggestions.append("在题干或解析中融入对应的知识点关键词")

        # Formula incomplete fragment
        if re.search(r'____|\[\s*\]|\{\s*\}|<\s*>', combined_text):
            score -= 20
            risk_tags.append("formula_incomplete")
            issues.append("包含未完成的填空或公式片段")
            fix_suggestions.append("修复残缺的文本符号")

        # Options all identical
        if len(set(opts_vals)) == 1 and len(opts_vals) == 4:
            score -= 60
            risk_tags.append("identical_options")
            issues.append("选项与答案可疑完全重复(ABCD相同)")
            fix_suggestions.append("提供各不相同的干扰项")

        # Decision
        if hard_violations or score < 70:
            decision = "DROP"
            for t in hard_violations + risk_tags:
                risk_tag_counts[t] += 1
            discarded_questions.append({
                "question_id": q_id,
                "decision": decision,
                "score": score,
                "issues": list(set(issues)),
                "risk_tags": list(set(hard_violations + risk_tags)),
                "fix_suggestions": list(set(fix_suggestions))
            })
            subject_pass[subject]["total"] += 1
            difficulty_pass[diff]["total"] += 1
            summary["drop_count"] += 1
        elif 70 <= score < 82:
            decision = "REVIEW"
            for t in risk_tags:
                risk_tag_counts[t] += 1
            review_questions.append({
                "question_id": q_id,
                "decision": decision,
                "score": score,
                "issues": list(set(issues)),
                "risk_tags": list(set(risk_tags)),
                "fix_suggestions": list(set(fix_suggestions))
            })
            subject_pass[subject]["total"] += 1
            difficulty_pass[diff]["total"] += 1
            summary["review_count"] += 1
        else:
            decision = "KEEP"
            kept_questions.append({
                "question_id": q_id,
                "subject_id": subject,
                "concept_id": cid,
                "difficulty": diff,
                "score": score,
                "reason_short": "无硬性违规且评分达到上线标准",
                "risk_tags": list(set(risk_tags))
            })
            subject_pass[subject]["total"] += 1
            subject_pass[subject]["kept"] += 1
            difficulty_pass[diff]["total"] += 1
            difficulty_pass[diff]["kept"] += 1
            summary["kept_count"] += 1

    summary["kept_rate"] = round(summary["kept_count"] / summary["total_questions"], 4) if summary["total_questions"] else 0
    summary["drop_rate"] = round(summary["drop_count"] / summary["total_questions"], 4) if summary["total_questions"] else 0

    subj_pass_rate = {s: round(d["kept"] / d["total"], 4) if d["total"] else 0 for s, d in subject_pass.items()}
    diff_pass_rate = {d: round(v["kept"] / v["total"], 4) if v["total"] else 0 for d, v in difficulty_pass.items()}
    top_tags = sorted(risk_tag_counts.items(), key=lambda x: x[1], reverse=True)
    
    all_risks = discarded_questions + review_questions
    all_risks.sort(key=lambda x: x["score"])
    top20_risk = all_risks[:20]

    aggregates = {
        "subject_pass_rate": subj_pass_rate,
        "difficulty_pass_rate": diff_pass_rate,
        "top_risk_tags": top_tags,
        "top20_risk_questions": [{"question_id": r["question_id"], "score": r["score"], "issues": r["issues"], "risk_tags": r["risk_tags"]} for r in top20_risk]
    }

    final_output = {
        "summary": summary,
        "kept_questions": kept_questions,
        "discarded_questions": discarded_questions,
        "review_questions": review_questions,
        "aggregates": aggregates,
        "kept_question_ids": [k["question_id"] for k in kept_questions]
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    print("Processing complete!")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    process_questions("data/practice_questions/all_408.json", "408_review_result.json")
