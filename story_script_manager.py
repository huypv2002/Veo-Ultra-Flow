"""
Story Script Manager - Quản lý viết kịch bản và đồng nhất câu truyện

Hệ thống quản lý dự án kịch bản video với:
- Khởi tạo dự án (thủ công/tự động)
- Quản lý hồ sơ nhân vật
- Nhật ký cốt truyện
- Tạo kịch bản đồng nhất
- Xuất định dạng JSON/Văn bản
"""

import json
import re
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path
from datetime import datetime
from enum import Enum


class ProjectStage(Enum):
    """Các giai đoạn của dự án"""
    NOT_STARTED = "not_started"
    SETUP = "setup"  # Giai đoạn 1
    CHARACTER_PROFILES = "character_profiles"  # Giai đoạn 2
    OPERATIONAL = "operational"  # Giai đoạn 3


class SetupMode(Enum):
    """Chế độ khởi tạo"""
    MANUAL = "manual"  # Thủ công
    AUTO = "auto"  # Tự động từ cốt truyện


@dataclass
class ProjectInfo:
    """Thông tin dự án"""
    num_characters: int = 0
    platform: str = "Veo"  # Veo hoặc Sora
    scene_duration: int = 10  # 8, 10, hoặc 15 giây
    theme: str = ""
    has_speech: bool = False
    main_language: str = ""
    setup_mode: str = SetupMode.MANUAL.value
    story_summary: str = ""  # Cho auto mode


@dataclass
class CharacterProfile:
    """Hồ sơ nhân vật đầy đủ"""
    # Phần A: Thông tin Cơ bản
    name: str = ""
    age: str = ""
    gender: str = ""
    role: str = ""  # Vai trò trong câu chuyện
    
    # Phần B: Ngoại hình
    appearance: str = ""
    clothing: str = ""
    distinctive_features: str = ""
    
    # Phần C: Âm thanh & Ngôn ngữ
    voice_description: str = ""
    speech_style: str = ""
    language: str = ""
    
    # Phần D: Hành vi & Cử chỉ
    behavior: str = ""
    gestures: str = ""
    movement_style: str = ""
    
    # Phần E: Tính cách & Nội tâm
    personality: str = ""
    emotions: str = ""
    motivations: str = ""
    
    # Phần F: Kiến thức & Kỹ năng
    knowledge: str = ""
    skills: str = ""
    limitations: str = ""
    
    # Phần G: Bối cảnh & Quan hệ
    background: str = ""
    relationships: str = ""
    context: str = ""
    
    # Phần H: Quy tắc Đồng bộ Cốt lõi
    always_rules: List[str] = field(default_factory=list)
    never_rules: List[str] = field(default_factory=list)


@dataclass
class StoryLogEntry:
    """Một mục nhật ký cốt truyện"""
    scene_number: int = 0
    timestamp: str = ""
    event_description: str = ""
    characters_involved: List[str] = field(default_factory=list)
    important_details: str = ""


@dataclass
class Scene:
    """Một cảnh trong kịch bản"""
    scene_number: int = 0
    duration: int = 10
    script_description: str = ""  # Mô tả kịch bản của cảnh (được AI gen trước)
    video_prompt: str = ""  # Prompt video (được AI gen sau, dựa trên script_description)
    dialogue: List[Dict[str, str]] = field(default_factory=list)  # [{"character": "A", "text": "..."}]
    characters_in_scene: List[str] = field(default_factory=list)
    consistency_check: Dict[str, Any] = field(default_factory=dict)


