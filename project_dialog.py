#!/usr/bin/env python3
"""
Project Dialog - UI quản lý projects
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import ttkbootstrap as tb
from typing import Optional, Callable
from project_manager import ProjectManager

class ProjectDialog:
    def __init__(self, parent, project_manager: ProjectManager, on_project_selected: Optional[Callable] = None):
        self.parent = parent
        self.project_manager = project_manager
        self.on_project_selected = on_project_selected
        self.selected_project = None
        
        print(f"🔧 ProjectDialog created with project_manager: {id(project_manager)}")
        print(f"🔧 Projects file: {project_manager.projects_file}")
        print(f"🔧 Current projects in memory: {len(project_manager.projects)}")
        
        # Tạo dialog
        self.dialog = tb.Toplevel(parent)
        self.dialog.title("📁 Quản lý Projects")
        self.dialog.geometry("800x600")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center dialog
        self._center_dialog()
        
        self._create_ui()
        self._refresh_project_list()
    
    def _center_dialog(self):
        """Center dialog trên màn hình"""
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (800 // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (600 // 2)
        self.dialog.geometry(f"800x600+{x}+{y}")
    
    def _create_ui(self):
        """Tạo UI"""
        # Main frame
        main_frame = tb.Frame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Header
        header_frame = tb.Frame(main_frame)
        header_frame.pack(fill="x", pady=(0, 10))
        
        tb.Label(header_frame, text="📁 Quản lý Projects", font=("Arial", 16, "bold")).pack(side="left")
        
        # Buttons frame
        btn_frame = tb.Frame(header_frame)
        btn_frame.pack(side="right")
        
        tb.Button(btn_frame, text="🆕 Tạo mới", bootstyle="success", 
                 command=self._create_new_project, width=10).pack(side="left", padx=2)
        tb.Button(btn_frame, text="📥 Import", bootstyle="info", 
                 command=self._import_project, width=10).pack(side="left", padx=2)
        
        # Projects list frame
        list_frame = tb.Labelframe(main_frame, text="📋 Danh sách Projects", padding=10)
        list_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Treeview for projects
        columns = ("name", "description", "created", "stats")
        self.tree = tb.Treeview(list_frame, columns=columns, show="headings", height=12)
        
        # Configure columns
        self.tree.heading("name", text="Tên Project")
        self.tree.heading("description", text="Mô tả")
        self.tree.heading("created", text="Ngày tạo")
        self.tree.heading("stats", text="Thống kê")
        
        self.tree.column("name", width=200)
        self.tree.column("description", width=250)
        self.tree.column("created", width=120)
        self.tree.column("stats", width=150)
        
        # Scrollbar
        scrollbar = tb.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Bind selection
        self.tree.bind("<<TreeviewSelect>>", self._on_project_select)
        self.tree.bind("<Double-1>", self._on_project_double_click)
        
        # Action buttons
        action_frame = tb.Frame(main_frame)
        action_frame.pack(fill="x", pady=(0, 10))
        
        tb.Button(action_frame, text="✏️ Chỉnh sửa", bootstyle="warning", 
                 command=self._edit_project, state="disabled", width=12).pack(side="left", padx=2)
        tb.Button(action_frame, text="📤 Export", bootstyle="info", 
                 command=self._export_project, state="disabled", width=12).pack(side="left", padx=2)
        tb.Button(action_frame, text="🗑️ Xóa", bootstyle="danger", 
                 command=self._delete_project, state="disabled", width=12).pack(side="left", padx=2)
        
        # Store button references for state management
        self.edit_btn = action_frame.winfo_children()[0]
        self.export_btn = action_frame.winfo_children()[1]
        self.delete_btn = action_frame.winfo_children()[2]
        
        # Bottom buttons
        bottom_frame = tb.Frame(main_frame)
        bottom_frame.pack(fill="x")
        
        tb.Button(bottom_frame, text="✅ Chọn Project", bootstyle="success", 
                 command=self._select_project, state="disabled", width=15).pack(side="right", padx=2)
        tb.Button(bottom_frame, text="❌ Đóng", bootstyle="secondary", 
                 command=self._close_dialog, width=10).pack(side="right", padx=2)
        
        self.select_btn = bottom_frame.winfo_children()[1]
    
    def _refresh_project_list(self):
        """Refresh danh sách projects"""
        print(f"🔄 _refresh_project_list called")
        
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        print(f"🔄 Cleared existing items from tree")
        
        # Add projects
        try:
            # Use get_all_projects directly instead of get_project_list
            all_projects = self.project_manager.get_all_projects()
            print(f"🔄 get_all_projects() returned {len(all_projects)} projects")
            
            # Convert to list format
            projects = []
            for project_id, data in all_projects.items():
                try:
                    projects.append({
                        "id": project_id,
                        "name": data.get("name", "Unknown"),
                        "description": data.get("description", ""),
                        "created_at": data.get("created_at", data.get("updated_at", "")),
                        "updated_at": data.get("updated_at", ""),
                        "stats": data.get("stats", {"total_videos": 0, "completed_videos": 0, "failed_videos": 0})
                    })
                except Exception as e:
                    print(f"❌ Error converting project {project_id}: {e}")
            
            print(f"🔄 Refreshing project list: Found {len(projects)} projects")
            
            if not projects:
                print(f"❌ No projects found after conversion")
                return
            
            for i, project in enumerate(projects):
                try:
                    created_date = project["created_at"][:10] if project["created_at"] else ""
                    stats = f"Videos: {project['stats']['completed_videos']}/{project['stats']['total_videos']}"
                    
                    self.tree.insert("", "end", iid=project["id"], values=(
                        project["name"],
                        project["description"][:50] + "..." if len(project["description"]) > 50 else project["description"],
                        created_date,
                        stats
                    ))
                    print(f"  ✅ Added project {i+1}: {project['name']} (ID: {project['id']})")
                except Exception as e:
                    print(f"  ❌ Error adding project {i+1}: {e}")
                    print(f"  📋 Project data: {project}")
                    
        except Exception as e:
            print(f"❌ Error in _refresh_project_list: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_project_select(self, event):
        """Khi chọn project"""
        selection = self.tree.selection()
        if selection:
            self.selected_project = selection[0]
            # Enable buttons
            self.edit_btn.config(state="normal")
            self.export_btn.config(state="normal")
            self.delete_btn.config(state="normal")
            self.select_btn.config(state="normal")
        else:
            self.selected_project = None
            # Disable buttons
            self.edit_btn.config(state="disabled")
            self.export_btn.config(state="disabled")
            self.delete_btn.config(state="disabled")
            self.select_btn.config(state="disabled")
    
    def _on_project_double_click(self, event):
        """Double click để chọn project"""
        self._select_project()
    
    def _create_new_project(self):
        """Tạo project mới"""
        def on_project_created():
            print(f"🔄 Project created, refreshing list...")
            self._refresh_project_list()
            
        dialog = NewProjectDialog(self.dialog, self.project_manager, on_project_created)
        # Wait for dialog to close
        if hasattr(dialog.dialog, 'wait_window'):
            dialog.dialog.wait_window()
        if dialog.result:
            self._refresh_project_list()
    
    def _edit_project(self):
        """Chỉnh sửa project"""
        if not self.selected_project:
            return
        
        project = self.project_manager.get_project(self.selected_project)
        if project:
            dialog = EditProjectDialog(self.dialog, self.project_manager, project)
            # Wait for dialog to close
            if hasattr(dialog.dialog, 'wait_window'):
                dialog.dialog.wait_window()
            if dialog.result:
                self._refresh_project_list()
    
    def _export_project(self):
        """Export project"""
        if not self.selected_project:
            return
        
        project = self.project_manager.get_project(self.selected_project)
        if not project:
            return
        
        filename = filedialog.asksaveasfilename(
            title="Export Project",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            if self.project_manager.export_project(self.selected_project, filename):
                messagebox.showinfo("Thành công", f"Đã export project '{project['name']}' thành công!")
            else:
                messagebox.showerror("Lỗi", "Không thể export project!")
    
    def _import_project(self):
        """Import project"""
        filename = filedialog.askopenfilename(
            title="Import Project",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            project_id = self.project_manager.import_project(filename)
            if project_id:
                messagebox.showinfo("Thành công", "Đã import project thành công!")
                self._refresh_project_list()
            else:
                messagebox.showerror("Lỗi", "Không thể import project!")
    
    def _delete_project(self):
        """Xóa project"""
        if not self.selected_project:
            return
        
        project = self.project_manager.get_project(self.selected_project)
        if not project:
            return
        
        result = messagebox.askyesno(
            "Xác nhận xóa",
            f"Bạn có chắc muốn xóa project '{project['name']}'?\n\nHành động này không thể hoàn tác!"
        )
        
        if result:
            if self.project_manager.delete_project(self.selected_project):
                messagebox.showinfo("Thành công", "Đã xóa project thành công!")
                self._refresh_project_list()
            else:
                messagebox.showerror("Lỗi", "Không thể xóa project!")
    
    def _select_project(self):
        """Chọn project"""
        if self.selected_project and self.on_project_selected:
            project = self.project_manager.get_project(self.selected_project)
            if project:
                self.on_project_selected(project)
                self._close_dialog()
    
    def _close_dialog(self):
        """Đóng dialog"""
        self.dialog.destroy()


class NewProjectDialog:
    def __init__(self, parent, project_manager: ProjectManager, on_created_callback=None):
        self.project_manager = project_manager
        self.result = None
        self.on_created_callback = on_created_callback
        
        print(f"🔧 NewProjectDialog created with project_manager: {id(project_manager)}")
        print(f"🔧 Projects file: {project_manager.projects_file}")
        print(f"🔧 Current projects in memory: {len(project_manager.projects)}")
        
        # Tạo dialog
        self.dialog = tb.Toplevel(parent)
        self.dialog.title("🆕 Tạo Project Mới")
        self.dialog.geometry("500x400")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self._create_ui()
    
    def _create_ui(self):
        """Tạo UI"""
        main_frame = tb.Frame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        tb.Label(main_frame, text="🆕 Tạo Project Mới", font=("Arial", 14, "bold")).pack(pady=(0, 20))
        
        # Form frame
        form_frame = tb.Frame(main_frame)
        form_frame.pack(fill="both", expand=True)
        
        # Project name
        tb.Label(form_frame, text="Tên Project *:").pack(anchor="w", pady=(0, 5))
        self.name_entry = tb.Entry(form_frame, width=50)
        self.name_entry.pack(fill="x", pady=(0, 15))
        
        # Description
        tb.Label(form_frame, text="Mô tả:").pack(anchor="w", pady=(0, 5))
        self.desc_text = tb.Text(form_frame, height=4, width=50)
        self.desc_text.pack(fill="x", pady=(0, 15))
        
        # Cookie
        tb.Label(form_frame, text="Cookie (tùy chọn):").pack(anchor="w", pady=(0, 5))
        self.cookie_text = tb.Text(form_frame, height=3, width=50)
        self.cookie_text.pack(fill="x", pady=(0, 20))
        
        # Buttons
        btn_frame = tb.Frame(main_frame)
        btn_frame.pack(fill="x")
        
        tb.Button(btn_frame, text="✅ Tạo", bootstyle="success", 
                 command=self._create_project, width=10).pack(side="right", padx=2)
        tb.Button(btn_frame, text="❌ Hủy", bootstyle="secondary", 
                 command=self._cancel, width=10).pack(side="right", padx=2)
    
    def _create_project(self):
        """Tạo project"""
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showerror("Lỗi", "Vui lòng nhập tên project!")
            return
        
        description = self.desc_text.get("1.0", "end").strip()
        cookie = self.cookie_text.get("1.0", "end").strip()
        
        project_id = self.project_manager.create_project(name, description, cookie)
        if project_id:
            self.result = project_id
            print(f"✅ Created project: {name} (ID: {project_id})")
            messagebox.showinfo("Thành công", f"Đã tạo project '{name}' thành công!")
            
            # Call callback if provided
            if self.on_created_callback:
                print(f"🔄 Calling on_created_callback...")
                try:
                    self.on_created_callback()
                except Exception as e:
                    print(f"❌ Error in callback: {e}")
            
            self.dialog.destroy()
        else:
            print(f"❌ Failed to create project: {name}")
            messagebox.showerror("Lỗi", "Không thể tạo project!")
    
    def _cancel(self):
        """Hủy"""
        self.dialog.destroy()


class EditProjectDialog:
    def __init__(self, parent, project_manager: ProjectManager, project: dict):
        self.project_manager = project_manager
        self.project = project
        self.result = None
        
        # Tạo dialog
        self.dialog = tb.Toplevel(parent)
        self.dialog.title("✏️ Chỉnh sửa Project")
        self.dialog.geometry("500x400")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self._create_ui()
    
    def _create_ui(self):
        """Tạo UI"""
        main_frame = tb.Frame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        tb.Label(main_frame, text="✏️ Chỉnh sửa Project", font=("Arial", 14, "bold")).pack(pady=(0, 20))
        
        # Form frame
        form_frame = tb.Frame(main_frame)
        form_frame.pack(fill="both", expand=True)
        
        # Project name
        tb.Label(form_frame, text="Tên Project *:").pack(anchor="w", pady=(0, 5))
        self.name_entry = tb.Entry(form_frame, width=50)
        self.name_entry.insert(0, self.project["name"])
        self.name_entry.pack(fill="x", pady=(0, 15))
        
        # Description
        tb.Label(form_frame, text="Mô tả:").pack(anchor="w", pady=(0, 5))
        self.desc_text = tb.Text(form_frame, height=4, width=50)
        self.desc_text.insert("1.0", self.project["description"])
        self.desc_text.pack(fill="x", pady=(0, 15))
        
        # Cookie
        tb.Label(form_frame, text="Cookie:").pack(anchor="w", pady=(0, 5))
        self.cookie_text = tb.Text(form_frame, height=3, width=50)
        self.cookie_text.insert("1.0", self.project["cookie"])
        self.cookie_text.pack(fill="x", pady=(0, 20))
        
        # Buttons
        btn_frame = tb.Frame(main_frame)
        btn_frame.pack(fill="x")
        
        tb.Button(btn_frame, text="✅ Lưu", bootstyle="success", 
                 command=self._save_project, width=10).pack(side="right", padx=2)
        tb.Button(btn_frame, text="❌ Hủy", bootstyle="secondary", 
                 command=self._cancel, width=10).pack(side="right", padx=2)
    
    def _save_project(self):
        """Lưu project"""
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showerror("Lỗi", "Vui lòng nhập tên project!")
            return
        
        description = self.desc_text.get("1.0", "end").strip()
        cookie = self.cookie_text.get("1.0", "end").strip()
        
        if self.project_manager.update_project(self.project["id"], 
                                             name=name, 
                                             description=description, 
                                             cookie=cookie):
            self.result = True
            messagebox.showinfo("Thành công", f"Đã cập nhật project '{name}' thành công!")
            self.dialog.destroy()
        else:
            messagebox.showerror("Lỗi", "Không thể cập nhật project!")
    
    def _cancel(self):
        """Hủy"""
        self.dialog.destroy()
