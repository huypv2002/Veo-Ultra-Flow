"""
Subscription plan policies & limits for Veo3 tool.

This module centralizes every rule so that backend validation (Supabase manager)
and frontend (Qt6 UI) can stay in sync.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

DEFAULT_PLAN_KEY = "free"

SUBSCRIPTION_RULES: Dict[str, Dict[str, Any]] = {
    "free": {
        "display_name": "Free",
        "badge_color": "#F44336",
        "max_cookies": 1,
        "max_concurrent_720": 5,
        "max_concurrent_1080": 3,
        "videos_per_minute_720": 1000,
        "videos_per_minute_1080": 1000,
        "extend_prompts_per_project": 5,
        "extend_max_duration_seconds": 40,  # ~30s video per project
        "reference_images_per_prompt": None,
        "is_full_feature": False,
        "notes": "Free tier: 5 luồng 720P, 3 luồng 1080P, 5 prompt/project (40s).",
    },
    # Basic is used when Ultra expires automatically.
    "basic": {
        "display_name": "Basic",
        "badge_color": "#FF7043",
        "max_cookies": 1,
        "max_concurrent_720": 5,
        "max_concurrent_1080": 3,
        "videos_per_minute_720": 3,
        "videos_per_minute_1080": 2,
        "extend_prompts_per_project": 4,
        "extend_max_duration_seconds": 30,
        "reference_images_per_prompt": 1,
        "is_full_feature": False,
        "notes": "Basic tier mirrors Free limits; used for auto-downgrade handling.",
    },
    "premium": {
        "display_name": "Premium",
        "badge_color": "#FF9800",
        "max_cookies": 5,
        "max_concurrent_720": 15,
        "max_concurrent_1080": 9,
        "videos_per_minute_720": None,
        "videos_per_minute_1080": None,
        "extend_prompts_per_project": 60,  # full access
        "extend_max_duration_seconds": 480,  # up to 6 minutes
        "reference_images_per_prompt": None,
        "is_full_feature": True,
        "notes": "Premium: full features, capped at 3 cookies / 15 luồng.",
    },
    "ultra": {
        "display_name": "Ultra",
        "badge_color": "#4CAF50",
        "max_cookies": None,  # unlimited
        "max_concurrent_720": None,
        "max_concurrent_1080": None,
        "videos_per_minute_720": None,
        "videos_per_minute_1080": None,
        "extend_prompts_per_project": None,
        "extend_max_duration_seconds": None,
        "reference_images_per_prompt": None,
        "is_full_feature": True,
        "downgrade_to": "basic",
        "notes": "Ultra: unlimited multi-thread, 1000 video/min.",
    },
    "enterprise": {
        "display_name": "Enterprise",
        "badge_color": "#3F51B5",
        "max_cookies": None,
        "max_concurrent_720": None,
        "max_concurrent_1080": None,
        "videos_per_minute_720": None,
        "videos_per_minute_1080": None,
        "extend_prompts_per_project": None,
        "extend_max_duration_seconds": None,
        "reference_images_per_prompt": None,
        "is_full_feature": True,
        "notes": "Enterprise: full unlimited usage without extra fees.",
    },
}


def normalize_subscription_type(value: Optional[str]) -> str:
    """Normalize plan string (None -> free)."""
    if not value:
        return DEFAULT_PLAN_KEY
    value = str(value).strip().lower()
    if value in SUBSCRIPTION_RULES:
        return value
    # Accept some aliases
    aliases = {
        "trial": "free",
        "lifetime": "premium",
        "vip": "premium",
    }
    return aliases.get(value, DEFAULT_PLAN_KEY)


def get_subscription_limits(subscription_type: Optional[str]) -> Dict[str, Any]:
    """Return a copy of the rules for the specified subscription."""
    plan_key = normalize_subscription_type(subscription_type)
    limits = SUBSCRIPTION_RULES.get(plan_key, SUBSCRIPTION_RULES[DEFAULT_PLAN_KEY])
    result = deepcopy(limits)
    result["plan_key"] = plan_key
    return result


def is_full_feature_plan(plan_key: str) -> bool:
    return SUBSCRIPTION_RULES.get(plan_key, SUBSCRIPTION_RULES[DEFAULT_PLAN_KEY]).get(
        "is_full_feature", False
    )


