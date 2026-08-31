import logging
from typing import Any

logger = logging.getLogger(__name__)


def normalize_confidence(raw_conf: Any) -> float:
    """
    Safely normalizes confidence values whether stored as 0-100 or 0.0-1.0.
    Guarantees a clean 0.0 - 1.0 multiplier without crushing valid scores.
    """
    if raw_conf is None:
        return 1.0
    try:
        val = float(raw_conf)
        if val > 1.0:
            return min(1.0, max(0.0, val / 100.0))
        return min(1.0, max(0.0, val))
    except (ValueError, TypeError):
        return 1.0


class BuyingSignalScorer:
    """
    Computes buying signal score (0 - 100) and produces explainable attribution logs:
    1. Confirmed Past Spend (Directory Reviewer / Client): Highest intent (Verified past budget)
    2. Active Hiring Intent: Scaled by normalized source confidence
    3. Specific Tech Alignment (Laravel, Next.js, Shopify, React): Capped skill bonus
    4. ATS Infrastructure (Greenhouse, Lever, etc.)
    5. Company Scale & Funding Signals
    """

    RELEVANT_SKILL_WEIGHTS = {
        "laravel": 30.0,
        "next.js": 30.0,
        "react": 25.0,
        "shopify": 25.0,
        "woocommerce": 20.0,
        "wordpress": 15.0,
        "fullstack": 20.0,
        "devops": 15.0,
    }

    PAST_SPEND_TYPES = {
        "client_past_spend_verified",
        "directory_client_review",
        "past_spend_verified",
        "verified_agency_client",
    }

    SIGNAL_TYPE_WEIGHTS = {
        "client_past_spend_verified": 45.0,
        "directory_client_review": 40.0,
        "active_hiring_intent": 25.0,
        "hiring_ats_detected": 15.0,
        "career_page_detected": 10.0,
        "funding_growth": 20.0,
    }

    def score_with_breakdown(self, signals: list[dict[str, Any]]) -> tuple[float, list[dict[str, Any]]]:
        if not signals:
            return 20.0, [{"reason": "baseline_no_signals", "points": 20.0, "confidence": 1.0}]

        score = 25.0
        breakdown = [{"reason": "baseline_signals_present", "points": 25.0, "confidence": 1.0}]
        total_skill_points = 0.0
        skill_reasons = []

        for sig in signals:
            sig_type = sig.get("type", "")
            raw_conf = sig.get("confidence", sig.get("confidence_score", 1.0))
            confidence = normalize_confidence(raw_conf)
            # Fix None-fallthrough bug:
            detail = sig.get("detail") or sig.get("evidence_data") or {}

            # 1. Past Spend Confirmation (Exact match whitelist)
            if sig_type in self.PAST_SPEND_TYPES:
                base = self.SIGNAL_TYPE_WEIGHTS.get(sig_type, 45.0)
                pts = base * max(0.6, confidence)
                score += pts
                breakdown.append({"reason": f"past_spend_{sig_type}", "points": round(pts, 2), "confidence": confidence})
                logger.debug(f"Matched past spend '{sig_type}' → +{pts:.1f} pts (conf={confidence})")

            # 2. Active Hiring Intent
            elif sig_type == "active_hiring_intent":
                base = self.SIGNAL_TYPE_WEIGHTS.get("active_hiring_intent", 25.0)
                pts = base * confidence
                score += pts
                breakdown.append({"reason": "active_hiring_intent", "points": round(pts, 2), "confidence": confidence})
                logger.debug(f"Matched active hiring intent → +{pts:.1f} pts (conf={confidence})")

            # 3. Matching Skill Roles (Capped at 40.0 points max across all skills)
            elif sig_type == "hiring_skill_match":
                matched = detail.get("matched_skills", []) if isinstance(detail, dict) else []
                for m in matched:
                    if isinstance(m, dict):
                        skill = m.get("skill", "").lower()
                        weight = self.RELEVANT_SKILL_WEIGHTS.get(skill, 15.0)
                        pts = weight * confidence
                        total_skill_points += pts
                        skill_reasons.append(f"{skill} (+{pts:.1f})")

            # 4. ATS Infrastructure
            elif sig_type == "hiring_ats_detected":
                pts = self.SIGNAL_TYPE_WEIGHTS.get("hiring_ats_detected", 15.0) * confidence
                score += pts
                breakdown.append({"reason": "ats_detected", "points": round(pts, 2), "confidence": confidence})
                logger.debug(f"Matched ATS infrastructure → +{pts:.1f} pts")

            # 5. Career Page Presence
            elif sig_type == "career_page_detected":
                pts = self.SIGNAL_TYPE_WEIGHTS.get("career_page_detected", 10.0) * confidence
                score += pts
                breakdown.append({"reason": "career_page", "points": round(pts, 2), "confidence": confidence})
                logger.debug(f"Matched career page → +{pts:.1f} pts")

            # 6. Growth & Scale Signals (Exact matches)
            elif sig_type in {"funding_round", "company_growth_award", "client_scale_expansion"}:
                pts = self.SIGNAL_TYPE_WEIGHTS.get("funding_growth", 20.0) * confidence
                score += pts
                breakdown.append({"reason": f"growth_{sig_type}", "points": round(pts, 2), "confidence": confidence})
                logger.debug(f"Matched growth signal '{sig_type}' → +{pts:.1f} pts")

        # Apply capped skill bonus
        capped_skill_pts = min(40.0, total_skill_points)
        if capped_skill_pts > 0:
            score += capped_skill_pts
            breakdown.append({
                "reason": "hiring_skills_capped",
                "points": round(capped_skill_pts, 2),
                "skills": skill_reasons,
            })
            logger.debug(f"Applied capped skill points: +{capped_skill_pts:.1f} (raw={total_skill_points:.1f})")

        final_score = min(100.0, max(0.0, round(score, 2)))
        return final_score, breakdown

    def score(self, signals: list[dict[str, Any]]) -> float:
        score_val, _ = self.score_with_breakdown(signals)
        return score_val


def get_buying_scorer() -> BuyingSignalScorer:
    return BuyingSignalScorer()
