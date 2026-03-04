"""
Character Profile Parser - Parser hồ sơ nhân vật từ format hoso.txt
"""

import re
from typing import Dict, Any, Optional
from story_script_manager import CharacterProfile


def parse_character_profile_from_text(text: str, character_name: str = "") -> Dict[str, Any]:
    """
    Parse hồ sơ nhân vật từ văn bản theo format hoso.txt
    
    Format mẫu:
    Phần A: Thông tin Cơ bản
    - Tên: ...
    - Tuổi: ...
    - Giới tính: ...
    - Vai trò: ...
    
    Phần B: Ngoại hình
    - Ngoại hình: ...
    - Trang phục: ...
    - Đặc điểm: ...
    ...
    """
    profile_data = {}
    
    # Tìm các phần
    parts = {
        "A": r"Phần\s*A[:\s]+Thông tin\s+Cơ\s+bản(.*?)(?=Phần\s*B|$)",
        "B": r"Phần\s*B[:\s]+Ngoại\s+hình(.*?)(?=Phần\s*C|$)",
        "C": r"Phần\s*C[:\s]+Âm\s+thanh[:\s&]*Ngôn\s+ngữ(.*?)(?=Phần\s*D|$)",
        "D": r"Phần\s*D[:\s]+Hành\s+vi[:\s&]*Cử\s+chỉ(.*?)(?=Phần\s*E|$)",
        "E": r"Phần\s*E[:\s]+Tính\s+cách[:\s&]*Nội\s+tâm(.*?)(?=Phần\s*F|$)",
        "F": r"Phần\s*F[:\s]+Kiến\s+thức[:\s&]*Kỹ\s+năng(.*?)(?=Phần\s*G|$)",
        "G": r"Phần\s*G[:\s]+Bối\s+cảnh[:\s&]*Quan\s+hệ(.*?)(?=Phần\s*H|$)",
        "H": r"Phần\s*H[:\s]+Quy\s+tắc[:\s]+Đồng\s+bộ(.*?)$"
    }
    
    for part_key, pattern in parts.items():
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            part_text = match.group(1).strip()
            profile_data[part_key] = parse_part_content(part_key, part_text)
    
    return profile_data


def parse_part_content(part_key: str, text: str) -> Dict[str, Any]:
    """Parse nội dung của một phần"""
    result = {}
    
    if part_key == "A":
        # Phần A: Thông tin Cơ bản
        result["age"] = extract_field(text, ["Tuổi", "Age"])
        result["gender"] = extract_field(text, ["Giới tính", "Gender"])
        result["role"] = extract_field(text, ["Vai trò", "Role", "Vai tro"])
    
    elif part_key == "B":
        # Phần B: Ngoại hình
        result["appearance"] = extract_field(text, ["Ngoại hình", "Appearance", "Ngoai hinh"])
        result["clothing"] = extract_field(text, ["Trang phục", "Clothing", "Trang phuc"])
        result["distinctive_features"] = extract_field(text, ["Đặc điểm", "Distinctive", "Dac diem"])
    
    elif part_key == "C":
        # Phần C: Âm thanh & Ngôn ngữ
        result["voice_description"] = extract_field(text, ["Giọng nói", "Voice", "Giong noi"])
        result["speech_style"] = extract_field(text, ["Phong cách", "Speech style", "Phong cach"])
        result["language"] = extract_field(text, ["Ngôn ngữ", "Language", "Ngon ngu"])
    
    elif part_key == "D":
        # Phần D: Hành vi & Cử chỉ
        result["behavior"] = extract_field(text, ["Hành vi", "Behavior", "Hanh vi"])
        result["gestures"] = extract_field(text, ["Cử chỉ", "Gestures", "Cu chi"])
        result["movement_style"] = extract_field(text, ["Phong cách di chuyển", "Movement", "Phong cach di chuyen"])
    
    elif part_key == "E":
        # Phần E: Tính cách & Nội tâm
        result["personality"] = extract_field(text, ["Tính cách", "Personality", "Tinh cach"])
        result["emotions"] = extract_field(text, ["Cảm xúc", "Emotions", "Cam xuc"])
        result["motivations"] = extract_field(text, ["Động lực", "Motivations", "Dong luc"])
    
    elif part_key == "F":
        # Phần F: Kiến thức & Kỹ năng
        result["knowledge"] = extract_field(text, ["Kiến thức", "Knowledge", "Kien thuc"])
        result["skills"] = extract_field(text, ["Kỹ năng", "Skills", "Ky nang"])
        result["limitations"] = extract_field(text, ["Hạn chế", "Limitations", "Han che", "Không biết", "Khong biet"])
    
    elif part_key == "G":
        # Phần G: Bối cảnh & Quan hệ
        result["background"] = extract_field(text, ["Bối cảnh", "Background", "Boi canh"])
        result["relationships"] = extract_field(text, ["Quan hệ", "Relationships", "Quan he"])
        result["context"] = extract_field(text, ["Ngữ cảnh", "Context", "Ngu canh"])
    
    elif part_key == "H":
        # Phần H: Quy tắc Đồng bộ
        always_text = extract_field(text, ["Luôn luôn", "Always", "Luon luon"])
        never_text = extract_field(text, ["Không bao giờ", "Never", "Khong bao gio"])
        
        result["always_rules"] = split_rules(always_text)
        result["never_rules"] = split_rules(never_text)
    
    return result


def extract_field(text: str, keywords: list) -> str:
    """Trích xuất giá trị của một trường từ văn bản"""
    for keyword in keywords:
        # Tìm pattern: "Keyword: value" hoặc "Keyword - value"
        patterns = [
            rf"{re.escape(keyword)}[:\-]\s*(.+?)(?=\n|$)",
            rf"{re.escape(keyword)}[:\-]\s*(.+?)(?=\n[A-Z]|$)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                value = match.group(1).strip()
                # Loại bỏ dấu "-" đầu dòng nếu có
                value = re.sub(r'^-\s*', '', value)
                return value
    
    return ""


def split_rules(text: str) -> list:
    """Chia văn bản quy tắc thành danh sách"""
    if not text:
        return []
    
    # Chia theo dấu phẩy, chấm phẩy, hoặc xuống dòng
    rules = re.split(r'[;,\n]', text)
    rules = [r.strip() for r in rules if r.strip()]
    return rules


def parse_multiple_profiles(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse nhiều hồ sơ nhân vật từ một văn bản"""
    profiles = {}
    
    # Tìm các phần bắt đầu bằng tên nhân vật hoặc "Nhân vật"
    # Giả định mỗi hồ sơ được phân cách bằng dòng trống hoặc tiêu đề
    sections = re.split(r'\n\s*\n|^Nhân vật\s+\d+[:]', text, flags=re.MULTILINE)
    
    for section in sections:
        if not section.strip():
            continue
        
        # Tìm tên nhân vật (dòng đầu tiên hoặc sau "Nhân vật")
        name_match = re.search(r'^(?:Nhân vật\s+\d+[:]?\s*)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', section, re.MULTILINE)
        if name_match:
            char_name = name_match.group(1).strip()
            profile_data = parse_character_profile_from_text(section, char_name)
            if profile_data:
                profiles[char_name] = profile_data
    
    return profiles