class StoryScriptManager:
    """Quản lý viết kịch bản và đồng nhất câu truyện"""
    
    def __init__(self, gemini_api_callback=None, log_callback=None):
        """Khởi tạo Story Script Manager
        
        Args:
            gemini_api_callback: Hàm callback để gọi Gemini API (keys, prompt, model) -> str
            log_callback: Hàm callback để log tiến trình (message: str) -> None
        """
        self.project_info = ProjectInfo()
        self.character_profiles: Dict[str, CharacterProfile] = {}
        self.story_log: List[StoryLogEntry] = []
        self.current_stage = ProjectStage.NOT_STARTED
        self.setup_mode = SetupMode.MANUAL
        self.generated_scenes: List[Scene] = []
        self.gemini_api_callback = gemini_api_callback
        self.log_callback = log_callback
        self.gemini_api_keys: List[str] = []
        
    # ===== GIAI ĐOẠN 1: KHỞI TẠO DỰ ÁN =====
    
    def start_manual_setup(self):
        """Bắt đầu khởi tạo thủ công (Tình huống A)"""
        self.current_stage = ProjectStage.SETUP
        self.setup_mode = SetupMode.MANUAL
        return {
            "stage": "setup_manual",
            "questions": [
                "Dự án này có bao nhiêu nhân vật chính?",
                "Bạn muốn sản xuất cho nền tảng video nào (Veo/Sora) và thời lượng trung bình mỗi cảnh là bao nhiêu (8, 10, hay 15 giây)?",
                "Chủ đề hoặc thông điệp chính của dự án là gì?",
                "Kịch bản có lời thoại không? (Vui lòng chọn: 1: Có / 2: Không)"
            ]
        }
    
    def process_manual_setup_answer(self, question_index: int, answer: str):
        """Xử lý câu trả lời trong setup thủ công"""
        if question_index == 0:
            # Số lượng nhân vật
            try:
                self.project_info.num_characters = int(answer.strip())
            except:
                return {"error": "Vui lòng nhập số nguyên hợp lệ"}
            return {"next_question": 1}
        
        elif question_index == 1:
            # Nền tảng & Thời lượng
            parts = answer.strip().split()
            platform = None
            duration = None
            
            for part in parts:
                if part.lower() in ["veo", "sora"]:
                    platform = part.capitalize()
                elif part in ["8", "10", "15"]:
                    duration = int(part)
            
            if platform:
                self.project_info.platform = platform
            if duration:
                self.project_info.scene_duration = duration
            
            return {"next_question": 2}
        
        elif question_index == 2:
            # Chủ đề
            self.project_info.theme = answer.strip()
            return {"next_question": 3}
        
        elif question_index == 3:
            # Lời thoại
            if answer.strip() in ["1", "có", "co", "yes", "y"]:
                self.project_info.has_speech = True
                return {
                    "next_question": "speech_language",
                    "question": "Ngôn ngữ chính là gì?"
                }
            else:
                self.project_info.has_speech = False
                return {"setup_complete": True}
        
        elif question_index == "speech_language":
            # Ngôn ngữ
            self.project_info.main_language = answer.strip()
            return {"setup_complete": True}
        
        return {"error": "Câu hỏi không hợp lệ"}
    
    def complete_manual_setup(self):
        """Hoàn tất setup thủ công"""
        self.project_info.setup_mode = SetupMode.MANUAL.value
        self.current_stage = ProjectStage.CHARACTER_PROFILES
        
        # Khởi tạo nhật ký rỗng
        self.story_log = []
        
        return {
            "status": "success",
            "message": "Khởi tạo 'Nhật ký cốt truyện' (Story Log) rỗng. Dự án đã sẵn sàng.",
            "summary": self.get_setup_summary(),
            "next_stage": "character_profiles_manual"
        }
    
    def start_auto_setup(self, story_summary: str):
        """Bắt đầu khởi tạo tự động từ cốt truyện (Tình huống B)"""
        self.current_stage = ProjectStage.SETUP
        self.setup_mode = SetupMode.AUTO
        self.project_info.story_summary = story_summary
        self.project_info.setup_mode = SetupMode.AUTO.value
        
        # Phân tích cốt truyện (đơn giản hóa - có thể tích hợp AI sau)
        analysis = self._analyze_story(story_summary)
        
        # Tự động điền một số thông tin
        self.project_info.num_characters = analysis.get("num_characters", 0)
        self.project_info.theme = analysis.get("theme", "")
        
        # Tạo nhật ký ban đầu từ cốt truyện
        self._create_initial_story_log(story_summary)
        
        return {
            "status": "analyzed",
            "message": f"Phân tích hoàn tất. Ghi nhận {analysis.get('num_characters', 0)} nhân vật chính. Chủ đề chính: {analysis.get('theme', 'Chưa xác định')}.",
            "analysis": analysis,
            "next_stage": "character_profiles_auto",
            "missing_info": {
                "questions": [
                    "Vui lòng cung cấp các thông tin sản xuất còn thiếu:",
                    "Nền tảng Video (Veo/Sora):",
                    "Thời lượng cảnh (8/10/15s):",
                    "Kịch bản có lời thoại không (Có/Không):"
                ]
            }
        }
    
    def complete_auto_setup(self, platform: str, duration: int, has_speech: bool, language: str = ""):
        """Hoàn tất setup tự động với thông tin bổ sung"""
        self.project_info.platform = platform
        self.project_info.scene_duration = duration
        self.project_info.has_speech = has_speech
        if has_speech:
            self.project_info.main_language = language
        
        self.current_stage = ProjectStage.CHARACTER_PROFILES
        
        return {
            "status": "success",
            "message": "Đã hoàn tất khởi tạo tự động",
            "summary": self.get_setup_summary(),
            "next_stage": "character_profiles_auto"
        }
    
    def _analyze_story(self, story: str) -> Dict[str, Any]:
        """Phân tích cốt truyện để trích xuất thông tin"""
        # Đơn giản hóa - có thể tích hợp AI/LLM sau
        story_lower = story.lower()
        
        # Đếm nhân vật (tìm tên riêng hoặc từ khóa)
        # Giả định: tìm các từ viết hoa hoặc sau "nhân vật"
        character_keywords = ["nhân vật", "character", "người", "anh", "chị", "ông", "bà"]
        num_chars = max(1, story.count("nhân vật") + story.count("character"))
        
        # Trích xuất chủ đề (câu đầu tiên hoặc từ khóa)
        lines = story.split('\n')
        theme = lines[0].strip() if lines else "Chưa xác định"
        if len(theme) > 100:
            theme = theme[:100] + "..."
        
        return {
            "num_characters": num_chars,
            "theme": theme,
            "keywords": self._extract_keywords(story)
        }
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Trích xuất từ khóa từ văn bản"""
        # Đơn giản hóa
        words = re.findall(r'\b\w+\b', text.lower())
        common_words = {"và", "của", "là", "một", "có", "được", "cho", "với", "trong", "the", "a", "an", "is", "are"}
        keywords = [w for w in words if w not in common_words and len(w) > 3]
        return list(set(keywords))[:10]
    
    def _create_initial_story_log(self, story: str):
        """Tạo nhật ký ban đầu từ cốt truyện"""
        # Chia cốt truyện thành các sự kiện chính
        sentences = re.split(r'[.!?]\s+', story)
        for idx, sentence in enumerate(sentences[:10], 1):  # Tối đa 10 sự kiện
            if len(sentence.strip()) > 10:
                entry = StoryLogEntry(
                    scene_number=idx,
                    timestamp=datetime.now().isoformat(),
                    event_description=sentence.strip(),
                    characters_involved=[],
                    important_details=""
                )
                self.story_log.append(entry)
    
    def get_setup_summary(self) -> Dict[str, Any]:
        """Lấy tóm tắt cấu hình"""
        return {
            "Số lượng nhân vật": self.project_info.num_characters,
            "Nền tảng": self.project_info.platform,
            "Thời lượng cảnh": f"{self.project_info.scene_duration} giây",
            "Chủ đề": self.project_info.theme,
            "Có lời thoại": "Có" if self.project_info.has_speech else "Không",
            "Ngôn ngữ": self.project_info.main_language if self.project_info.has_speech else "N/A"
        }
    
    # ===== GIAI ĐOẠN 2: NHẬP HỒ SƠ NHÂN VẬT =====
    
    def add_character_profile(self, character_name: str, profile_data: Dict[str, Any]):
        """Thêm hoặc cập nhật hồ sơ nhân vật"""
        if character_name not in self.character_profiles:
            self.character_profiles[character_name] = CharacterProfile()
        
        profile = self.character_profiles[character_name]
        profile.name = character_name
        
        # Cập nhật từng phần
        if "A" in profile_data:
            part_a = profile_data["A"]
            profile.age = part_a.get("age", "")
            profile.gender = part_a.get("gender", "")
            profile.role = part_a.get("role", "")
        
        if "B" in profile_data:
            part_b = profile_data["B"]
            profile.appearance = part_b.get("appearance", "")
            profile.clothing = part_b.get("clothing", "")
            profile.distinctive_features = part_b.get("distinctive_features", "")
        
        if "C" in profile_data:
            part_c = profile_data["C"]
            profile.voice_description = part_c.get("voice_description", "")
            profile.speech_style = part_c.get("speech_style", "")
            profile.language = part_c.get("language", "")
        
        if "D" in profile_data:
            part_d = profile_data["D"]
            profile.behavior = part_d.get("behavior", "")
            profile.gestures = part_d.get("gestures", "")
            profile.movement_style = part_d.get("movement_style", "")
        
        if "E" in profile_data:
            part_e = profile_data["E"]
            profile.personality = part_e.get("personality", "")
            profile.emotions = part_e.get("emotions", "")
            profile.motivations = part_e.get("motivations", "")
        
        if "F" in profile_data:
            part_f = profile_data["F"]
            profile.knowledge = part_f.get("knowledge", "")
            profile.skills = part_f.get("skills", "")
            profile.limitations = part_f.get("limitations", "")
        
        if "G" in profile_data:
            part_g = profile_data["G"]
            profile.background = part_g.get("background", "")
            profile.relationships = part_g.get("relationships", "")
            profile.context = part_g.get("context", "")
        
        if "H" in profile_data:
            part_h = profile_data["H"]
            profile.always_rules = part_h.get("always_rules", [])
            profile.never_rules = part_h.get("never_rules", [])
        
        return {"status": "success", "character": character_name}
    
    def auto_fill_character_profiles(self, story_summary: str) -> Dict[str, CharacterProfile]:
        """Tự động điền hồ sơ nhân vật từ cốt truyện (Giai đoạn 2B)"""
        # Đơn giản hóa - có thể tích hợp AI sau
        auto_profiles = {}
        
        # Tìm tên nhân vật trong cốt truyện
        # Giả định: tìm các từ viết hoa hoặc sau "nhân vật"
        character_names = self._extract_character_names(story_summary)
        
        for name in character_names[:self.project_info.num_characters]:
            profile = CharacterProfile()
            profile.name = name
            profile.role = "Nhân vật chính"  # Mặc định
            profile.personality = "Được mô tả trong cốt truyện"
            profile.background = "Liên quan đến cốt truyện"
            auto_profiles[name] = profile
        
        return auto_profiles
    
    def _extract_character_names(self, text: str) -> List[str]:
        """Trích xuất tên nhân vật từ văn bản"""
        # Đơn giản hóa - tìm từ viết hoa
        words = text.split()
        names = []
        for word in words:
            if word and word[0].isupper() and len(word) > 1:
                # Loại bỏ dấu câu
                clean_name = re.sub(r'[^\w\s]', '', word)
                if clean_name and clean_name not in names:
                    names.append(clean_name)
        return names[:10]  # Tối đa 10 tên
    
    def confirm_character_profiles(self, confirmed_profiles: Dict[str, Dict[str, Any]]):
        """Xác nhận và bổ sung hồ sơ nhân vật"""
        for char_name, profile_data in confirmed_profiles.items():
            self.add_character_profile(char_name, profile_data)
        
        self.current_stage = ProjectStage.OPERATIONAL
        return {
            "status": "success",
            "message": "Đã xác nhận hồ sơ nhân vật",
            "num_characters": len(self.character_profiles),
            "next_stage": "operational"
        }
    
    # ===== GIAI ĐOẠN 3: VẬN HÀNH =====
    
    def query_character(self, question: str) -> str:
        """Chế độ tra cứu & kiểm tra (3A)"""
        question_lower = question.lower()
        
        # Tìm nhân vật được hỏi
        mentioned_characters = []
        for char_name in self.character_profiles.keys():
            if char_name.lower() in question_lower:
                mentioned_characters.append(char_name)
        
        if not mentioned_characters:
            return "Không tìm thấy nhân vật nào trong câu hỏi."
        
        # Phân tích câu hỏi và tìm trong hồ sơ
        answers = []
        for char_name in mentioned_characters:
            profile = self.character_profiles[char_name]
            
            # Kiểm tra các phần khác nhau
            if any(word in question_lower for word in ["biết", "know", "kỹ năng", "skill"]):
                # Kiểm tra Phần F
                if "không" in question_lower or "not" in question_lower:
                    if profile.limitations:
                        answers.append(f"{char_name}: {profile.limitations}")
                else:
                    if profile.skills:
                        answers.append(f"{char_name}: {profile.skills}")
            
            elif any(word in question_lower for word in ["hành động", "action", "hợp lý", "logical"]):
                # Kiểm tra Phần H (Quy tắc)
                if profile.always_rules:
                    answers.append(f"{char_name} luôn: {', '.join(profile.always_rules)}")
                if profile.never_rules:
                    answers.append(f"{char_name} không bao giờ: {', '.join(profile.never_rules)}")
            
            elif any(word in question_lower for word in ["tính cách", "personality"]):
                if profile.personality:
                    answers.append(f"{char_name}: {profile.personality}")
        
        if answers:
            return "\n".join(answers)
        else:
            return "Không tìm thấy thông tin liên quan trong hồ sơ nhân vật."
    
    def add_story_log_entry(self, event_description: str, characters_involved: List[str] = None, important_details: str = ""):
        """Chế độ ghi nhật ký (3B)"""
        scene_number = len(self.story_log) + 1
        entry = StoryLogEntry(
            scene_number=scene_number,
            timestamp=datetime.now().isoformat(),
            event_description=event_description,
            characters_involved=characters_involved or [],
            important_details=important_details
        )
        self.story_log.append(entry)
        return {"status": "success", "entry": entry}
    
    def generate_scenes(self, total_minutes: int = None, story_theme: str = "", num_scenes: int = None, 
                       gemini_keys: List[str] = None) -> List[Scene]:
        """Chế độ sáng tạo & xuất (3C) - Tạo kịch bản
        
        Workflow:
        1. AI gen kịch bản (các cảnh với mô tả sự kiện)
        2. AI gen prompt cho từng cảnh dựa trên kịch bản
        
        Args:
            total_minutes: Tổng số phút (cho batch mode)
            story_theme: Chủ đề câu truyện cụ thể (bắt buộc)
            num_scenes: Số cảnh cụ thể (cho single scene)
            gemini_keys: Danh sách Gemini API keys (nếu có)
        """
        if gemini_keys:
            self.gemini_api_keys = gemini_keys
        
        if not story_theme.strip():
            raise ValueError("Vui lòng nhập chủ đề câu truyện cụ thể!")
        
        if num_scenes is None:
            if total_minutes is None:
                return []
            # Tính số cảnh
            total_seconds = total_minutes * 60
            num_scenes = total_seconds // self.project_info.scene_duration
        
        # BƯỚC 1: AI gen kịch bản (các cảnh với mô tả)
        script_scenes = self._generate_script_with_ai(story_theme, num_scenes)
        
        if not script_scenes:
            # Fallback: Tạo cảnh cơ bản
            script_scenes = []
            for i in range(1, num_scenes + 1):
                script_scenes.append({
                    "scene_number": i,
                    "description": f"Cảnh {i} trong câu truyện",
                    "characters": self._get_characters_for_scene(i),
                    "dialogue": []
                })
        
        # BƯỚC 2: Tạo Scene objects và gen prompt cho từng cảnh
        if hasattr(self, 'log_callback') and self.log_callback:
            self.log_callback(f"📹 BƯỚC 2: Đang tạo prompt video cho {len(script_scenes)} cảnh...")
        
        scenes = []
        for idx, script_scene in enumerate(script_scenes, 1):
            scene_num = script_scene.get("scene_number", len(scenes) + 1)
            scene_description = script_scene.get("description", "")
            scene_chars = script_scene.get("characters", [])
            scene_dialogue = script_scene.get("dialogue", [])
            
            # Đảm bảo có nhân vật (từ AI hoặc fallback)
            if not scene_chars:
                scene_chars = self._get_characters_for_scene(scene_num)
            
            # Log progress
            if hasattr(self, 'log_callback') and self.log_callback:
                self.log_callback(f"  ⏳ Đang xử lý cảnh {scene_num}/{len(script_scenes)}...")
            
            # Gen prompt video dựa trên kịch bản đã tạo
            video_prompt = self._generate_video_prompt_from_script(
                scene_num, scene_description, story_theme, scene_chars
            )
            
            scene = Scene(
                scene_number=scene_num,
                duration=self.project_info.scene_duration,
                script_description=scene_description,
                video_prompt=video_prompt,
                dialogue=scene_dialogue if scene_dialogue else [],
                characters_in_scene=scene_chars,
                consistency_check=self._check_consistency(scene_num)
            )
            
            # Thêm lời thoại nếu có (từ AI hoặc generate)
            if not scene.dialogue and self.project_info.has_speech:
                scene.dialogue = self._generate_dialogue(scene_num)
            
            scenes.append(scene)
        
        self.generated_scenes = scenes
        return scenes
    
    def _generate_script_with_ai(self, story_theme: str, num_scenes: int) -> List[Dict[str, Any]]:
        """BƯỚC 1: AI gen kịch bản (các cảnh với mô tả)"""
        if not self.gemini_api_callback or not self.gemini_api_keys:
            return []  # Fallback về template mode
        
        try:
            # Xây dựng prompt để AI gen kịch bản
            if self.log_callback:
                self.log_callback(f"📝 BƯỚC 1: Đang tạo kịch bản với AI ({num_scenes} cảnh)...")
            prompt = self._build_script_generation_prompt(story_theme, num_scenes)
            response = self.gemini_api_callback(self.gemini_api_keys, prompt, "gemini-2.0-flash")
            if self.log_callback:
                self.log_callback(f"✅ BƯỚC 1: Hoàn thành tạo kịch bản!")
            
            if response and response.strip():
                import json
                try:
                    # Parse JSON response
                    response_clean = response.strip()
                    if response_clean.startswith("```json"):
                        response_clean = response_clean[7:]
                    if response_clean.startswith("```"):
                        response_clean = response_clean[3:]
                    if response_clean.endswith("```"):
                        response_clean = response_clean[:-3]
                    response_clean = response_clean.strip()
                    
                    parsed = json.loads(response_clean)
                    
                    # Parse scenes từ response
                    if isinstance(parsed, dict) and "scenes" in parsed:
                        return parsed["scenes"]
                    elif isinstance(parsed, list):
                        return parsed
                except Exception as e:
                    # Nếu không parse được JSON, thử parse text
                    return self._parse_script_from_text(response)
        except Exception as e:
            pass
        
        return []
    
    def _build_script_generation_prompt(self, story_theme: str, num_scenes: int) -> str:
        """Xây dựng prompt để AI gen kịch bản"""
        # Thu thập thông tin nhân vật
        char_summaries = []
        for char_name, profile in self.character_profiles.items():
            char_summary = f"- {char_name}: {profile.role}"
            if profile.personality:
                char_summary += f", Tính cách: {profile.personality[:100]}"
            char_summaries.append(char_summary)
        
        prompt = f"""Bạn là một biên kịch chuyên nghiệp. Nhiệm vụ của bạn là tạo kịch bản video chi tiết.

