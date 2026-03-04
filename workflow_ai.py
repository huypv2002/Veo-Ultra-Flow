#!/usr/bin/env python3
"""
Workflow AI utilities: Gemini text generation for prompts.

Provides a small wrapper over Google Generative Language API (Gemini) to generate
rich prompts from user keywords. The output is a list of prompts.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

import requests
import math
from pathlib import Path
import re


class GeminiTextGenerator:
    """Simple client for Gemini text generation to produce prompts from keywords."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        # Default to the requested model: Gemini 2.5 Flash-Lite
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate_prompts(self, keywords: str, num: int = 4, context: str = "") -> List[str]:
        """Generate a list of prompts from keywords.

        keywords: free-form text from user
        num: desired number of prompts
        context: optional guidance (e.g., for video or image style)
        """
        if not self.is_configured():
            return []

        # Construct the prompt for Gemini
        system_hint = (
            "You are a senior prompt engineer for text-to-video (8s cinematic shots). "
            "Expand short user keywords into rich, production-ready generation prompts. "
            "Requirements for EACH item: one line only, numbered, no extra text before/after. "
            "Write in English ONLY. Do NOT use Vietnamese. Avoid code blocks. "
            "Include the following elements inline, separated by pipes `|` where natural: "
            "Subject & strong action verb; Setting/location, time of day, weather; Composition/framing "
            "(wide/medium/close-up, subject distance, rule of thirds/symmetry); Camera specs (lens mm, "
            "aperture, shallow DOF or deep focus, movement such as dolly-in/steadicam/drone/pan/tilt/handheld); "
            "Lighting scheme (key/fill/rim, temperature, contrast ratio, mood lighting); Color palette; Mood/emotion; "
            "Style anchor (e.g., 3D cinematic, Pixar-like if appropriate, hyper realistic, filmic grain); "
            "Physical detail (cloth/hair simulation, particles, motion blur); Quality suffix (4K, high detail). "
            "Add constraints: no text overlays, no watermarks, no logos, safe-for-work, no copyrighted names unless provided. "
            "Default aspect ratio 16:9 unless context overrides. If GEN_ID_* tokens appear in the keywords, reference them at the start."
        )
        user_prompt = (
            f"Keywords: {keywords}\n"
            f"Context: {context}\n"
            f"Please produce {num} distinct prompts. One line per item, numbered 1..{num}."
        )

        # Gemini REST API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": system_hint}]},
                {"role": "user", "parts": [{"text": user_prompt}]},
            ]
        }

        try:
            resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=60)
            resp.raise_for_status()
            data = resp.json()
            text = self._extract_text(data)
            return self._split_numbered_list(text, num)
        except Exception:
            return []

    # -------- Scenario generation for structured files --------
    def generate_scenario_pack(
        self,
        keywords: str,
        total_duration_seconds: int,
        shots_per_scene: int = 5,
        language: str = "en",
        global_style: Optional[str] = None,
    ) -> dict:
        """Create a structured scenario with scenes, shots (8s each), and characters.

        Returns a dict with keys: scenes (list), characters (list), environment (str or dict).
        Robust to API failures: falls back to a deterministic splitter.
        """
        if total_duration_seconds <= 0:
            total_duration_seconds = 8
        if shots_per_scene <= 0:
            shots_per_scene = 5

        # Compute counts
        total_shots = max(1, math.ceil(total_duration_seconds / 8))
        if total_shots == 10:
            # Encourage exactly 2 scenes x 5 shots for 80s
            num_scenes = 2
            shots_distribution = [5, 5]
        else:
            num_scenes = max(1, math.ceil(total_shots / shots_per_scene))
            # Distribute shots across scenes as evenly as possible
            base = total_shots // num_scenes
            remainder = total_shots % num_scenes
            shots_distribution = [base + (1 if i < remainder else 0) for i in range(num_scenes)]

        # Extract GEN_ID tokens if any (e.g., GEN_ID_TEACHER_01)
        forced_gen_ids = self._extract_gen_ids(keywords)

        # Ask Gemini for a structured JSON
        if self.is_configured():
            try:
                sys_hint = (
                    "You are a film storyboard writer and senior prompt engineer. Produce a STRICT JSON object with keys: "
                    "'characters' (array), 'environment' (object), and 'scenes' (array).\n"
                    "characters: [{ id, name (Name_ID in output files), details: { "
                    "appearance: { fur_or_hair_color, eye_color, height_cm, weight_kg, body_shape, skin_or_fur_texture, color_palette, hair_style }, "
                    "outfit_accessories: { items, locked_style }, distinctive_features, behavior_personality, "
                    "consistency: { palette_lock, outfit_lock, hair_lock, do_not_change:[], negative } } }]\n"
                    "environment: { name, description, location_type, time_of_day, weather, lighting_palette, props }\n"
                    "scenes: [{ scene_id:int, title, summary, shots:[ { duration_seconds:8, prompt, style, camera, transition, dialogue:null, "
                    "audio:{ bgm, sfx:[] }, timeline:{ '0-3':'', '3-5':'', '5-8':'' }, "
                    "lens_mm:int, aperture:string, dof:string, lighting:string, color_palette:string, movement:string, composition:string, mood:string, quality:string, negative:string } ] }]\n"
                    "Language must be English ONLY. Respond ONLY in English. No Vietnamese or other languages.\n"
                    "Shot writing checklist: Strong action verbs; explicit setting/time/weather; composition (wide/medium/close-up, rule of thirds/symmetry); camera with lens (e.g., 35mm), aperture (e.g., f/2.8), movement (dolly/pan/tilt/handheld/drone), DOF and focus plane; lighting (key/fill/rim, temperature, contrast); color palette; mood; style anchor (3D cinematic, Pixar-like if suitable); physical detail (cloth/hair/particles/motion blur); quality tag (4K, high detail); and a concise negative clause (no text overlays, no watermarks, no logos).\n"
                    "Character consistency constraints: If GEN_ID tokens are provided, define characters using those GEN_IDs and reference them by GEN_ID in EVERY shot prompt. "
                    "Keep age, outfit, accessories, palette, hair style, and style anchor CONSTANT across all scenes. Use at most two characters per shot. "
                    "Default aspect ratio is 16:9. If total shots == 10, distribute as 2 scenes x 5 shots. Do NOT include code fences or commentary—output JSON only."
                )
                structure_spec = {
                    "keywords": keywords,
                    "total_duration_seconds": total_duration_seconds,
                    "num_scenes": num_scenes,
                    "shots_per_scene_preference": shots_per_scene,
                    "shots_distribution": shots_distribution,
                    "shot_duration_seconds": 8,
                    "forced_gen_ids": forced_gen_ids,
                    "english_only": True,
                    "global_style": global_style,
                }
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
                headers = {"Content-Type": "application/json; charset=utf-8"}
                body = {
                    "contents": [
                        {"role": "user", "parts": [{"text": sys_hint}]},
                        {"role": "user", "parts": [{"text": (
                            "Create a scenario pack in STRICT JSON with the schema above. "
                            "Respond ONLY in English. Do not include any language other than English. "
                            "Hard requirements: (1) If 'forced_gen_ids' is not empty, define characters with these "
                            "GEN_IDs and reference them by GEN_ID in EVERY shot's prompt. (2) Keep character outfit, "
                            "accessories, and style consistent across all scenes. (3) Avoid adding extra unnamed "
                            "characters; use at most two characters per shot. (4) Ensure each shot duration is 8s. "
                            "(5) For every shot include a 'timeline' object with keys '0-3', '3-5', '5-8' describing exact on-screen actions.\n" 
                            + json.dumps(structure_spec, ensure_ascii=False)
                        )}]}
                    ]
                }
                resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=90)
                resp.raise_for_status()
                data = resp.json()
                text = self._extract_text(data)
                json_text = self._extract_json_block(text)
                pack = json.loads(json_text)
                pack = self._normalize_pack(pack, shots_distribution)
                # Enforce GEN_ID usage if provided
                if forced_gen_ids:
                    pack = self._enforce_gen_ids(pack, forced_gen_ids)
                # Ensure detailed timelines exist even if model omitted them
                pack = self._ensure_timelines(pack)
                # Enforce global style across all shots if provided
                if global_style:
                    try:
                        for sc in pack.get("scenes", []) or []:
                            for sh in sc.get("shots", []) or []:
                                sh["style"] = global_style
                    except Exception:
                        pass
                    try:
                        pack["_global_style"] = global_style
                    except Exception:
                        pass
                return pack
            except Exception:
                pass

        # Fallback: deterministic splitter
        pack = self._fallback_pack(keywords, shots_distribution)
        if forced_gen_ids:
            pack = self._enforce_gen_ids(pack, forced_gen_ids)
        pack = self._ensure_timelines(pack)
        # Enforce global style on fallback as well
        if global_style:
            try:
                for sc in pack.get("scenes", []) or []:
                    for sh in sc.get("shots", []) or []:
                        sh["style"] = global_style
                pack["_global_style"] = global_style
            except Exception:
                pass
        return pack

    @staticmethod
    def _extract_json_block(text: str) -> str:
        if not text:
            return "{}"
        
        # Clean the text first
        text = text.strip()
        
        # Try to extract JSON from code fences first
        code_fence_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text, re.IGNORECASE)
        if code_fence_match:
            return code_fence_match.group(1)
        
        # Try to find balanced JSON object
        start_idx = text.find('{')
        if start_idx == -1:
            return text
        
        # Count braces to find the end
        brace_count = 0
        end_idx = start_idx
        for i in range(start_idx, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i
                    break
        
        if brace_count == 0:
            return text[start_idx:end_idx + 1]
        
        # Fallback: try simple regex
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            return m.group(0)
        
        return text

    @staticmethod
    def _normalize_pack(pack: dict, shots_distribution: List[int]) -> dict:
        # Basic shape validation; if missing, fallback
        try:
            if not isinstance(pack, dict):
                raise ValueError("pack not dict")
            scenes = pack.get("scenes")
            if not isinstance(scenes, list) or not scenes:
                raise ValueError("no scenes")
            # Ensure each shot has 8s
            for sc in scenes:
                for sh in sc.get("shots", []) or []:
                    sh["duration_seconds"] = 8
            return pack
        except Exception:
            # fallback shape
            return {
                "characters": pack.get("characters", []),
                "environment": pack.get("environment", {}),
                "scenes": pack.get("scenes", []),
            }

    @staticmethod
    def _fallback_pack(keywords: str, shots_distribution: List[int]) -> dict:
        scenes = []
        shot_counter = 0
        for i, count in enumerate(shots_distribution, 1):
            shots = []
            for j in range(count):
                shot_counter += 1
                shots.append({
                    "duration_seconds": 8,
                    "prompt": f"Scene {i}, shot {j+1}. {keywords}",
                    "style": "3D Hyper Realistic / Cinematic",
                    "camera": "Wide / close mix",
                    "transition": "cut",
                    "dialogue": None,
                    "audio": {"bgm": "Ambient", "sfx": []},
                })
            scenes.append({
                "scene_id": i,
                "title": f"Scene {i}",
                "summary": f"Summary for scene {i} based on the keywords.",
                "shots": shots,
            })
        characters = [
            {"id": "character_1", "name": "Main Character", "description": "The protagonist."},
            {"id": "character_2", "name": "Supporting Character", "description": "Supports the protagonist."},
        ]
        env = {"name": "Environment", "description": "General setting."}
        return {"characters": characters, "environment": env, "scenes": scenes}

    @staticmethod
    def _extract_gen_ids(text: str) -> List[str]:
        try:
            return list(dict.fromkeys(re.findall(r"GEN_ID_[A-Z0-9_]+", text.upper())))
        except Exception:
            return []

    @staticmethod
    def _enforce_gen_ids(pack: dict, gen_ids: List[str]) -> dict:
        # Ensure characters array exists and uses provided GEN_IDs
        chars = []
        for gid in gen_ids[:2]:
            chars.append({
                "id": gid.lower(),
                "name": gid,
                "description": "Consistent character bound to this GEN_ID across all scenes. Outfit and accessories remain constant.",
            })
        pack["characters"] = chars
        # Inject GEN_IDs into every shot prompt if missing
        scenes = pack.get("scenes") or []
        for sc in scenes:
            for sh in sc.get("shots", []) or []:
                p = sh.get("prompt") or ""
                # Prepend the primary GEN_ID if not present
                first = gen_ids[0]
                if first not in p:
                    sh["prompt"] = f"{first}: " + p
        return pack

    @staticmethod
    def _ensure_timelines(pack: dict) -> dict:
        """Guarantee each shot has a timeline with 0-3 / 3-5 / 5-8 seconds descriptions.
        If missing, synthesize from the prompt by splitting sentences.
        """
        def synthesize(prompt: str) -> dict:
            # naive sentence split
            parts = [p.strip() for p in re.split(r"[.;]\s+", prompt) if p.strip()]
            t0_3 = parts[0] if parts else prompt
            t3_5 = parts[1] if len(parts) > 1 else (parts[0] if parts else prompt)
            t5_8 = parts[2] if len(parts) > 2 else (parts[-1] if parts else prompt)
            return {"0-3": t0_3, "3-5": t3_5, "5-8": t5_8}

        scenes = pack.get("scenes") or []
        for sc in scenes:
            for sh in sc.get("shots", []) or []:
                tl = sh.get("timeline")
                if not isinstance(tl, dict) or not all(k in tl for k in ("0-3", "3-5", "5-8")):
                    sh["timeline"] = synthesize(sh.get("prompt", ""))
                # Also enrich the main prompt with the timeline beats (English labels)
                tl = sh.get("timeline")
                timeline_prompt = (
                    f"Seconds 0-3: {tl.get('0-3','')}. Seconds 3-5: {tl.get('3-5','')}. Seconds 5-8: {tl.get('5-8','')}"
                )
                base = sh.get("prompt", "")
                if "Seconds 0-3" not in base:
                    sh["prompt"] = (base + " " + timeline_prompt).strip()
        return pack

    # -------- Writers --------
    @staticmethod
    def write_gemini_files(out_dir: str, pack: dict) -> dict:
        """Write three files: gemini_prompt.txt, gemini_shot_prompt.txt, characters.txt.
        Returns dict with paths.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        prompt_path = out / "gemini_prompt.txt"
        shot_path = out / "gemini_shot_prompt.txt"
        char_path = out / "characters.txt"

        # Clear previous files to avoid appending or stale content
        for p in (prompt_path, shot_path, char_path):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

        # gemini_prompt.txt: one JSON object per line per scene (similar to chatgpt_prompt style)
        lines = []
        global_style = (pack.get("_global_style") if isinstance(pack, dict) else None) or None
        for sc in (pack.get("scenes") or []):
            scene_obj = {
                "scene_id": sc.get("scene_id"),
                "video_duration": "8s",
                "characters": {(
                    c.get("id")
                ): json.dumps((lambda ch: (
                    (lambda details: {
                        "Name_ID": ch.get("name"),
                        "GEN_ID": ch.get("name"),
                        "Description": ch.get("description"),
                        "Details": details,
                        "Style_Lock": global_style or "3D Hyper Realistic / Cinematic",
                        "Outfit": "Keep constant across scenes",
                        "Accessories": "Keep constant across scenes",
                        "Consistency": {
                            "Palette_Lock": (details.get("consistency", {}) or {}).get("palette_lock") or (details.get("appearance", {}) or {}).get("color_palette"),
                            "Outfit_Lock": (details.get("consistency", {}) or {}).get("outfit_lock") or (details.get("outfit_accessories", {}) or {}).get("locked_style"),
                            "Hair_Lock": (details.get("consistency", {}) or {}).get("hair_lock") or details.get("hair_style"),
                            "Do_Not_Change": (details.get("consistency", {}) or {}).get("do_not_change") or [
                                "palette", "outfit", "hair", "distinctive_features", "age", "proportions", "accessories", "style"
                            ],
                            "Negative": (details.get("consistency", {}) or {}).get("negative") or "no text overlays, no watermarks, no logos, no extra characters, safe-for-work"
                        }
                    })((ch.get("details") or {}))
                ))(c), ensure_ascii=False) for c in (pack.get("characters") or [])},
                "environment": {
                    "environment_1": json.dumps({
                        "Name_ID": (pack.get("environment") or {}).get("name", "Environment"),
                        "Description": (pack.get("environment") or {}).get("description", "")
                    }, ensure_ascii=False)
                },
                "shots": [
                    {
                        "duration": f"{max(1, int((sh.get('duration_seconds') or 8)))}s",
                        "prompt": sh.get("prompt", ""),
                        "style": global_style or sh.get("style", ""),
                        "camera": sh.get("camera", ""),
                        "transition": sh.get("transition", "cut"),
                        "dialogue": sh.get("dialogue"),
                        "audio": sh.get("audio", {}),
                        "timeline": sh.get("timeline", {}),
                    }
                    for sh in (sc.get("shots") or [])
                ]
            }
            lines.append(json.dumps(scene_obj, ensure_ascii=False))
        prompt_path.write_text("\n".join(lines), encoding="utf-8")

        # gemini_shot_prompt.txt: one line per SHOT, enumerated scene_id_1..N (English)
        shot_lines = []
        sid = 1
        for sc in (pack.get("scenes") or []):
            for sh in (sc.get("shots") or []):
                p = sh.get("prompt", "")
                cam = sh.get("camera", "")
                sty = sh.get("style", "")
                tl = sh.get("timeline", {})
                t0_3 = tl.get("0-3", "")
                t3_5 = tl.get("3-5", "")
                t5_8 = tl.get("5-8", "")
                line = (
                    f"\"scene_id_{sid}\": \"{p} | Camera: {cam} | Style: {sty} | "
                    f"Timeline: 0-3s: {t0_3}; 3-5s: {t3_5}; 5-8s: {t5_8}\""
                )
                shot_lines.append(line.replace("\"", "'"))
                sid += 1
        shot_path.write_text("\n".join(shot_lines), encoding="utf-8")

        # characters.txt: one line per character similar to provided style
        char_lines = []
        for c in (pack.get("characters") or []):
            details = c.get("details") or {}
            consistency = details.get("consistency") or {}
            palette_lock = consistency.get("palette_lock") or (details.get("appearance") or {}).get("color_palette")
            outfit_lock = consistency.get("outfit_lock") or (details.get("outfit_accessories") or {}).get("locked_style")
            hair_lock = consistency.get("hair_lock") or details.get("hair_style")
            do_not_change = consistency.get("do_not_change") or [
                "palette", "outfit", "hair", "distinctive_features", "age", "proportions", "accessories", "style"
            ]
            negative = consistency.get("negative") or "no text overlays, no watermarks, no logos, no extra characters, safe-for-work"
            obj = {
                "Name_ID": c.get("name"),
                "Description": c.get("description", ""),
                "GEN_ID": c.get("name"),
                "Details": details,
                "Style_Lock": global_style or "3D Hyper Realistic / Cinematic",
                "Outfit": "Keep constant across scenes",
                "Accessories": "Keep constant across scenes",
                "Consistency": {
                    "Palette_Lock": palette_lock,
                    "Outfit_Lock": outfit_lock,
                    "Hair_Lock": hair_lock,
                    "Do_Not_Change": do_not_change,
                    "Negative": negative
                }
            }
            char_lines.append("\"Character Bible: " + json.dumps(obj, ensure_ascii=False) + "\"")
        env = pack.get("environment") or {}
        env_obj = {"Name_ID": env.get("name", "Environment"), "Description": env.get("description", "")}
        char_lines.append("\"Environment Bible: " + json.dumps(env_obj, ensure_ascii=False) + "\"")
        char_path.write_text("\n".join(char_lines), encoding="utf-8")

        return {"prompt": str(prompt_path), "shot": str(shot_path), "characters": str(char_path)}

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            candidates = data.get("candidates") or []
            if not candidates:
                return ""
            content = candidates[0].get("content") or {}
            parts = content.get("parts") or []
            for p in parts:
                if isinstance(p, dict) and p.get("text"):
                    return str(p["text"]).strip()
            return ""
        except Exception:
            return ""

    @staticmethod
    def _split_numbered_list(text: str, desired: int) -> List[str]:
        if not text:
            return []
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        # Remove possible numbering like "1.", "1)" or "1 -"
        prompts: List[str] = []
        for ln in lines:
            cleaned = ln
            # strip common prefixes
            for sep in [". ", ") ", " - ", ".", ")", " -"]:
                if len(cleaned) > 2 and cleaned[:2].isdigit():
                    pass
            # More robust: remove leading digits and separators
            i = 0
            while i < len(cleaned) and cleaned[i].isdigit():
                i += 1
            while i < len(cleaned) and cleaned[i] in ".)- ":
                i += 1
            cleaned = cleaned[i:].strip()
            if cleaned:
                prompts.append(cleaned)
        if desired > 0:
            return prompts[:desired]
        return prompts


