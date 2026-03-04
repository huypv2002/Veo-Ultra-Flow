#!/usr/bin/env python3
"""
Project Manager - Quản lý dự án với cookie riêng cho từng project
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import uuid

class ProjectManager:
    def __init__(self, projects_dir: str = "projects"):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(exist_ok=True)
        self.projects_file = self.projects_dir / "projects.json"
        self.current_project = None
        self.projects = self._load_projects()
    
    def _load_projects(self) -> Dict:
        """Load danh sách projects từ file"""
        try:
            if self.projects_file.exists():
                print(f"📂 Loading projects from {self.projects_file}")
                with open(self.projects_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"📂 Loaded {len(data)} projects from file")
                    return data
            else:
                print(f"📂 Projects file does not exist: {self.projects_file}")
            return {}
        except Exception as e:
            print(f"❌ Lỗi load projects: {e}")
            return {}
    
    def _save_projects(self) -> None:
        """Save danh sách projects vào file"""
        try:
            print(f"💾 Saving {len(self.projects)} projects to {self.projects_file}")
            with open(self.projects_file, 'w', encoding='utf-8') as f:
                json.dump(self.projects, f, indent=2, ensure_ascii=False)
            print(f"✅ Successfully saved projects to file")
        except Exception as e:
            print(f"❌ Lỗi save projects: {e}")
    
    def create_project(self, name: str, description: str = "", cookie: str = "") -> str:
        """Tạo project mới"""
        project_id = str(uuid.uuid4())[:8]
        project_data = {
            "id": project_id,
            "name": name,
            "description": description,
            "cookie": cookie,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "settings": {
                "style": "3D Pixel",
                "total_seconds": "40",
                "seed": "",
                "gemini_keys": "",
                "output_dir": "",
                "image_model": "IMAGEN_3_5",
                "video_model": "veo_3_1_t2v",
                "aspect_ratio": "16:9"
            },
            "stats": {
                "total_videos": 0,
                "completed_videos": 0,
                "failed_videos": 0
            }
        }
        
        print(f"🔧 Before create: {len(self.projects)} projects in memory")
        self.projects[project_id] = project_data
        print(f"🔧 After create: {len(self.projects)} projects in memory")
        self._save_projects()
        print(f"🔧 Saved to file: {self.projects_file}")
        return project_id
    
    def update_project(self, project_id: str, **kwargs) -> bool:
        """Cập nhật project"""
        if project_id not in self.projects:
            return False
        
        for key, value in kwargs.items():
            if key in ["name", "description", "cookie"]:
                self.projects[project_id][key] = value
            elif key == "settings":
                self.projects[project_id]["settings"].update(value)
            elif key == "stats":
                self.projects[project_id]["stats"].update(value)
        
        self.projects[project_id]["updated_at"] = datetime.now().isoformat()
        self._save_projects()
        return True
    
    def delete_project(self, project_id: str) -> bool:
        """Xóa project"""
        if project_id in self.projects:
            # Xóa folder project nếu tồn tại
            project_folder = self.projects_dir / project_id
            if project_folder.exists():
                import shutil
                shutil.rmtree(project_folder)
            
            del self.projects[project_id]
            self._save_projects()
            return True
        return False
    
    def get_project(self, project_id: str) -> Optional[Dict]:
        """Lấy thông tin project"""
        return self.projects.get(project_id)
    
    def get_all_projects(self) -> Dict:
        """Lấy tất cả projects"""
        return self.projects
    
    def get_project_list(self) -> List[Dict]:
        """Lấy danh sách projects cho combobox"""
        print(f"🔍 get_project_list: {len(self.projects)} projects in memory")
        print(f"🔍 Projects file: {self.projects_file}")
        print(f"🔍 File exists: {self.projects_file.exists()}")
        
        # Reload from file to ensure we have latest data
        self.projects = self._load_projects()
        print(f"🔍 After reload: {len(self.projects)} projects in memory")
        
        projects = []
        for project_id, data in self.projects.items():
            try:
                print(f"🔍 Processing project {project_id}: {data.get('name', 'NO_NAME')}")
                projects.append({
                    "id": project_id,
                    "name": data["name"],
                    "description": data["description"],
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "stats": data["stats"]
                })
                print(f"🔍 ✅ Added project {project_id} to list")
            except Exception as e:
                print(f"🔍 ❌ Error processing project {project_id}: {e}")
                print(f"🔍 📋 Project data: {data}")
        
        # Sắp xếp theo thời gian cập nhật mới nhất
        try:
            projects.sort(key=lambda x: x["updated_at"], reverse=True)
            print(f"🔍 ✅ Sorted {len(projects)} projects")
        except Exception as e:
            print(f"🔍 ❌ Error sorting projects: {e}")
            print(f"🔍 📋 Sample project: {projects[0] if projects else 'No projects'}")
        
        print(f"🔍 Returning {len(projects)} projects")
        return projects
    
    def set_current_project(self, project_id: str) -> bool:
        """Set project hiện tại"""
        if project_id in self.projects:
            self.current_project = project_id
            return True
        return False
    
    def get_current_project(self) -> Optional[Dict]:
        """Lấy project hiện tại"""
        if self.current_project and self.current_project in self.projects:
            return self.projects[self.current_project]
        return None
    
    def export_project(self, project_id: str, export_path: str) -> bool:
        """Export project ra file"""
        try:
            project = self.get_project(project_id)
            if not project:
                return False
            
            # Tạo file export
            export_data = {
                "project": project,
                "exported_at": datetime.now().isoformat(),
                "version": "1.0"
            }
            
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            print(f"Lỗi export project: {e}")
            return False
    
    def import_project(self, import_path: str) -> Optional[str]:
        """Import project từ file"""
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            project = import_data.get("project")
            if not project:
                return None
            
            # Tạo project mới với ID mới
            project_id = str(uuid.uuid4())[:8]
            project["id"] = project_id
            project["created_at"] = datetime.now().isoformat()
            project["updated_at"] = datetime.now().isoformat()
            
            self.projects[project_id] = project
            self._save_projects()
            
            return project_id
        except Exception as e:
            print(f"Lỗi import project: {e}")
            return None
    
    def get_project_folder(self, project_id: str) -> Path:
        """Lấy folder project"""
        return self.projects_dir / project_id
    
    def ensure_project_folder(self, project_id: str) -> Path:
        """Đảm bảo folder project tồn tại"""
        folder = self.get_project_folder(project_id)
        folder.mkdir(parents=True, exist_ok=True)
        return folder