THÔNG TIN DỰ ÁN:
- Chủ đề: {self.project_info.theme}
- Chủ đề câu truyện cụ thể: {story_theme}
- Nền tảng: {self.project_info.platform}
- Thời lượng mỗi cảnh: {self.project_info.scene_duration} giây
- Số cảnh cần tạo: {num_scenes}
- Có lời thoại: {'Có' if self.project_info.has_speech else 'Không'}
- Ngôn ngữ: {self.project_info.main_language if self.project_info.has_speech else 'N/A'}

NHÂN VẬT:
{chr(10).join(char_summaries) if char_summaries else "Chưa có nhân vật"}

NHẬT KÝ CỐT TRUYỆN:
"""
        
        if self.story_log:
            for entry in self.story_log[-5:]:  # 5 sự kiện gần nhất
                prompt += f"- Cảnh {entry.scene_number}: {entry.event_description}\n"
        else:
            prompt += "Chưa có sự kiện\n"
        
        prompt += f"""
YÊU CẦU:
1. Tạo {num_scenes} cảnh kịch bản dựa trên chủ đề câu truyện: "{story_theme}"
2. Mỗi cảnh phải có mô tả rõ ràng về sự kiện, hành động, cảm xúc
3. Phân bổ nhân vật hợp lý cho từng cảnh
4. Đảm bảo tính liên kết giữa các cảnh
5. Tuân thủ quy tắc "Luôn luôn" và "Không bao giờ" của từng nhân vật
6. Nếu có lời thoại, tạo lời thoại phù hợp với tính cách nhân vật

Trả về JSON format:
{{
  "scenes": [
    {{
      "scene_number": 1,
      "description": "Mô tả chi tiết sự kiện trong cảnh này...",
      "characters": ["Tên nhân vật 1", "Tên nhân vật 2"],
      "dialogue": [
        {{"character": "Tên nhân vật", "text": "Lời thoại..."}}
      ]
    }},
    ...
  ]
}}
"""
        
        return prompt
    
    def _parse_script_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Parse kịch bản từ text nếu không phải JSON"""
        # Đơn giản hóa - tìm các cảnh trong text
        scenes = []
        lines = text.split('\n')
        current_scene = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Tìm số cảnh
            import re
            scene_match = re.search(r'cảnh\s+(\d+)', line, re.IGNORECASE)
            if scene_match:
                if current_scene:
                    scenes.append(current_scene)
                current_scene = {
                    "scene_number": int(scene_match.group(1)),
                    "description": line,
                    "characters": [],
                    "dialogue": []
                }
            elif current_scene:
                current_scene["description"] += " " + line
        
        if current_scene:
            scenes.append(current_scene)
        
        return scenes
    
    def _generate_video_prompt_from_script(self, scene_number: int, script_description: str, 
                                           story_theme: str, characters: List[str]) -> str:
        """BƯỚC 2: Gen prompt video dựa trên kịch bản đã tạo"""
        # Sử dụng script_description làm context chính
        context = f"{script_description}"
        if story_theme:
            context = f"{story_theme}. {context}"
        
        # Truyền script_description vào để _build_gemini_prompt sử dụng
        return self._generate_video_prompt(scene_number, context, script_description)
    
    def _generate_video_prompt(self, scene_number: int, context: str = "", script_description: str = "") -> str:
        """Tạo prompt video cho cảnh - Sử dụng Gemini AI nếu có, fallback về template"""
        characters = self._get_characters_for_scene(scene_number)
        
        # Thử dùng Gemini AI nếu có
        if self.gemini_api_callback and self.gemini_api_keys:
            try:
                ai_prompt = self._build_gemini_prompt(scene_number, context, characters, script_description)
                response = self.gemini_api_callback(self.gemini_api_keys, ai_prompt, "gemini-2.0-flash")
                
                if response and response.strip():
                    # Parse response từ Gemini (có thể là JSON hoặc text)
                    import json
                    try:
                        # Thử parse JSON
                        response_clean = response.strip()
                        if response_clean.startswith("```json"):
                            response_clean = response_clean[7:]
                        if response_clean.startswith("```"):
                            response_clean = response_clean[3:]
                        if response_clean.endswith("```"):
                            response_clean = response_clean[:-3]
                        response_clean = response_clean.strip()
                        
                        parsed = json.loads(response_clean)
                        if isinstance(parsed, dict) and "prompt" in parsed:
                            return parsed["prompt"]
                        elif isinstance(parsed, str):
                            return parsed
                    except:
                        # Nếu không phải JSON, dùng trực tiếp
                        return response.strip()
            except Exception as e:
                # Fallback về template nếu Gemini lỗi
                pass
        
        # Fallback: Template-based prompt
        return self._generate_template_prompt(scene_number, context, characters)
    
    def _build_gemini_prompt(self, scene_number: int, context: str, characters: List[str], script_description: str = "") -> str:
        """Xây dựng prompt cho Gemini AI để gen prompt video"""
        # Nếu không có script_description từ tham số, thử tìm từ generated_scenes
        if not script_description:
            for scene in self.generated_scenes:
                if scene.scene_number == scene_number and hasattr(scene, 'script_description'):
                    script_description = scene.script_description
                    break
        
        # Thu thập thông tin nhân vật
        char_info_list = []
        for char_name in characters:
            if char_name in self.character_profiles:
                profile = self.character_profiles[char_name]
                char_info = {
                    "name": char_name,
                    "role": profile.role,
                    "appearance": profile.appearance,
                    "personality": profile.personality,
                    "always_rules": profile.always_rules,
                    "never_rules": profile.never_rules
                }
                char_info_list.append(char_info)
        
        # Thu thập story log liên quan
        relevant_events = []
        for entry in self.story_log:
            if entry.scene_number == scene_number or entry.scene_number == scene_number - 1:
                relevant_events.append({
                    "scene": entry.scene_number,
                    "event": entry.event_description,
                    "characters": entry.characters_involved
                })
        
        prompt = f"""Bạn là một chuyên gia viết prompt video chuyên nghiệp. Nhiệm vụ của bạn là tạo một prompt video chi tiết cho cảnh {scene_number} trong một dự án video.

KỊCH BẢN CẢNH {scene_number}:
{script_description if script_description else "Chưa có mô tả kịch bản"}

THÔNG TIN DỰ ÁN:
- Chủ đề: {self.project_info.theme}
- Nền tảng: {self.project_info.platform}
- Thời lượng cảnh: {self.project_info.scene_duration} giây
- Có lời thoại: {'Có' if self.project_info.has_speech else 'Không'}
- Ngôn ngữ: {self.project_info.main_language if self.project_info.has_speech else 'N/A'}

NHÂN VẬT TRONG CẢNH:
"""
        
        for char_info in char_info_list:
            prompt += f"""
- {char_info['name']}:
  + Vai trò: {char_info['role']}
  + Ngoại hình: {char_info['appearance']}
  + Tính cách: {char_info['personality']}
  + Luôn luôn: {', '.join(char_info['always_rules']) if char_info['always_rules'] else 'Không có'}
  + Không bao giờ: {', '.join(char_info['never_rules']) if char_info['never_rules'] else 'Không có'}
"""
        
        if relevant_events:
            prompt += "\nBỐI CẢNH TỪ CỐT TRUYỆN:\n"
            for event in relevant_events:
                prompt += f"- Cảnh {event['scene']}: {event['event']}\n"
        
        if context:
            prompt += f"\nBỐI CẢNH BỔ SUNG: {context}\n"
        
        prompt += f"""
YÊU CẦU:
1. Tạo một prompt video chi tiết, sinh động, mô tả rõ ràng cảnh quay
2. Đảm bảo nhân vật tuân thủ các quy tắc "Luôn luôn" và "Không bao giờ"
3. Prompt phải phù hợp với thời lượng {self.project_info.scene_duration} giây
4. Mô tả rõ: góc quay, ánh sáng, cảm xúc, hành động
5. Độ dài prompt: 100-300 từ
6. Ngôn ngữ: Tiếng Việt

Trả về JSON format:
{{
  "prompt": "prompt video chi tiết của bạn ở đây"
}}
"""
        
        return prompt
    
    def _generate_template_prompt(self, scene_number: int, context: str, characters: List[str]) -> str:
        """Tạo prompt dựa trên template (fallback)"""
        prompt_parts = []
        
        # Thông tin cảnh
        prompt_parts.append(f"Cảnh {scene_number}")
        
        # Thêm context/bối cảnh
        if context:
            prompt_parts.append(context)
        elif self.project_info.theme:
            prompt_parts.append(f"Chủ đề: {self.project_info.theme}")
        
        # Thông tin nhân vật chi tiết
        if characters:
            char_details = []
            for char_name in characters:
                if char_name in self.character_profiles:
                    profile = self.character_profiles[char_name]
                    char_info = f"{char_name}"
                    
                    # Thêm ngoại hình nếu có
                    if profile.appearance:
                        char_info += f" ({profile.appearance[:50]})"
                    
                    char_details.append(char_info)
                else:
                    char_details.append(char_name)
            
            if char_details:
                prompt_parts.append(f"Với nhân vật: {', '.join(char_details)}")
        
        # Thêm thông tin từ nhật ký
        if self.story_log:
            # Tìm sự kiện liên quan đến cảnh này
            relevant_events = []
            for entry in self.story_log:
                if entry.scene_number == scene_number or entry.scene_number == scene_number - 1:
                    relevant_events.append(entry.event_description)
            
            if relevant_events:
                prompt_parts.append(f"Bối cảnh: {relevant_events[-1][:100]}")
        
        # Thêm thông tin kỹ thuật
        if self.project_info.platform:
            prompt_parts.append(f"Nền tảng: {self.project_info.platform}")
        
        # Kết hợp tất cả
        full_prompt = ". ".join(prompt_parts)
        
        # Đảm bảo prompt không quá dài
        if len(full_prompt) > 500:
            full_prompt = full_prompt[:497] + "..."
        
        return full_prompt if full_prompt else f"Cảnh {scene_number}"
    
    def _get_characters_for_scene(self, scene_number: int) -> List[str]:
        """Lấy danh sách nhân vật cho cảnh"""
        # Đơn giản hóa - phân bổ nhân vật theo cảnh
        all_chars = list(self.character_profiles.keys())
        if not all_chars:
            return []
        
        # Round-robin hoặc dựa trên nhật ký
        char_index = (scene_number - 1) % len(all_chars)
        num_chars_in_scene = min(2, len(all_chars))  # Tối đa 2 nhân vật/cảnh
        return all_chars[char_index:char_index + num_chars_in_scene]
    
    def _generate_dialogue(self, scene_number: int) -> List[Dict[str, str]]:
        """Tạo lời thoại cho cảnh"""
        dialogue = []
        characters = self._get_characters_for_scene(scene_number)
        
        if not characters or not self.project_info.has_speech:
            return dialogue
        
        # Đơn giản hóa - tạo 1-2 câu thoại
        for i, char in enumerate(characters[:2]):
            dialogue.append({
                "character": char,
                "text": f"[Lời thoại của {char} trong cảnh {scene_number}]"
            })
        
        return dialogue
    
    def _check_consistency(self, scene_number: int) -> Dict[str, Any]:
        """Kiểm tra tính đồng nhất cho cảnh"""
        characters = self._get_characters_for_scene(scene_number)
        checks = {
            "characters_consistent": True,
            "story_continuity": True,
            "rules_followed": True,
            "warnings": []
        }
        
        # Kiểm tra quy tắc nhân vật
        for char_name in characters:
            if char_name in self.character_profiles:
                profile = self.character_profiles[char_name]
                # Có thể thêm logic kiểm tra phức tạp hơn
                if profile.never_rules:
                    checks["warnings"].append(f"Đảm bảo {char_name} không vi phạm: {', '.join(profile.never_rules)}")
        
        return checks
    
    # ===== XUẤT ĐỊNH DẠNG =====
    
    def export_json_format(self) -> str:
        """Xuất định dạng JSON Tự chứa (Lựa chọn 1)"""
        output = []
        
        for scene in self.generated_scenes:
            scene_data = {
                "projectInfo": asdict(self.project_info),
                "characterProfiles": {
                    name: asdict(profile) 
                    for name, profile in self.character_profiles.items()
                },
                "storyLog": [asdict(entry) for entry in self.story_log],
                "currentScene": {
                    "sceneNumber": scene.scene_number,
                    "duration": scene.duration,
                    "scriptDescription": getattr(scene, 'script_description', ''),
                    "videoPrompt": scene.video_prompt,
                    "dialogue": scene.dialogue,
                    "charactersInScene": scene.characters_in_scene,
                    "consistencyCheck": scene.consistency_check
                }
            }
            
            output.append(json.dumps(scene_data, ensure_ascii=False, indent=2))
        
        # Ngăn cách bằng "---" và dòng trống
        return "\n---\n\n".join(output)
    
    def export_text_format(self) -> str:
        """Xuất định dạng Văn bản Thô (Lựa chọn 2) - Format chi tiết hơn"""
        lines = ["═══════════════════════════════════════════════════════════════════════════════"]
        lines.append("                    KỊCH BẢN VIDEO - ĐỊNH DẠNG VĂN BẢN")
        lines.append("═══════════════════════════════════════════════════════════════════════════════")
        lines.append("")
        lines.append(f"📋 THÔNG TIN DỰ ÁN:")
        lines.append(f"  • Chủ đề: {self.project_info.theme}")
        lines.append(f"  • Nền tảng: {self.project_info.platform}")
        lines.append(f"  • Thời lượng cảnh: {self.project_info.scene_duration} giây")
        lines.append(f"  • Có lời thoại: {'Có' if self.project_info.has_speech else 'Không'}")
        if self.project_info.has_speech:
            lines.append(f"  • Ngôn ngữ: {self.project_info.main_language}")
        lines.append("")
        lines.append(f"👥 NHÂN VẬT: {', '.join(self.character_profiles.keys()) if self.character_profiles else 'Chưa có'}")
        lines.append("")
        lines.append("═══════════════════════════════════════════════════════════════════════════════")
        lines.append("")
        
        for scene in self.generated_scenes:
            lines.append(f"🎬 CẢNH {scene.scene_number} ({scene.duration} giây)")
            lines.append("─" * 80)
            
            # Kịch bản (Script Description) - Nếu có
            if hasattr(scene, 'script_description') and scene.script_description:
                lines.append(f"📝 KỊCH BẢN:")
                lines.append(f"   {scene.script_description}")
                lines.append("")
            
            # Prompt Video chi tiết
            lines.append(f"📹 PROMPT VIDEO:")
            lines.append(f"   {scene.video_prompt}")
            lines.append("")
            
            # Nhân vật trong cảnh
            if scene.characters_in_scene:
                lines.append(f"👥 NHÂN VẬT:")
                for char in scene.characters_in_scene:
                    lines.append(f"   • {char}")
                lines.append("")
            
            # Lời thoại
            if scene.dialogue:
                lines.append(f"💬 LỜI THOẠI:")
                for dialogue_item in scene.dialogue:
                    char_name = dialogue_item.get('character', 'Unknown')
                    text = dialogue_item.get('text', '')
                    lines.append(f"   [{char_name}]: {text}")
                lines.append("")
            
            # Kiểm tra đồng nhất
            if scene.consistency_check and scene.consistency_check.get('warnings'):
                lines.append(f"⚠️ LƯU Ý ĐỒNG BỘ:")
                for warning in scene.consistency_check['warnings']:
                    lines.append(f"   • {warning}")
                lines.append("")
            
            lines.append("")  # Dòng trống giữa các cảnh
        
        lines.append("═══════════════════════════════════════════════════════════════════════════════")
        lines.append(f"Tổng cộng: {len(self.generated_scenes)} cảnh")
        total_seconds = sum(s.duration for s in self.generated_scenes)
        total_minutes = total_seconds // 60
        remaining_seconds = total_seconds % 60
        lines.append(f"Tổng thời lượng: {total_minutes} phút {remaining_seconds} giây")
        lines.append("═══════════════════════════════════════════════════════════════════════════════")
        
        return "\n".join(lines)
    
    # ===== LƯU/TẢI DỰ ÁN =====
    
    def save_project(self, file_path: str):
        """Lưu dự án ra file JSON"""
        data = {
            "project_info": asdict(self.project_info),
            "character_profiles": {
                name: asdict(profile) 
                for name, profile in self.character_profiles.items()
            },
            "story_log": [asdict(entry) for entry in self.story_log],
            "generated_scenes": [asdict(scene) for scene in self.generated_scenes],
            "current_stage": self.current_stage.value,
            "setup_mode": self.setup_mode.value
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def load_project(self, file_path: str):
        """Tải dự án từ file JSON"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.project_info = ProjectInfo(**data.get("project_info", {}))
        self.character_profiles = {
            name: CharacterProfile(**profile_data)
            for name, profile_data in data.get("character_profiles", {}).items()
        }
        self.story_log = [
            StoryLogEntry(**entry_data)
            for entry_data in data.get("story_log", [])
        ]
        self.generated_scenes = [
            Scene(**scene_data)
            for scene_data in data.get("generated_scenes", [])
        ]
        self.current_stage = ProjectStage(data.get("current_stage", "not_started"))
        self.setup_mode = SetupMode(data.get("setup_mode", "manual"))
    
    # ===== QUẢN LÝ NHÂN VẬT RIÊNG LẺ =====
    
    def save_character_to_file(self, character_name: str, file_path: str, format: str = "json"):
        """Lưu một nhân vật ra file riêng (JSON hoặc text)"""
        if character_name not in self.character_profiles:
            raise ValueError(f"Nhân vật '{character_name}' không tồn tại!")
        
        profile = self.character_profiles[character_name]
        
        if format.lower() == "json":
            data = {
                "character_name": character_name,
                "profile": asdict(profile),
                "saved_at": datetime.now().isoformat()
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:  # text format
            # Format giống hoso.txt
            text = self._format_character_to_text(character_name, profile)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(text)
    
    def load_character_from_file(self, file_path: str) -> Tuple[str, CharacterProfile]:
        """Tải một nhân vật từ file (trả về tên và profile)"""
        file_path_obj = Path(file_path)
        
        if file_path_obj.suffix.lower() == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            character_name = data.get("character_name", "")
            profile_data = data.get("profile", {})
            profile = CharacterProfile(**profile_data)
            
            return character_name, profile
        else:
            # Parse từ text format
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Tìm tên nhân vật từ file
            name_match = re.search(r'NHÂN VẬT\s+\d+:\s*(.+)', content, re.IGNORECASE)
            if not name_match:
                # Thử tìm ID
                id_match = re.search(r'ID Nhân vật:\s*(.+)', content, re.IGNORECASE)
                if id_match:
                    character_name = id_match.group(1).strip()
                else:
                    # Lấy tên từ file
                    character_name = file_path_obj.stem
            else:
                character_name = name_match.group(1).strip()
            
            from character_profile_parser import parse_character_profile_from_text
            profile_data = parse_character_profile_from_text(content, character_name)
            if not profile_data:
                raise ValueError("Không thể parse hồ sơ từ file!")
            
            profile = CharacterProfile()
            profile.name = character_name
            
            # Cập nhật từ profile_data
            if "A" in profile_data:
                part_a = profile_data["A"]
                profile.age = part_a.get("age", "")
                profile.gender = part_a.get("gender", "")
                profile.role = part_a.get("role", "")
            
            if "B" in profile_data:
                part_b = profile_data["B"]
                profile.appearance = part_b.get("appearance", "")
                profile.clothing = part_b.get("clothing", "")
                profile.distinctive_features = part_b.get("distinctive_features", "")
            
            if "C" in profile_data:
                part_c = profile_data["C"]
                profile.voice_description = part_c.get("voice_description", "")
                profile.speech_style = part_c.get("speech_style", "")
                profile.language = part_c.get("language", "")
            
            if "D" in profile_data:
                part_d = profile_data["D"]
                profile.behavior = part_d.get("behavior", "")
                profile.gestures = part_d.get("gestures", "")
                profile.movement_style = part_d.get("movement_style", "")
            
            if "E" in profile_data:
                part_e = profile_data["E"]
                profile.personality = part_e.get("personality", "")
                profile.emotions = part_e.get("emotions", "")
                profile.motivations = part_e.get("motivations", "")
            
            if "F" in profile_data:
                part_f = profile_data["F"]
                profile.knowledge = part_f.get("knowledge", "")
                profile.skills = part_f.get("skills", "")
                profile.limitations = part_f.get("limitations", "")
            
            if "G" in profile_data:
                part_g = profile_data["G"]
                profile.background = part_g.get("background", "")
                profile.relationships = part_g.get("relationships", "")
                profile.context = part_g.get("context", "")
            
            if "H" in profile_data:
                part_h = profile_data["H"]
                profile.always_rules = part_h.get("always_rules", [])
                profile.never_rules = part_h.get("never_rules", [])
            
            return character_name, profile
    
    def _format_character_to_text(self, character_name: str, profile: CharacterProfile) -> str:
        """Format nhân vật thành text giống hoso.txt"""
        lines = [
            "═══════════════════════════════════════════════════════════════════════════════",
            f"                    BẢNG DỮ LIỆU NHÂN VẬT TỔNG THỂ",
            f"                              (Master Template)",
            "═══════════════════════════════════════════════════════════════════════════════",
            "",
            f"NHÂN VẬT: {character_name}",
            "",
            f"ID Nhân vật: {character_name.upper().replace(' ', '_')}",
            f"Vai trò: {profile.role or 'Chưa xác định'}",
            "",
            "───────────────────────────────────────────────────────────────────────────────",
            "PHẦN A: THÔNG TIN CƠ BẢN (Identity)",
            "───────────────────────────────────────────────────────────────────────────────",
            f"- Tên: {profile.name}",
            f"- Tuổi: {profile.age}",
            f"- Giới tính: {profile.gender}",
            f"- Chủng tộc: [Chưa có]",
            f"- Nghề nghiệp: [Chưa có]",
            f"- Nơi xuất thân: [Chưa có]",
            "",
            "───────────────────────────────────────────────────────────────────────────────",
            "PHẦN B: NGOẠI HÌNH (Visual Profile)",
            "───────────────────────────────────────────────────────────────────────────────",
            f"- Ngoại hình: {profile.appearance}",
            f"- Trang phục: {profile.clothing}",
            f"- Đặc điểm nổi bật: {profile.distinctive_features}",
            "",
            "───────────────────────────────────────────────────────────────────────────────",
            "PHẦN C: ÂM THANH & NGÔN NGỮ (Audio & Language Profile)",
            "───────────────────────────────────────────────────────────────────────────────",
            f"- Ngôn ngữ chính: {profile.language}",
            f"- Chất giọng: {profile.voice_description}",
            f"- Phong cách nói: {profile.speech_style}",
            "",
            "───────────────────────────────────────────────────────────────────────────────",
            "PHẦN D: HÀNH VI & CỬ CHỈ (Behavior & Movement Profile)",
            "───────────────────────────────────────────────────────────────────────────────",
            f"- Hành vi: {profile.behavior}",
            f"- Cử chỉ: {profile.gestures}",
            f"- Phong cách di chuyển: {profile.movement_style}",
            "",
            "───────────────────────────────────────────────────────────────────────────────",
            "PHẦN E: TÍNH CÁCH & NỘI TÂM (Personality & Psyche)",
            "───────────────────────────────────────────────────────────────────────────────",
            f"- Tính cách: {profile.personality}",
            f"- Cảm xúc: {profile.emotions}",
            f"- Động lực: {profile.motivations}",
            "",
            "───────────────────────────────────────────────────────────────────────────────",
            "PHẦN F: KIẾN THỨC & KỸ NĂNG (Knowledge & Skills)",
            "───────────────────────────────────────────────────────────────────────────────",
            f"- Kiến thức: {profile.knowledge}",
            f"- Kỹ năng: {profile.skills}",
            f"- Hạn chế: {profile.limitations}",
            "",
            "───────────────────────────────────────────────────────────────────────────────",
            "PHẦN G: BỐI CẢNH & QUAN HỆ (Backstory & Relations)",
            "───────────────────────────────────────────────────────────────────────────────",
            f"- Bối cảnh: {profile.background}",
            f"- Quan hệ: {profile.relationships}",
            f"- Ngữ cảnh: {profile.context}",
            "",
            "───────────────────────────────────────────────────────────────────────────────",
            "PHẦN H: QUY TẮC ĐỒNG BỘ CỐT LÕI (Core Sync Rules)",
            "───────────────────────────────────────────────────────────────────────────────",
            "- Luôn luôn:",
        ]
        
        for rule in profile.always_rules:
            lines.append(f"  * {rule}")
        
        lines.append("")
        lines.append("- Không bao giờ:")
        for rule in profile.never_rules:
            lines.append(f"  * {rule}")
        
        lines.append("")
        lines.append("═══════════════════════════════════════════════════════════════════════════════")
        
        return "\n".join(lines)
    
    def get_characters_directory(self) -> Path:
        """Lấy đường dẫn thư mục characters/"""
        return Path("characters")
    
    def list_saved_characters(self) -> List[str]:
        """Liệt kê các nhân vật đã lưu trong thư mục characters/"""
        chars_dir = self.get_characters_directory()
        if not chars_dir.exists():
            return []
        
        character_files = []
        for file_path in chars_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    char_name = data.get("character_name", file_path.stem)
                    character_files.append(char_name)
            except:
                pass
        
        # Cũng tìm file .txt
        for file_path in chars_dir.glob("*.txt"):
            character_files.append(file_path.stem)
        
        return sorted(set(character_files))

