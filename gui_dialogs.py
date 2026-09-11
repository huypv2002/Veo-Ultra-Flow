"""Dialog and helper widget classes extracted from gui_app_mac.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *



class ClickableLabel(QLabel):
    """Label có thể click để đổi tên nhân vật"""
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def format_plan_name(tier: Any) -> str:
    """Chuẩn hóa tên gói dịch vụ Google Flow (Ultra vs Pro)."""
    if not tier:
        return "Tự động nhận diện"
    t = str(tier).strip().upper()
    if "2" in t or "TWO" in t or "ULTRA" in t:
        return "⚡ Ultra (Tier 2)"
    elif "1" in t or "ONE" in t or "PRO" in t or "3" in t or "THREE" in t:
        return "🔷 Pro (Tier 1)"
    elif "0" in t or "FREE" in t or "NOT_PAID" in t:
        return "Standard / Free"
    return f"Tier {tier}"


class AccountManagerDialog(QDialog):
    """Dialog Quản Trị Tài Khoản Google Flow Ultra / Pro.
    Chỉ làm việc qua quét Chrome Profiles từ tiện ích Veo Flow Bridge.
    Tự động nhận diện Gmail, Gói Plan (Ultra/Pro), Số Credits và câng bằng tải giữa 2 Profile.
    """

    REQUIRED_COOKIE_NAMES = [
        "__Host-next-auth.csrf-token",
        "__Secure-next-auth.callback-url",
        "__Secure-next-auth.session-token",
    ]

    def __init__(
        self,
        parent_app,
        *,
        title: str = "Quản Trị Tài Khoản",
        header_text: str = "Quản Trị Tài Khoản (Google Flow Multi-Profile)",
        info_text: str = "",
        prefill_existing: bool = True,
    ):
        super().__init__(parent_app if isinstance(parent_app, QWidget) else None)
        self.parent_app = parent_app
        self.setWindowTitle("Quản Trị Tài Khoản Google Flow Ultra / Pro")
        self.setMinimumSize(1100, 640)
        self.resize(1180, 680)

        self.max_cookies_allowed, self.unlimited_cookies = self.parent_app._get_cookie_limit_for_dialog()

        # Danh sách tài khoản chuẩn hóa
        # Mỗi phần tử: {email, plan, credits, tier, status, source, note, cookie, client_id}
        self.accounts: List[Dict[str, Any]] = []

        # Backward-compatible cookie_blocks: [(cookie_str, label), ...]
        self.cookie_blocks: List[Tuple[str, str]] = []

        # Nạp dữ liệu tài khoản đã lưu
        if prefill_existing:
            self._load_initial_accounts()

        self._build_ui(header_text, info_text)
        self._setup_refresh_timer()
        self._refresh_grid()

        # Tự động quét profiles sau khi mở dialog
        QTimer.singleShot(150, self._scan_extension_profiles)

    def _load_initial_accounts(self) -> None:
        """Nạp dữ liệu tài khoản từ app và file cache .cookies_temp.json."""
        self.accounts = []
        saved_meta_map: Dict[str, Dict[str, Any]] = {}

        # Thử đọc metadata tài khoản đã lưu từ .cookies_temp.json
        try:
            cookie_file = self.parent_app._get_local_cookies_file_path()
            if os.path.exists(cookie_file):
                with open(cookie_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                saved_meta_list = cdata.get("account_metadata", [])
                for item in saved_meta_list:
                    ck = item.get("cookie", "").strip()
                    if ck:
                        saved_meta_map[self._get_cookie_hash(ck)] = item
                    em = item.get("email", "").strip()
                    if em:
                        saved_meta_map[em.lower()] = item
        except Exception:
            pass

        # Đọc metadata từ in-memory parent_app.account_metadata nếu có
        app_meta_list = list(getattr(self.parent_app, "account_metadata", []) or [])
        for item in app_meta_list:
            ck = item.get("cookie", "").strip()
            if ck:
                saved_meta_map[self._get_cookie_hash(ck)] = item
            em = item.get("email", "").strip()
            if em:
                saved_meta_map[em.lower()] = item

        # Nạp từ parent_app.cookies_list
        cookies_list = list(getattr(self.parent_app, "cookies_list", []) or [])
        labels_list = list(getattr(self.parent_app, "cookie_labels", []) or [])

        for idx, cookie_str in enumerate(cookies_list):
            label = labels_list[idx] if idx < len(labels_list) else ""
            chash = self._get_cookie_hash(cookie_str)
            meta = saved_meta_map.get(chash) or saved_meta_map.get(label.lower()) or {}

            email = meta.get("email") or label or f"Profile #{idx + 1}"
            tier = meta.get("tier") or "TIER_2"
            plan = format_plan_name(meta.get("plan") or tier)
            credits = meta.get("credits")
            status = meta.get("status") or "🟢 Live (Extension)"
            source = meta.get("source") or "🌐 Chrome Profile"
            note = meta.get("note") or ""

            acc = {
                "email": email,
                "plan": plan,
                "credits": credits,
                "tier": tier,
                "status": status,
                "source": source,
                "note": note,
                "cookie": cookie_str,
                "client_id": meta.get("client_id", ""),
            }
            self.accounts.append(acc)

        self._sync_cookie_blocks()

    def _sync_cookie_blocks(self) -> None:
        """Đồng bộ cookie_blocks tương thích ngược với các logic cũ."""
        self.cookie_blocks = []
        for acc in self.accounts:
            ck = acc.get("cookie", "")
            lb = acc.get("email", "")
            self.cookie_blocks.append((ck, lb))

    def _build_ui(self, header_text: str, info_text: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        shell = QFrame()
        shell.setStyleSheet("""
            QFrame#accountShell {
                background: #ffffff;
                border: 1px solid #d8e2f0;
                border-radius: 18px;
            }
        """)
        shell.setObjectName("accountShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(20, 20, 20, 20)
        shell_layout.setSpacing(14)
        layout.addWidget(shell)

        # ── Header Bar ──────────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        header = QLabel("👤 Quản Trị Tài Khoản (Google Flow Multi-Profile)")
        header.setStyleSheet("font-size: 22px; font-weight: 800; color: #0f172a;")
        title_col.addWidget(header)

        subtitle = QLabel(
            "Tự động quét và nhận diện tài khoản Google Flow từ các Profile Chrome đang mở. "
            "Hiển thị chính xác Gmail, Gói Plan (Ultra/Pro), Số Credits còn lại và cân bằng tải tự động."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #475569; font-size: 12px; line-height: 1.4;")
        title_col.addWidget(subtitle)
        top.addLayout(title_col, 1)

        # Badges góc phải
        badges_col = QVBoxLayout()
        badges_col.setSpacing(4)
        badges_col.setAlignment(Qt.AlignRight | Qt.AlignTop)

        b_row = QHBoxLayout()
        b_row.setSpacing(8)

        badge_multi = QLabel("⚡ Multi-Profile Ready")
        badge_multi.setAlignment(Qt.AlignCenter)
        badge_multi.setFixedHeight(30)
        badge_multi.setStyleSheet("""
            QLabel {
                padding: 0 12px;
                background: #ecfdf5;
                color: #047857;
                border: 1px solid #a7f3d0;
                border-radius: 15px;
                font-size: 11px;
                font-weight: 700;
            }
        """)
        b_row.addWidget(badge_multi)

        badge_port = QLabel("🌐 Bridge: 127.0.0.1:3003")
        badge_port.setAlignment(Qt.AlignCenter)
        badge_port.setFixedHeight(30)
        badge_port.setStyleSheet("""
            QLabel {
                padding: 0 12px;
                background: #eff6ff;
                color: #1d4ed8;
                border: 1px solid #bfdbfe;
                border-radius: 15px;
                font-size: 11px;
                font-weight: 700;
            }
        """)
        b_row.addWidget(badge_port)
        badges_col.addLayout(b_row)

        top.addLayout(badges_col)
        shell_layout.addLayout(top)

        # ── Banner Hướng Dẫn 2 Profile Chrome ────────────────────────
        guide_banner = QFrame()
        guide_banner.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f0fdf4, stop:1 #eff6ff);
                border: 1px solid #bbf7d0;
                border-radius: 12px;
                padding: 10px 14px;
            }
        """)
        guide_layout = QHBoxLayout(guide_banner)
        guide_layout.setContentsMargins(14, 10, 14, 10)
        guide_layout.setSpacing(12)

        guide_icon = QLabel("💡")
        guide_icon.setStyleSheet("font-size: 24px;")
        guide_layout.addWidget(guide_icon, 0, Qt.AlignVCenter)

        guide_text = QLabel(
            "<b>Hướng dẫn sử dụng nhiều Profile Chrome (Ultra & Pro):</b><br/>"
            "• Mở <b>Chrome Profile 1</b> (Tài khoản Ultra) và <b>Chrome Profile 2</b> (Tài khoản Pro / Ultra).<br/>"
            "• Đảm bảo tiện ích <b>Veo Flow Bridge</b> đã được BẬT ở cả 2 profile và đang mở tab <code>flow.google.com</code>.<br/>"
            "• Bấm nút <b>'🔄 Quét Extension Profiles'</b> (hoặc hệ thống tự quét khi mở). Hệ thống sẽ tự động cân bằng tải luân phiên giữa 2 profile khi tạo video!"
        )
        guide_text.setWordWrap(True)
        guide_text.setStyleSheet("color: #166534; font-size: 12px; line-height: 1.5;")
        guide_layout.addWidget(guide_text, 1)

        shell_layout.addWidget(guide_banner)

        # ── Bảng Danh Sách Tài Khoản (Chiếm Trọn Chiều Rộng) ─────────
        table_card = QFrame()
        table_card.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 16px;
            }
        """)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(16, 16, 16, 16)
        table_layout.setSpacing(12)

        # ── Toolbar trên bảng: Hàng 1 (Tiêu đề + Nút thao tác) ────────
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        card_title = QLabel("📋 Danh Sách Chrome Profile Đã Kết Nối")
        card_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #0f172a;")
        top_bar.addWidget(card_title, 1)

        # Nút Quét Extension Profiles
        self.btn_scan_extension = QPushButton("🔄 Quét Extension Profiles")
        self.btn_scan_extension.setToolTip("Quét tất cả Profile Chrome đang mở có gắn extension Veo Flow Bridge")
        self.btn_scan_extension.setStyleSheet("""
            QPushButton {
                background: #0284c7;
                color: white;
                font-weight: 700;
                padding: 9px 18px;
                border-radius: 8px;
                font-size: 13px;
            }
            QPushButton:hover { background: #0369a1; }
        """)
        self.btn_scan_extension.clicked.connect(self._scan_extension_profiles)
        top_bar.addWidget(self.btn_scan_extension)

        # Nút Làm Mới Credits
        self.btn_check_all_credits = QPushButton("⚡ Làm Mới Credits")
        self.btn_check_all_credits.setToolTip("Cập nhật lại số credits và gói plan mới nhất từ các Profile Chrome")
        self.btn_check_all_credits.setStyleSheet("""
            QPushButton {
                background: #7c3aed;
                color: white;
                font-weight: 700;
                padding: 9px 18px;
                border-radius: 8px;
                font-size: 13px;
            }
            QPushButton:hover { background: #6d28d9; }
        """)
        self.btn_check_all_credits.clicked.connect(self._scan_extension_profiles)
        top_bar.addWidget(self.btn_check_all_credits)

        # Nút Xóa dòng chọn
        self.btn_remove = QPushButton("🗑️ Xóa dòng chọn")
        self.btn_remove.setStyleSheet(self._secondary_button_style())
        self.btn_remove.clicked.connect(self._remove_selected)
        top_bar.addWidget(self.btn_remove)

        # Nút Xóa toàn bộ
        self.btn_clear_grid = QPushButton("🗑️ Xóa toàn bộ")
        self.btn_clear_grid.setStyleSheet(self._danger_button_style())
        self.btn_clear_grid.clicked.connect(self._clear_grid)
        top_bar.addWidget(self.btn_clear_grid)

        table_layout.addLayout(top_bar)

        # ── Hàng 2: Dãy Thẻ Thống Kê (Stat Badges) ────────────────────
        self.stats_bar = QHBoxLayout()
        self.stats_bar.setSpacing(8)

        self.chip_total = QLabel("👥 Tổng: 0 tài khoản")
        self.chip_total.setStyleSheet("padding: 5px 12px; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 12px; font-weight: 700; color: #334155; font-size: 12px;")
        self.stats_bar.addWidget(self.chip_total)

        self.chip_active = QLabel("🟢 0 Sẵn sàng")
        self.chip_active.setStyleSheet("padding: 5px 12px; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 12px; font-weight: 700; color: #047857; font-size: 12px;")
        self.stats_bar.addWidget(self.chip_active)

        self.chip_ultra = QLabel("⚡ 0 Ultra")
        self.chip_ultra.setStyleSheet("padding: 5px 12px; background: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 12px; font-weight: 700; color: #6d28d9; font-size: 12px;")
        self.stats_bar.addWidget(self.chip_ultra)

        self.chip_pro = QLabel("🔷 0 Pro")
        self.chip_pro.setStyleSheet("padding: 5px 12px; background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 12px; font-weight: 700; color: #0369a1; font-size: 12px;")
        self.stats_bar.addWidget(self.chip_pro)

        self.chip_credits = QLabel("💎 Tổng: 0 Credits")
        self.chip_credits.setStyleSheet("padding: 5px 12px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; font-weight: 700; color: #15803d; font-size: 12px;")
        self.stats_bar.addWidget(self.chip_credits)

        self.stats_bar.addStretch()
        table_layout.addLayout(self.stats_bar)

        # Bảng tài khoản (7 cột hiển thị rõ ràng, không bị che khuất)
        self.cookie_table = QTableWidget()
        self.cookie_table.setColumnCount(7)
        self.cookie_table.setHorizontalHeaderLabels([
            "#",
            "Gmail / Tên tài khoản",
            "Gói (Plan)",
            "Số Credits",
            "Trạng thái",
            "Nguồn",
            "Ghi chú",
        ])
        self.cookie_table.verticalHeader().setVisible(False)
        self.cookie_table.setAlternatingRowColors(True)
        self.cookie_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cookie_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.cookie_table.setShowGrid(False)
        self.cookie_table.setStyleSheet("""
            QTableWidget {
                background: #f8fafc;
                alternate-background-color: #f1f5f9;
                border: 1px solid #dbe3ef;
                border-radius: 12px;
                color: #0f172a;
                font-size: 13px;
            }
            QHeaderView::section {
                background: #e2e8f0;
                color: #1e293b;
                border: none;
                border-bottom: 1px solid #cbd5e1;
                padding: 10px 10px;
                font-weight: 700;
                font-size: 12px;
            }
        """)

        header_view = self.cookie_table.horizontalHeader()
        header_view.setMinimumSectionSize(50)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(6, QHeaderView.ResizeToContents)

        table_layout.addWidget(self.cookie_table, 1)
        shell_layout.addWidget(table_card, 1)

        # ── Footer ──────────────────────────────────────────────────
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 12px; color: #475569; font-weight: 500;")
        shell_layout.addWidget(self.status_label)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        footer.addStretch()

        btn_cancel = QPushButton("Đóng")
        btn_cancel.setStyleSheet(self._secondary_button_style())
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        self.btn_save = QPushButton("💾 Lưu & Áp Dụng Tài Khoản")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background: #16a34a;
                color: white;
                font-weight: 700;
                padding: 11px 26px;
                border-radius: 8px;
                font-size: 13px;
            }
            QPushButton:hover { background: #15803d; }
        """)
        self.btn_save.clicked.connect(self._save_cookies)
        footer.addWidget(self.btn_save)

        shell_layout.addLayout(footer)

    def _setup_refresh_timer(self) -> None:
        """Timer cập nhật trạng thái runtime."""
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(4000)
        self._refresh_timer.timeout.connect(self._sync_runtime_status)
        self._refresh_timer.start()

    def _sync_runtime_status(self) -> None:
        """Cập nhật trạng thái runtime nhẹ nhàng."""
        self._refresh_grid(soft_update=True)

    def _secondary_button_style(self) -> str:
        return (
            "QPushButton { background: #ffffff; color: #334155; border: 1px solid #cbd5e1; "
            "font-weight: 600; padding: 9px 15px; border-radius: 8px; font-size: 12px; }"
            "QPushButton:hover { background: #f8fafc; }"
        )

    def _danger_button_style(self) -> str:
        return (
            "QPushButton { background: #fff1f2; color: #be123c; border: 1px solid #fecdd3; "
            "font-weight: 700; padding: 9px 15px; border-radius: 8px; font-size: 12px; }"
            "QPushButton:hover { background: #ffe4e6; }"
        )

    def _get_cookie_hash(self, cookie_str: str) -> str:
        """Tạo hash SHA256 nhận diện cookie trùng lặp."""
        import hashlib
        normalized = cookie_str.strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # ── Refresh Grid ────────────────────────────────────────────────
    def _refresh_grid(self, soft_update: bool = False) -> None:
        self.cookie_table.blockSignals(True)
        selected_row = self.cookie_table.currentRow()

        self.cookie_table.setRowCount(0)
        total_accounts = len(self.accounts)
        active_count = 0
        ultra_count = 0
        pro_count = 0
        total_credits = 0

        for idx, acc in enumerate(self.accounts, 1):
            email = acc.get("email") or f"Profile #{idx}"
            tier = acc.get("tier") or "TIER_2"
            raw_plan = acc.get("plan")
            plan = format_plan_name(raw_plan or tier)
            acc["plan"] = plan
            credits = acc.get("credits")
            status = acc.get("status") or "🟢 Live (Extension)"
            source = acc.get("source") or "🌐 Chrome Profile"
            note = acc.get("note") or ""

            if "Live" in status or "Hoạt động" in status or "Sẵn sàng" in status:
                active_count += 1
            if "Ultra" in plan:
                ultra_count += 1
            elif "Pro" in plan:
                pro_count += 1
            if isinstance(credits, (int, float)):
                total_credits += int(credits)

            row = self.cookie_table.rowCount()
            self.cookie_table.insertRow(row)

            # Cột 0: STT
            c0 = QTableWidgetItem(str(idx))
            c0.setTextAlignment(Qt.AlignCenter)
            c0.setData(Qt.UserRole, acc)
            self.cookie_table.setItem(row, 0, c0)

            # Cột 1: Gmail / Tên tài khoản
            c1 = QTableWidgetItem(email)
            c1.setFont(QFont("SF Pro Text", 12, QFont.Bold))
            c1.setForeground(QColor("#0f172a"))
            self.cookie_table.setItem(row, 1, c1)

            # Cột 2: Gói (Plan)
            c2 = QTableWidgetItem(plan)
            c2.setTextAlignment(Qt.AlignCenter)
            if "Ultra" in plan:
                c2.setForeground(QColor("#7c3aed"))
                c2.setFont(QFont("SF Pro Text", 12, QFont.Bold))
            elif "Pro" in plan:
                c2.setForeground(QColor("#0284c7"))
                c2.setFont(QFont("SF Pro Text", 12, QFont.Bold))
            else:
                c2.setForeground(QColor("#64748b"))
                c2.setFont(QFont("SF Pro Text", 11))
            self.cookie_table.setItem(row, 2, c2)

            # Cột 3: Số Credits
            cred_str = f"{credits:,}" if isinstance(credits, (int, float)) else "--"
            c3 = QTableWidgetItem(cred_str)
            c3.setTextAlignment(Qt.AlignCenter)
            c3.setForeground(QColor("#16a34a"))
            c3.setFont(QFont("SF Pro Text", 13, QFont.Bold))
            self.cookie_table.setItem(row, 3, c3)

            # Cột 4: Trạng thái
            c4 = QTableWidgetItem(status)
            c4.setTextAlignment(Qt.AlignCenter)
            if "Live" in status or "Hoạt động" in status:
                c4.setForeground(QColor("#16a34a"))
            elif "Hết hạn" in status or "Lỗi" in status:
                c4.setForeground(QColor("#dc2626"))
            elif "Bị chặn" in status:
                c4.setForeground(QColor("#f59e0b"))
            else:
                c4.setForeground(QColor("#64748b"))
            self.cookie_table.setItem(row, 4, c4)

            # Cột 5: Nguồn
            c5 = QTableWidgetItem(source)
            c5.setTextAlignment(Qt.AlignCenter)
            c5.setForeground(QColor("#0284c7"))
            self.cookie_table.setItem(row, 5, c5)

            # Cột 6: Ghi chú
            c6 = QTableWidgetItem(note)
            c6.setForeground(QColor("#64748b"))
            self.cookie_table.setItem(row, 6, c6)

        # Khôi phục dòng chọn
        if 0 <= selected_row < self.cookie_table.rowCount():
            self.cookie_table.selectRow(selected_row)

        # Cập nhật các thẻ thống kê
        if hasattr(self, "chip_total"):
            self.chip_total.setText(f"👥 Tổng: {total_accounts} tài khoản")
            self.chip_active.setText(f"🟢 {active_count} Sẵn sàng")
            self.chip_ultra.setText(f"⚡ {ultra_count} Ultra")
            self.chip_pro.setText(f"🔷 {pro_count} Pro")
            self.chip_credits.setText(f"💎 Tổng: {total_credits:,} Credits")
        if not soft_update:
            self.status_label.setText(f"Đã tải {total_accounts} tài khoản Chrome Profile. Sẵn sàng tạo video.")

        self.cookie_table.blockSignals(False)
        self._sync_cookie_blocks()

    def _remove_selected(self) -> None:
        row = self.cookie_table.currentRow()
        if row < 0 or row >= len(self.accounts):
            return
        removed = self.accounts.pop(row)
        self._refresh_grid()
        self.status_label.setText(f"Đã xóa dòng: {removed.get('email', '')}")

    def _clear_grid(self) -> None:
        if not self.accounts:
            return
        reply = QMessageBox.question(
            self,
            "Xác nhận",
            "Bạn có chắc chắn muốn xóa toàn bộ danh sách tài khoản?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.accounts = []
            self._refresh_grid()
            self.status_label.setText("Đã xóa sạch bảng tài khoản.")

    # ── Quét Chrome Extension Profiles (127.0.0.1:3003/accounts) ──
    def _scan_extension_profiles(self) -> None:
        """Kết nối Bridge Server cổng 3003 để quét tất cả Profile Chrome đang mở."""
        self.status_label.setText("⏳ Đang quét Chrome Profiles qua Bridge Server...")
        QApplication.processEvents()

        try:
            import urllib.request
            url = "http://127.0.0.1:3003/accounts"
            req = urllib.request.Request(url, headers={"User-Agent": "VeoFlowManager/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP status {resp.status}")
                data = json.loads(resp.read().decode("utf-8"))

            if not data.get("ok"):
                raise RuntimeError("Server phản hồi không hợp lệ.")

            ext_accounts = data.get("accounts", [])
            if not ext_accounts:
                self.status_label.setText("⚠️ Chưa phát hiện Profile Chrome nào đang kết nối tới Bridge.")
                return

            synced_count = 0
            for ext in ext_accounts:
                cid = ext.get("client_id") or ""
                email = ext.get("email") or f"Profile ({cid})"
                credits = ext.get("credits")
                tier = ext.get("tier") or "TIER_2"
                plan = format_plan_name(ext.get("plan") or tier)
                cookie = ext.get("cookie") or ""
                access_token = ext.get("access_token") or ""
                source = ext.get("source") or f"🌐 Chrome Profile ({cid})"
                status = ext.get("status") or "🟢 Live (Extension)"

                # Nếu chưa có chuỗi cookie, tạo token định danh tương thích
                if not cookie:
                    cookie = f"__Secure-next-auth.session-token=ext_{cid}; client_id={cid}; email={email}"

                # Tìm xem tài khoản đã tồn tại trong danh sách chưa
                matched = False
                for existing in self.accounts:
                    if (existing.get("email") and existing["email"].lower() == email.lower()) or \
                       (cid and existing.get("client_id") == cid):
                        existing["credits"] = credits
                        existing["plan"] = plan
                        existing["tier"] = tier
                        existing["status"] = status
                        existing["source"] = source
                        existing["cookie"] = cookie
                        existing["client_id"] = cid
                        if access_token:
                            existing["access_token"] = access_token
                        matched = True
                        synced_count += 1
                        break

                if not matched:
                    self.accounts.append({
                        "email": email,
                        "plan": plan,
                        "credits": credits,
                        "tier": tier,
                        "status": status,
                        "source": source,
                        "note": f"Đồng bộ từ {cid}",
                        "cookie": cookie,
                        "client_id": cid,
                        "access_token": access_token,
                    })
                    synced_count += 1

            self._refresh_grid()
            ultra_cnt = sum(1 for a in self.accounts if "Ultra" in a.get("plan", ""))
            pro_cnt = sum(1 for a in self.accounts if "Pro" in a.get("plan", ""))
            self.status_label.setText(
                f"✅ Đã đồng bộ thành công {len(ext_accounts)} Profile Chrome "
                f"({ultra_cnt} Ultra, {pro_cnt} Pro) - Sẵn sàng tạo video với cân bằng tải luân phiên."
            )

        except Exception as e:
            err_str = str(e)
            if "Connection refused" in err_str or "Errno 61" in err_str:
                self.status_label.setText("ℹ️ Đang chờ Bridge Server cổng 3003 kết nối với Chrome Extension (Mở Flow trên Chrome để tự nhận diện).")
            else:
                self.status_label.setText(f"⚠️ Thông báo Bridge: {err_str}")

    # ── Lưu & Áp Dụng ──────────────────────────────────────────────
    def _save_cookies(self) -> None:
        """Lưu toàn bộ danh sách tài khoản và đồng bộ vào app."""
        try:
            cookie_list = []
            labels_list = []

            for acc in self.accounts:
                ck = acc.get("cookie", "").strip()
                if not ck:
                    cid = acc.get("client_id", "ext")
                    em = acc.get("email", "")
                    ck = f"__Secure-next-auth.session-token=ext_{cid}; client_id={cid}; email={em}"
                    acc["cookie"] = ck
                cookie_list.append(ck)
                labels_list.append(acc.get("email", ""))

            if not cookie_list:
                self.status_label.setText("⚠️ Chưa có tài khoản nào được đồng bộ!")
                QMessageBox.warning(self, "Chưa có tài khoản", "Vui lòng mở ít nhất 1 Profile Chrome có tiện ích để quét tài khoản.")
                return

            # Áp dụng danh sách cookies vào parent_app
            count = self.parent_app._apply_cookie_blocks(cookie_list)

            # Cập nhật labels và metadata
            if hasattr(self.parent_app, "cookie_labels"):
                self.parent_app.cookie_labels = labels_list
            self.parent_app.account_metadata = self.accounts

            # Lưu vào file .cookies_temp.json
            self._persist_accounts_metadata(cookie_list, labels_list)

            self.status_label.setText(f"✅ Đã lưu thành công {count} tài khoản!")
            self.parent_app.log(f"👤 [AccountManager] Đã cập nhật {count} tài khoản Google Flow (Ultra/Pro).")
            QMessageBox.information(
                self,
                "Đã lưu thành công",
                f"Đã lưu thành công {count} tài khoản Google Flow.\n"
                "Hệ thống đã sẵn sàng tạo video với cơ chế cân bằng tải tự động."
            )
            self.accept()

        except Exception as e:
            error_msg = str(e)
            self.status_label.setText(f"❌ Lỗi: {error_msg}")
            QMessageBox.warning(self, "Không thể lưu", f"Không thể lưu tài khoản.\n\n{error_msg}")

    def _persist_accounts_metadata(self, cookie_list: List[str], labels_list: List[str]) -> None:
        """Lưu metadata tài khoản vào file local để không bị mất khi mở lại app."""
        try:
            cookie_file = self.parent_app._get_local_cookies_file_path()
            data = {}
            if os.path.exists(cookie_file):
                with open(cookie_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

            data["cookies_list"] = cookie_list
            data["cookie_labels"] = labels_list
            data["account_metadata"] = self.accounts

            with open(cookie_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Không thể lưu account_metadata: {e}")

    def closeEvent(self, event):
        if hasattr(self, "_refresh_timer") and self._refresh_timer:
            self._refresh_timer.stop()
        super().closeEvent(event)


# Alias tương thích ngược hoàn toàn cho toàn bộ project
CookieManagerDialog = AccountManagerDialog



class MatchingEditDialog(QDialog):
    """Dialog chỉnh sửa matching results"""
    
    def __init__(self, parent_app, parent_dialog=None):
        super().__init__(parent_dialog)
        self.setWindowTitle("Chỉnh Sửa Matching Results")
        self.setModal(True)
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)
        
        self.parent_app = parent_app
        self.parent_dialog = parent_dialog
        
        self.init_ui()
        # Căn width dialog theo form chính (nếu có)
        try:
            if hasattr(self.parent_app, 'width'):
                w = int(self.parent_app.width())
                if w and w > 0:
                    self.resize(w, self.height())
                    self.setMinimumWidth(w)
        except Exception:
            pass
        self.load_data()
    
    def init_ui(self):
        """Khởi tạo UI theo layout 4 hàng"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(8)
        
        # Row 1: Slider ảnh (thumbnail sát nhau, cách 5px)
        self.row1_scroll = QScrollArea()
        self.row1_scroll.setWidgetResizable(True)
        self.row1_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.row1_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.row1_scroll_content = QWidget()
        self.row1_scroll_layout = QGridLayout(self.row1_scroll_content)
        self.row1_scroll_layout.setContentsMargins(8, 8, 8, 8)
        self.row1_scroll_layout.setHorizontalSpacing(12)
        self.row1_scroll_layout.setVerticalSpacing(12)
        self.row1_scroll_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.row1_scroll.setWidget(self.row1_scroll_content)
        main_layout.addWidget(self.row1_scroll)
        # Kích thước cột đồng nhất
        self._col_width = 150
        self._thumb_size = 64
        
        # Row 2: Tên nhân vật (tối đa 10)
        self.row2_names = QWidget()
        self.row2_names_layout = QHBoxLayout(self.row2_names)
        self.row2_names_layout.setContentsMargins(0, 0, 0, 0)
        self.row2_names_layout.setSpacing(5)
        self.row2_names.hide()
        main_layout.addWidget(self.row2_names)
        
        # Row 3: Label All + 10 checkbox nhỏ
        self.row3_all = QWidget()
        self.row3_all_layout = QHBoxLayout(self.row3_all)
        self.row3_all_layout.setContentsMargins(0, 0, 0, 0)
        self.row3_all_layout.setSpacing(10)
        self._all_label = QLabel("All:")
        self.row3_all_layout.addWidget(self._all_label)
        self.global_all_checkboxes = []  # will be created in load_data()
        self.row3_all.hide()
        main_layout.addWidget(self.row3_all)
        
        # Row 4+: các prompt, mỗi hàng chia đôi: trái = tích chọn ≤3, phải = prompt input
        self.prompts_container = QWidget()
        self.prompts_layout = QVBoxLayout(self.prompts_container)
        self.prompts_layout.setContentsMargins(0, 0, 0, 0)
        self.prompts_layout.setSpacing(8)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(self.prompts_container)
        main_layout.addWidget(scroll, 1)
        
        # Hàng nút
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_save = QPushButton("💾 Lưu")
        btn_save.setFixedSize(100, 35)
        btn_save.clicked.connect(self.accept)
        btn_layout.addWidget(btn_save)
        btn_cancel = QPushButton("Hủy")
        btn_cancel.setFixedSize(100, 35)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        main_layout.addLayout(btn_layout)
    
    def load_data(self):
        """Load data từ parent và hiển thị với ảnh nhân vật"""
        if not self.parent_app:
            return
        
        # Khởi tạo danh sách ảnh (tối đa 10)
        self.left_images = []  # List[dict]: {'name': str, 'path': str}
        try:
            if hasattr(self.parent_app, 'custom_characters') and isinstance(self.parent_app.custom_characters, dict):
                for name, path in self.parent_app.custom_characters.items():
                    if len(self.left_images) >= 10:
                        break
                    self.left_images.append({'name': str(name), 'path': str(path or "")})
        except Exception:
            self.left_images = []
        
        # Rebuild 3 hàng đầu
        self._rebuild_top_rows()
        
        # Clear container
        while self.prompts_layout.count():
            child = self.prompts_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Load prompts từ file
        prompts = []
        if hasattr(self.parent_app, 'txt_integrate_custom_prompt_file'):
            prompt_file = self.parent_app.txt_integrate_custom_prompt_file.text().strip()
            if prompt_file and Path(prompt_file).exists():
                try:
                    with open(prompt_file, 'r', encoding='utf-8') as f:
                        prompts = [line.strip() for line in f if line.strip()]
                except Exception as e:
                    if hasattr(self.parent_app, 'log'):
                        self.parent_app.log(f"⚠️ Lỗi đọc prompt file: {e}")
        
        # Dùng prompts đã chỉnh sửa nếu có
        if hasattr(self.parent_app, 'custom_prompts') and self.parent_app.custom_prompts:
            for idx, original_prompt in enumerate(prompts, 1):
                if idx in self.parent_app.custom_prompts:
                    prompts[idx - 1] = self.parent_app.custom_prompts[idx]
        
        # Nếu không có kết quả matching, vẫn hiển thị prompt để chỉnh thủ công
        if not hasattr(self.parent_app, 'character_matching_results') or not self.parent_app.character_matching_results:
            if prompts:
                for i in range(1, len(prompts) + 1):
                    self.create_prompt_item(i, prompts)
            return
        
        # Tạo UI cho mỗi prompt (Row 4+: panel trái/phải) theo kết quả matching
        for prompt_idx in sorted(self.parent_app.character_matching_results.keys()):
            self.create_prompt_item(prompt_idx, prompts)
    
    def _rebuild_top_rows(self):
        """Vẽ lại danh sách nhân vật dưới dạng thẻ gọn gàng"""
        layout = self.row1_scroll_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.global_all_checkboxes = []

        card_width = 156
        total_cards = len(self.left_images) + (1 if len(self.left_images) < 10 else 0)
        max_columns = max(1, min(10, total_cards if total_cards > 0 else 1))

        content_width = max_columns * (card_width + 12) + 16
        self.row1_scroll_content.setMinimumWidth(content_width)
        self.row1_scroll_content.setMaximumWidth(content_width)
        self.row1_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        for idx, info in enumerate(self.left_images):
            card = self._create_character_card(info, card_width)
            layout.addWidget(card, idx // max_columns, idx % max_columns)

        if len(self.left_images) < 10:
            add_card = self._create_add_character_card(card_width)
            layout.addWidget(add_card, len(self.left_images) // max_columns, len(self.left_images) % max_columns)

        layout.setRowStretch(0, 0)

    def _create_character_card(self, info: Dict[str, str], width: int) -> QWidget:
        """Tạo thẻ hiển thị cho một nhân vật"""
        char_name = str(info.get('name') or "Image")
        img_path = str(info.get('path') or "")

        card = QFrame()
        card.setFixedWidth(width)
        card.setStyleSheet("""
            QFrame {
                border: 1px solid #dce3f0;
                border-radius: 12px;
                background-color: #ffffff;
            }
            QFrame:hover {
                border: 1px solid #1A73E8;
                box-shadow: 0px 6px 18px rgba(26, 115, 232, 0.12);
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 12)
        card_layout.setSpacing(8)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        initials = "".join(part[:1] for part in char_name.split()[:2]).upper() or "NV"
        badge = QLabel(initials[:2])
        badge.setFixedSize(26, 22)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("""
            QLabel {
                background-color: #E3F2FD;
                color: #1A73E8;
                font-weight: 600;
                border-radius: 6px;
            }
        """)
        top_bar.addWidget(badge, 0, Qt.AlignLeft)

        remove_btn = QToolButton()
        remove_btn.setText("✕")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setFixedSize(22, 22)
        remove_btn.setStyleSheet("""
            QToolButton {
                border: none;
                color: #B71C1C;
                font-weight: bold;
            }
            QToolButton:hover {
                background-color: #EF5350;
                color: white;
                border-radius: 11px;
            }
        """)
        remove_btn.setToolTip(f"Xóa nhân vật '{char_name}'")
        remove_btn.clicked.connect(partial(self._on_remove_character_clicked, char_name))
        top_bar.addStretch()
        top_bar.addWidget(remove_btn)
        card_layout.addLayout(top_bar)

        thumb = QLabel()
        thumb.setFixedSize(width - 32, width - 32)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setStyleSheet("border: 1px solid #e0e6ef; border-radius: 10px; background-color: #f7f9fc;")

        if img_path and Path(img_path).exists():
            try:
                pixmap = QPixmap(img_path)
                if not pixmap.isNull():
                    thumb.setPixmap(pixmap.scaled(thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    thumb.setText("❌\nLỗi ảnh")
            except Exception:
                thumb.setText("❌\nLỗi ảnh")
        else:
            thumb.setText("⚠️\nKhông có ảnh")
        card_layout.addWidget(thumb, 0, Qt.AlignCenter)

        name_label = ClickableLabel(char_name)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                font-weight: 600;
                color: #1f2933;
                padding: 4px 6px;
                border-radius: 6px;
            }
            QLabel:hover {
                background-color: #F1F5FF;
            }
        """)
        name_label.setToolTip("Click để đổi tên nhân vật")
        name_label.clicked.connect(partial(self._on_character_label_clicked, char_name))
        card_layout.addWidget(name_label)

        global_row = QHBoxLayout()
        global_row.setContentsMargins(0, 0, 0, 0)
        global_row.setSpacing(6)
        global_chk = QCheckBox()
        global_chk.setToolTip(f"Áp dụng '{char_name}' cho tất cả prompts")
        global_chk.setProperty("char_name", char_name)
        global_chk.setProperty("is_global_checkbox", True)
        global_chk.setCursor(Qt.PointingHandCursor)
        global_chk.stateChanged.connect(partial(self._on_global_checkbox_changed, char_name))
        label = QLabel("All prompts")
        label.setStyleSheet("color:#5f6b7c; font-size:11px;")
        global_row.addWidget(global_chk)
        global_row.addWidget(label)
        global_row.addStretch()
        card_layout.addLayout(global_row)

        self.global_all_checkboxes.append(global_chk)
        card_layout.addStretch()

        return card

    def _create_add_character_card(self, width: int) -> QWidget:
        """Thẻ thêm nhân vật thủ công"""
        card = QFrame()
        card.setFixedWidth(width)
        card.setStyleSheet("""
            QFrame {
                border: 1px dashed #9BB7F1;
                border-radius: 12px;
                background-color: #F8FBFF;
            }
            QFrame:hover {
                border: 1px solid #1A73E8;
                background-color: #F3F8FF;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        icon = QLabel("➕")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 28px; color: #1A73E8;")
        layout.addWidget(icon)

        text = QLabel("Thêm ảnh thủ công")
        text.setAlignment(Qt.AlignCenter)
        text.setStyleSheet("color: #1A73E8; font-weight: 600;")
        layout.addWidget(text)

        btn = QPushButton("Chọn ảnh")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #1A73E8;
                color: white;
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1557B0;
            }
        """)
        btn.clicked.connect(self._on_add_left_image)
        layout.addWidget(btn, 0, Qt.AlignCenter)
        layout.addStretch()
        return card
    
    def _on_character_label_clicked(self, current_name: str):
        """Click vào tên nhân vật để đổi tên"""
        if not self.parent_app or not current_name:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Đổi tên nhân vật",
            "Nhập tên mới:",
            text=current_name
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == current_name:
            return
        if self._rename_character_internal(current_name, new_name):
            QTimer.singleShot(0, self.load_data)
            QTimer.singleShot(0, self.refresh_matching_summary)
            try:
                if hasattr(self.parent_app, 'signals') and hasattr(self.parent_app.signals, 'update_character_tree'):
                    self.parent_app.signals.update_character_tree.emit()
                    QTimer.singleShot(0, self.parent_app._update_character_tree)
            except Exception:
                pass
    
    def _rename_character_internal(self, old_name: str, new_name: str) -> bool:
        """Đổi tên nhân vật trong dữ liệu gốc"""
        try:
            if not hasattr(self.parent_app, 'custom_characters'):
                return False
            if new_name in self.parent_app.custom_characters and new_name != old_name:
                QMessageBox.warning(self, "Cảnh báo", f"Tên '{new_name}' đã tồn tại!")
                return False
            if old_name not in self.parent_app.custom_characters:
                return False
            
            img_path = self.parent_app.custom_characters.pop(old_name)
            self.parent_app.custom_characters[new_name] = img_path
            
            # Update extracted characters list
            try:
                if hasattr(self.parent_app, 'extracted_characters') and isinstance(self.parent_app.extracted_characters, list):
                    for char_info in self.parent_app.extracted_characters:
                        if isinstance(char_info, dict) and char_info.get('name') == old_name:
                            char_info['name'] = new_name
            except Exception:
                pass
            
            # Update character_images and related dicts
            for attr in ['character_images', 'character_image_sources', 'character_image_media_ids']:
                container = getattr(self.parent_app, attr, None)
                if isinstance(container, dict) and old_name in container:
                    container[new_name] = container.pop(old_name)
            
            # Update matching results
            try:
                if hasattr(self.parent_app, 'character_matching_results'):
                    for matched in self.parent_app.character_matching_results.values():
                        if isinstance(matched, list):
                            for idx, name in enumerate(matched):
                                if name == old_name:
                                    matched[idx] = new_name
                        elif isinstance(matched, dict):
                            if old_name in matched:
                                matched[new_name] = matched.pop(old_name)
            except Exception:
                pass
            
            # Update local left_images cache
            for info in self.left_images:
                if info.get('name') == old_name:
                    info['name'] = new_name
            
            # ✅ Update label trong parent app (không phải trong dialog)
            if hasattr(self.parent_app, 'lbl_char_count'):
                self.parent_app.lbl_char_count.setText(f"Đã thêm: {len(self.parent_app.custom_characters)}/10 nhân vật")
            
            return True
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể đổi tên nhân vật: {e}")
            return False
    
    def _on_remove_character_clicked(self, char_name: str):
        """Xóa nhân vật khỏi danh sách"""
        if not self.parent_app or not char_name:
            return
        try:
            if hasattr(self.parent_app, 'on_delete_character'):
                self.parent_app.on_delete_character(char_name)
                QTimer.singleShot(0, self.load_data)
                if hasattr(self, "refresh_matching_summary"):
                    QTimer.singleShot(0, self.refresh_matching_summary)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể xóa nhân vật: {e}")
    
    def _on_add_left_image(self):
        """Thêm ảnh thủ công vào panel trái (tối đa 6)"""
        try:
            if len(self.left_images) >= 10:
                QMessageBox.information(self, "Thông báo", "Đã đạt tối đa 10 ảnh.")
                return
            file_path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh nhân vật", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
            if not file_path:
                return
            # Hỏi tên nhân vật ngắn gọn (fallback theo số thứ tự)
            base_name = Path(file_path).stem[:20] if Path(file_path).stem else ""
            name = base_name if base_name else f"Image {len(self.left_images)+1}"
            # Đảm bảo tên không trùng trong parent_app.custom_characters
            if hasattr(self.parent_app, 'custom_characters'):
                original = name
                suffix = 1
                while name in self.parent_app.custom_characters:
                    name = f"{original}_{suffix}"
                    suffix += 1
                # Cập nhật vào nguồn dữ liệu chính để load_data() không mất ảnh vừa thêm
                if len(self.parent_app.custom_characters) < 10:
                    self.parent_app.custom_characters[name] = str(file_path)
                else:
                    QMessageBox.information(self, "Thông báo", "Đã đạt tối đa 10 ảnh.")
                    return
            # Đồng bộ dữ liệu cho Kho Character (ngoài dialog)
            try:
                if not hasattr(self.parent_app, 'extracted_characters') or self.parent_app.extracted_characters is None:
                    self.parent_app.extracted_characters = []
                if not hasattr(self.parent_app, 'character_images') or self.parent_app.character_images is None:
                    self.parent_app.character_images = {}
                if not hasattr(self.parent_app, 'character_image_sources') or self.parent_app.character_image_sources is None:
                    self.parent_app.character_image_sources = {}
                # Thêm vào danh sách nhân vật nếu chưa có
                if name not in [c.get('name') for c in self.parent_app.extracted_characters]:
                    self.parent_app.extracted_characters.append({
                        'name': name,
                        'description': 'Manual import',
                        'scenes': []
                    })
                # Cập nhật map ảnh và nguồn
                self.parent_app.character_images[name] = str(file_path)
                self.parent_app.character_image_sources[name] = 'uploaded'
            except Exception:
                pass
            self.left_images.append({'name': str(name), 'path': str(file_path)})
            self._rebuild_top_rows()
            
            # Cập nhật lại UI prompt để có thêm cột tick tương ứng
            self.load_data()
            # Đồng bộ UI bên ngoài ngay
            try:
                if hasattr(self.parent_app, 'signals') and hasattr(self.parent_app.signals, 'update_character_tree'):
                    self.parent_app.signals.update_character_tree.emit()
                    # Force update ngay lập tức để thấy đủ 10 nhân vật
                    QTimer.singleShot(0, self.parent_app._update_character_tree)
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể thêm ảnh: {e}")
    
    def create_prompt_item(self, prompt_idx, prompts):
        """Tạo một hàng gồm panel trái (tick) và panel phải (prompt)"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        row_widget.setProperty('prompt_idx', prompt_idx)
        
        # Panel trái: chọn nhân vật (≤3)
        left_panel = QFrame()
        left_panel.setFrameStyle(QFrame.Box)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)
        
        top_left = QHBoxLayout()
        top_left.setContentsMargins(0, 0, 0, 0)
        top_left.addStretch()
        btn_tick_all = QPushButton("Tích All (≤3)")
        btn_tick_all.setFixedHeight(26)
        btn_tick_all.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn_tick_all.clicked.connect(lambda checked=False, idx=prompt_idx: self._on_tick_all_for_prompt(idx))
        top_left.addWidget(btn_tick_all, 0, Qt.AlignRight)
        left_layout.addLayout(top_left)
        
        tick_row = QWidget()
        grid_layout = QGridLayout(tick_row)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(8)
        grid_layout.setVerticalSpacing(6)
        matched_chars = self.parent_app.character_matching_results.get(prompt_idx, []).copy()
        total_chars = max(1, len(self.left_images))
        max_cols = max(1, math.ceil(total_chars / 2))
        for i, img in enumerate(self.left_images):
            name = img.get('name') or f"Image {i+1}"
            chk = QCheckBox(name)
            chk.setChecked(name in matched_chars)
            chk.setToolTip(name)
            chk.setProperty('char_name', name)
            chk.setProperty('is_prompt_checkbox', True)
            chk.setProperty('prompt_idx', prompt_idx)
            chk.stateChanged.connect(partial(self.on_character_checkbox_changed, name, prompt_idx))
            row = i // max_cols
            col = i % max_cols
            grid_layout.addWidget(chk, row, col, Qt.AlignLeft)
        left_layout.addWidget(tick_row)
        
        # Panel phải: Prompt input
        right_panel = QFrame()
        right_panel.setFrameStyle(QFrame.Box)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 8, 10, 10)
        right_layout.setSpacing(6)
        
        prompt_text = prompts[prompt_idx - 1] if prompt_idx <= len(prompts) else f"Prompt {prompt_idx}"
        prompt_header = QHBoxLayout()
        prompt_header.setContentsMargins(0, 0, 0, 0)
        prompt_id_label = QLabel(f"{prompt_idx}")
        prompt_id_label.setStyleSheet("""
            QLabel {
                color: #1A73E8;
                background-color: #E3F2FD;
                font-weight: bold;
                border-radius: 10px;
                padding: 2px 10px;
            }
        """)
        prompt_id_label.setAlignment(Qt.AlignCenter)
        prompt_header.addWidget(prompt_id_label, 0, Qt.AlignLeft)
        prompt_header.addStretch()
        right_layout.addLayout(prompt_header)

        prompt_edit = QPlainTextEdit()
        prompt_edit.setPlainText(prompt_text)
        prompt_edit.setWordWrapMode(QTextOption.WordWrap)
        prompt_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        prompt_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        prompt_edit.setMinimumHeight(110)
        prompt_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        prompt_edit.setStyleSheet("""
            QPlainTextEdit {
                border: 1px solid #d0d5dd;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 12px;
                background-color: #ffffff;
            }
            QPlainTextEdit:focus {
                border: 1px solid #1A73E8;
                box-shadow: 0 0 4px rgba(26, 115, 232, 0.35);
            }
        """)
        prompt_edit.setProperty('prompt_idx', prompt_idx)
        prompt_edit.textChanged.connect(lambda: self.on_prompt_text_changed(prompt_edit))
        right_layout.addWidget(prompt_edit)
        
        # Đồng bộ chiều cao hàng 1 trái/phải
        left_panel.setMinimumHeight(prompt_edit.sizeHint().height() + 20)
        
        # Chia đôi width
        row_layout.addWidget(left_panel)
        row_layout.addWidget(right_panel)
        row_layout.setStretch(0, 7)
        row_layout.setStretch(1, 13)
        
        self.prompts_layout.addWidget(row_widget)
    
    def _on_global_checkbox_changed(self, char_name, state):
        """Global checkbox thay đổi (áp dụng cho tất cả prompts, tối đa 3)"""
        if not hasattr(self.parent_app, 'character_matching_results'):
            return
        try:
            selected = [
                str(chk.property("char_name"))
                for chk in self.global_all_checkboxes
                if isinstance(chk, QCheckBox) and chk.isChecked() and chk.property("char_name")
            ]

            if len(selected) > 3:
                sender = self.sender()
                if isinstance(sender, QCheckBox):
                    sender.blockSignals(True)
                    sender.setChecked(False)
                    sender.blockSignals(False)
                return

            allow_more = len(selected) < 3
            for chk in self.global_all_checkboxes:
                if not isinstance(chk, QCheckBox):
                    continue
                char = chk.property("char_name")
                if not char:
                    continue
                if char in selected:
                    chk.setEnabled(True)
                else:
                    chk.setEnabled(allow_more)

            for prompt_idx in list(self.parent_app.character_matching_results.keys()):
                self.parent_app.character_matching_results[prompt_idx] = selected.copy()

            for i in range(self.prompts_layout.count()):
                row_widget = self.prompts_layout.itemAt(i).widget()
                if not row_widget:
                    continue
                for chk in row_widget.findChildren(QCheckBox):
                    if not isinstance(chk, QCheckBox):
                        continue
                    if not chk.property("is_prompt_checkbox"):
                        continue
                    char = chk.property("char_name")
                    chk.blockSignals(True)
                    chk.setChecked(char in selected)
                    chk.setEnabled(char in selected or len(selected) < 3)
                    chk.blockSignals(False)
        except Exception:
            pass
    
    def _on_tick_all_for_prompt(self, prompt_idx):
        """Chọn tối đa 3 ảnh đầu cho prompt"""
        if not self.parent_app:
            return
        try:
            names = [str(img.get('name') or f"Image {i+1}") for i, img in enumerate(self.left_images)]
            if not names:
                return
            selected = names[:3]
            self.parent_app.character_matching_results[prompt_idx] = selected
            for i in range(self.prompts_layout.count()):
                row_widget = self.prompts_layout.itemAt(i).widget()
                if not row_widget:
                    continue
                for chk in row_widget.findChildren(QCheckBox):
                    if not isinstance(chk, QCheckBox):
                        continue
                    if not chk.property("is_prompt_checkbox"):
                        continue
                    if chk.property("prompt_idx") != prompt_idx:
                        continue
                    char = chk.property("char_name")
                    chk.blockSignals(True)
                    chk.setChecked(char in selected)
                    chk.setEnabled(char in selected or len(selected) < 3)
                    chk.blockSignals(False)
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"❌ Lỗi tick all: {e}")
    
    def _on_tick_all_global_changed(self, state):
        """Checkbox All: chọn/bỏ chọn toàn bộ prompts (≤3 ảnh đầu)"""
        try:
            if state == Qt.Checked:
                self._on_tick_all_for_all_prompts()
            else:
                # Clear toàn bộ lựa chọn
                for prompt_idx in list(self.parent_app.character_matching_results.keys()):
                    self.parent_app.character_matching_results[prompt_idx] = []
                # Cập nhật UI nhanh
                for i in range(self.prompts_layout.count()):
                    item = self.prompts_layout.itemAt(i)
                    pf = item.widget() if item else None
                    if not pf:
                        continue
                for chk in pf.findChildren(QCheckBox):
                    if not isinstance(chk, QCheckBox):
                        continue
                    if not chk.property("is_prompt_checkbox"):
                        continue
                    chk.blockSignals(True)
                    chk.setChecked(False)
                    chk.setEnabled(True)
                    chk.blockSignals(False)
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"❌ Lỗi All checkbox: {e}")
    
    def _on_tick_all_for_all_prompts(self):
        """Áp dụng Tích All (≤3 ảnh đầu) cho tất cả prompts"""
        try:
            names = [str(img.get('name') or f"Image {i+1}") for i, img in enumerate(self.left_images)]
            selected = names[:3]
            # Update data
            for prompt_idx in list(self.parent_app.character_matching_results.keys()):
                self.parent_app.character_matching_results[prompt_idx] = selected.copy()
            # Update UI
            for i in range(self.prompts_layout.count()):
                item = self.prompts_layout.itemAt(i)
                pf = item.widget() if item else None
                if not pf:
                    continue
                for chk in pf.findChildren(QCheckBox):
                    if not isinstance(chk, QCheckBox):
                        continue
                    if not chk.property("is_prompt_checkbox"):
                        continue
                    char = chk.property("char_name")
                    chk.blockSignals(True)
                    chk.setChecked(char in selected)
                    chk.setEnabled(char in selected or len(selected) < 3)
                    chk.blockSignals(False)
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"❌ Lỗi Tích All toàn bộ: {e}")
    
    def create_character_widget(self, char_name, prompt_idx, is_selected, max_reached):
        """Tạo widget hiển thị character với ảnh"""
        char_frame = QFrame()
        char_frame.setFrameStyle(QFrame.Box)
        char_frame.setStyleSheet(f"""
            QFrame {{
                border: 2px solid {'#4CAF50' if is_selected else '#e0e0e0'};
                border-radius: 6px;
                background-color: {'#e8f5e9' if is_selected else 'white'};
                padding: 5px;
            }}
        """)
        char_layout = QVBoxLayout(char_frame)
        char_layout.setSpacing(5)
        char_layout.setContentsMargins(8, 8, 8, 8)
        
        # Ảnh character
        img_path = self.parent_app.custom_characters.get(char_name, "")
        img_label = QLabel()
        img_label.setFixedSize(120, 120)
        img_label.setAlignment(Qt.AlignCenter)
        img_label.setStyleSheet("border: 1px solid #cccccc; border-radius: 4px; background-color: #f5f5f5;")
        
        if img_path and Path(img_path).exists():
            try:
                pixmap = QPixmap(img_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    img_label.setPixmap(scaled)
            except Exception as e:
                img_label.setText("❌\nLỗi\nảnh")
                if hasattr(self.parent_app, 'log'):
                    self.parent_app.log(f"⚠️ Lỗi load ảnh {char_name}: {e}")
        else:
            img_label.setText("⚠️\nKhông có\nảnh")
        
        char_layout.addWidget(img_label)
        
        # Checkbox
        chk = QCheckBox(char_name)
        chk.setChecked(is_selected)
        chk.setEnabled(not (max_reached and not is_selected))
        chk.stateChanged.connect(partial(self.on_character_checkbox_changed, char_name, prompt_idx))
        char_layout.addWidget(chk)
        
        char_frame.setProperty('prompt_idx', prompt_idx)
        char_frame.setProperty('char_name', char_name)
        char_frame.setProperty('checkbox', chk)
        
        return char_frame
    
    def on_prompt_text_changed(self, text_edit):
        """Xử lý khi user chỉnh sửa prompt text"""
        if not self.parent_app:
            return
        try:
            prompt_idx = text_edit.property('prompt_idx')
            new_prompt = text_edit.toPlainText()
            if not hasattr(self.parent_app, 'custom_prompts'):
                self.parent_app.custom_prompts = {}
            self.parent_app.custom_prompts[prompt_idx] = new_prompt
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"❌ Lỗi update prompt: {e}")
    
    
    def on_character_checkbox_changed(self, char_name, prompt_idx, state):
        """Xử lý khi user check/uncheck character"""
        if not self.parent_app:
            return
        try:
            current = self.parent_app.character_matching_results.get(prompt_idx, [])
            # Chuẩn hóa về list[str]
            if isinstance(current, dict):
                matched_chars = list(current.keys())
            elif isinstance(current, (set, tuple)):
                matched_chars = list(current)
            elif isinstance(current, list):
                matched_chars = current.copy()
            else:
                matched_chars = []
            
            if state == Qt.Checked:
                if char_name in matched_chars:
                    pass
                elif len(matched_chars) < 3:
                    matched_chars.append(char_name)
                else:
                    QMessageBox.warning(self, "Cảnh báo", "Tối đa 3 characters mỗi prompt!")
                    # Hoàn nguyên checkbox hiện tại (không dùng logic uncheck cũ để tránh bug)
                    sender = self.sender()
                    if isinstance(sender, QCheckBox):
                        sender.blockSignals(True)
                        sender.setChecked(False)
                        sender.blockSignals(False)
                    return
            else:
                if char_name in matched_chars:
                    matched_chars.remove(char_name)
            
            self.parent_app.character_matching_results[prompt_idx] = matched_chars
            # Không rebuild toàn bộ UI để tránh lỗi và闪烁
            sender = self.sender()
            if isinstance(sender, QCheckBox):
                row_widget = sender.parent()
                if row_widget and row_widget.layout():
                    max_reached = len(matched_chars) >= 3
                    for i in range(row_widget.layout().count()):
                        item = row_widget.layout().itemAt(i)
                        if not item or not item.widget():
                            continue
                        w = item.widget()
                        if isinstance(w, QCheckBox):
                            name = w.property("char_name") or w.text()
                            if name in matched_chars:
                                w.setEnabled(True)
                            else:
                                w.setEnabled(not max_reached)
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"❌ Lỗi update character: {e}")
    
    def _uncheck_character_checkbox(self, char_name, prompt_idx):
        """Tìm và uncheck checkbox của character"""
        # Tìm tất cả QFrame trong prompts_layout
        for i in range(self.prompts_layout.count()):
            item = self.prompts_layout.itemAt(i)
            if item and item.widget():
                prompt_frame = item.widget()
                # Tìm chars_container trong prompt_frame
                chars_container = None
                for child in prompt_frame.findChildren(QWidget):
                    if child.layout() and isinstance(child.layout(), QHBoxLayout):
                        # Kiểm tra xem có chứa character frames không
                        for j in range(child.layout().count()):
                            char_item = child.layout().itemAt(j)
                            if char_item and char_item.widget():
                                test_frame = char_item.widget()
                                if test_frame.property('char_name'):
                                    chars_container = child
                                    break
                        if chars_container:
                            break
                
                if chars_container:
                    for j in range(chars_container.layout().count()):
                        char_item = chars_container.layout().itemAt(j)
                        if char_item and char_item.widget():
                            char_frame = char_item.widget()
                            if (char_frame.property('prompt_idx') == prompt_idx and 
                                char_frame.property('char_name') == char_name):
                                checkbox = char_frame.property('checkbox')
                                if checkbox:
                                    checkbox.blockSignals(True)
                                    checkbox.setChecked(False)
                                    checkbox.blockSignals(False)
                                return
    
    def on_add_character_to_prompt(self, prompt_idx):
        """Thêm character vào prompt"""
        if not self.parent_app:
            return
        matched_chars = self.parent_app.character_matching_results.get(prompt_idx, [])
        if len(matched_chars) >= 3:
            QMessageBox.warning(self, "Cảnh báo", "Tối đa 3 characters mỗi prompt!")
            return
        
        available_chars = [name for name in self.parent_app.custom_characters.keys() if name not in matched_chars]
        if not available_chars:
            QMessageBox.information(self, "Thông báo", "Đã chọn hết characters!")
            return
        
        char_to_add = available_chars[0]
        matched_chars.append(char_to_add)
        self.parent_app.character_matching_results[prompt_idx] = matched_chars
        self.load_data()
    
    def on_remove_character_from_prompt(self, prompt_idx):
        """Bỏ character khỏi prompt"""
        if not self.parent_app:
            return
        matched_chars = self.parent_app.character_matching_results.get(prompt_idx, [])
        if not matched_chars:
            return
        
        matched_chars.pop()
        self.parent_app.character_matching_results[prompt_idx] = matched_chars
        self.load_data()
    
    def accept(self):
        """Lưu và đóng"""
        # Thu thập lại checkbox hiện tại để chắc chắn lưu mapping thủ công
        try:
            self._collect_matching_from_ui()
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"⚠️ Không thể đồng bộ matching thủ công (accept): {e}")
        # Prompts đã được lưu tự động khi user chỉnh sửa trong on_prompt_text_changed
        # Refresh summary trong parent dialog
        if self.parent_dialog and hasattr(self.parent_dialog, 'refresh_matching_summary'):
            self.parent_dialog.refresh_matching_summary()
        
        super().accept()

    def _collect_matching_from_ui(self):
        """Ghi lại các checkbox nhân vật đang chọn vào parent_app.character_matching_results"""
        if not self.parent_app:
            return
        if not hasattr(self.parent_app, 'character_matching_results') or self.parent_app.character_matching_results is None:
            self.parent_app.character_matching_results = {}
        
        # Duyệt từng prompt row, đọc checkbox đã tick
        for i in range(self.prompts_layout.count()):
            row_widget = self.prompts_layout.itemAt(i).widget()
            if not row_widget:
                continue
            prompt_idx = row_widget.property('prompt_idx') or (i + 1)
            try:
                prompt_idx = int(prompt_idx)
            except Exception:
                prompt_idx = i + 1
            matched = []
            for chk in row_widget.findChildren(QCheckBox):
                if not isinstance(chk, QCheckBox):
                    continue
                if not chk.property("is_prompt_checkbox"):
                    continue
                if chk.isChecked():
                    name = chk.property("char_name") or chk.text()
                    if name:
                        matched.append(str(name))
            # Giới hạn 3 để tránh lỗi sau này
            matched = matched[:3]
            self.parent_app.character_matching_results[int(prompt_idx)] = matched


class ExtendProjectEditDialog(QDialog):
    """Dialog chỉnh sửa prompt lỗi cho Extend Project - Bootstrap style, chỉ hiển thị 1 prompt lỗi"""
    
    def __init__(self, project, parent=None, highlight_index=None):
        super().__init__(parent)
        self.project = project
        self.highlight_index = highlight_index  # Segment index cần sửa (1-based)
        self.error_segment = None  # Segment lỗi cần sửa
        
        # ✅ Tìm segment lỗi đầu tiên
        if self.highlight_index is not None:
            for seg in self.project.segments:
                if seg.index == self.highlight_index:
                    self.error_segment = seg
                    break
        
        # Nếu không có highlight_index, tìm segment lỗi đầu tiên
        if self.error_segment is None:
            for seg in self.project.segments:
                if hasattr(seg, 'status') and seg.status == "error":
                    self.error_segment = seg
                    self.highlight_index = seg.index
                    break
        
        if self.error_segment is None:
            QMessageBox.warning(parent, "Cảnh báo", "Không tìm thấy segment lỗi để sửa!")
            self.reject()
            return
        
        self.setWindowTitle(f"Chỉnh Sửa Prompt Lỗi - {project.project_name}")
        self.setModal(True)
        # ✅ Giảm kích thước cho màn hình nhỏ
        self.setMinimumSize(500, 350)
        self.resize(600, 400)
        
        # ✅ Bootstrap-style CSS
        self.setStyleSheet("""
            QDialog {
                background-color: #f8f9fa;
            }
            QFrame#cardFrame {
                background-color: #ffffff;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 20px;
            }
            QLabel#titleLabel {
                font-size: 20px;
                font-weight: bold;
                color: #212529;
                margin-bottom: 8px;
            }
            QLabel#infoLabel {
                font-size: 14px;
                color: #6c757d;
                margin-bottom: 16px;
            }
            QLabel#segmentLabel {
                font-size: 13px;
                font-weight: 600;
                color: #495057;
                margin-bottom: 8px;
            }
            QLabel#statusLabel {
                font-size: 12px;
                padding: 4px 12px;
                border-radius: 12px;
                font-weight: 600;
            }
            QPlainTextEdit {
                border: 1px solid #ced4da;
                border-radius: 6px;
                padding: 12px;
                font-size: 13px;
                background-color: #ffffff;
                min-height: 120px;
            }
            QPlainTextEdit:focus {
                border: 2px solid #0d6efd;
                background-color: #f8f9ff;
            }
            QPushButton#btnPrimary {
                background-color: #0d6efd;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;  # ✅ Giảm padding
                font-size: 13px;  # ✅ Giảm từ 14px
                font-weight: 600;
                min-width: 100px;  # ✅ Giảm từ 120px
            }
            QPushButton#btnPrimary:hover {
                background-color: #0b5ed7;
            }
            QPushButton#btnPrimary:pressed {
                background-color: #0a58ca;
            }
            QPushButton#btnSecondary {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;  # ✅ Giảm padding
                font-size: 13px;  # ✅ Giảm từ 14px
                font-weight: 600;
                min-width: 100px;  # ✅ Giảm từ 120px
            }
            QPushButton#btnSecondary:hover {
                background-color: #5c636a;
            }
            QPushButton#btnSecondary:pressed {
                background-color: #565e64;
            }
        """)
        
        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # ✅ Scroll Area để hỗ trợ màn hình nhỏ
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #f8f9fa;
            }
            QScrollBar:vertical {
                background-color: #e9ecef;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #adb5bd;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #868e96;
            }
        """)
        
        # ✅ Card Frame (Bootstrap card style)
        card_frame = QFrame()
        card_frame.setObjectName("cardFrame")
        card_layout = QVBoxLayout(card_frame)
        card_layout.setSpacing(12)  # ✅ Giảm spacing
        card_layout.setContentsMargins(20, 20, 20, 20)  # ✅ Giảm margins
        
        # Title
        title = QLabel(f"🔧 Chỉnh Sửa Prompt Lỗi")
        title.setObjectName("titleLabel")
        card_layout.addWidget(title)
        
        # Info
        info = QLabel(f"Project: <b>{self.project.project_name}</b> | Segment #{self.error_segment.index}")
        info.setObjectName("infoLabel")
        info.setWordWrap(True)
        card_layout.addWidget(info)
        
        # Segment info row
        segment_info_layout = QHBoxLayout()
        segment_info_layout.setSpacing(12)
        
        segment_label = QLabel("Prompt:")
        segment_label.setObjectName("segmentLabel")
        segment_info_layout.addWidget(segment_label)
        
        # Status badge
        status_badge = QLabel("❌ Lỗi")
        status_badge.setObjectName("statusLabel")
        status_badge.setStyleSheet("background-color: #f8d7da; color: #721c24;")
        status_badge.setAlignment(Qt.AlignCenter)
        status_badge.setFixedHeight(24)
        segment_info_layout.addStretch()
        segment_info_layout.addWidget(status_badge)
        
        card_layout.addLayout(segment_info_layout)
        
        # Prompt text edit
        self.prompt_edit = QPlainTextEdit(self.error_segment.text)
        self.prompt_edit.setPlaceholderText("Nhập prompt mới...")
        self.prompt_edit.setMinimumHeight(120)  # ✅ Giảm từ 150px
        self.prompt_edit.setMaximumHeight(200)  # ✅ Thêm max height để tiết kiệm không gian
        self.prompt_edit.setFocus()
        # Select all text để dễ chỉnh sửa
        QTimer.singleShot(100, lambda: self.prompt_edit.selectAll())
        card_layout.addWidget(self.prompt_edit)
        
        # Error message (nếu có)
        if hasattr(self.error_segment, 'error_message') and self.error_segment.error_message:
            error_msg = QLabel(f"⚠️ <b>Lỗi:</b> {self.error_segment.error_message}")
            error_msg.setStyleSheet("""
                color: #721c24;
                background-color: #f8d7da;
                border: 1px solid #f5c2c7;
                border-radius: 6px;
                padding: 8px;  # ✅ Giảm từ 10px
                font-size: 11px;  # ✅ Giảm từ 12px
            """)
            error_msg.setWordWrap(True)
            card_layout.addWidget(error_msg)
        
        card_layout.addStretch()
        
        # Buttons (Bootstrap style)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("Hủy")
        btn_cancel.setObjectName("btnSecondary")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_save = QPushButton("💾 Lưu và Tiếp tục")
        btn_save.setObjectName("btnPrimary")
        btn_save.clicked.connect(self.on_save)
        btn_layout.addWidget(btn_save)
        
        card_layout.addLayout(btn_layout)
        
        main_layout.addWidget(card_frame)
    
    def on_save(self):
        """Lưu prompt đã chỉnh sửa và đóng dialog"""
        new_text = self.prompt_edit.toPlainText().strip()
        if not new_text:
            QMessageBox.warning(self, "Cảnh báo", "Prompt không được để trống!")
            return
        
        # ✅ Cập nhật text của segment lỗi
        self.error_segment.text = new_text
        # Reset status để retry
        self.error_segment.status = "pending"
        if hasattr(self.error_segment, 'error_message'):
            self.error_segment.error_message = ""
        
        self.accept()


class CustomIntegrateDialog(QDialog):
    """Dialog đơn giản cho chức năng Tùy Chỉnh Integrate"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cấu Hình Tùy Chỉnh")
        self.setModal(True)
        
        # Kích thước dialog
        self.setMinimumSize(800, 700)
        self.resize(900, 750)
        
        # Style đơn giản
        self.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cccccc;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
            QTableWidget {
                border: 1px solid #cccccc;
                gridline-color: #e0e0e0;
            }
            QLineEdit {
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 5px;
            }
        """)
        
        self.parent_app = parent
        self.init_ui()
    
    def init_ui(self):
        """Khởi tạo UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Scroll area để tránh UI bị cắt
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 5, 5, 5)
        content_layout.setSpacing(10)
        
        # Kho Character
        char_group = QGroupBox("Kho Character (Tối đa 10 nhân vật)")
        char_layout = QVBoxLayout()
        char_layout.setSpacing(8)
        
        # Import buttons row
        import_row = QHBoxLayout()
        import_row.setSpacing(10)
        btn_import = QPushButton("Thêm Ảnh Thủ Công")
        btn_import.setFixedSize(150, 30)
        btn_import.clicked.connect(self.on_import_characters)
        import_row.addWidget(btn_import)
        # Import by Folder
        btn_import_folder = QPushButton("Thêm Ảnh Từ Folder")
        btn_import_folder.setFixedSize(150, 30)
        btn_import_folder.clicked.connect(self.on_import_characters_folder)
        import_row.addWidget(btn_import_folder)
        
        guide_label = QLabel("Hướng Dẫn: Đặt đúng tên Nhân Vật giống trong Prompt trên bảng hiển thị để Auto ảnh Nhân vật chính xác.")
        guide_label.setWordWrap(True)
        guide_label.setStyleSheet("""
            QLabel {
                background-color: #FFF8E1;
                border: 1px solid #FFCC80;
                border-radius: 6px;
                color: #7A4E00;
                padding: 8px 14px;
                font-size: 11px;
            }
        """)
        guide_label.setMinimumWidth(420)
        guide_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        import_row.addWidget(guide_label)
        import_row.addStretch()
        char_layout.addLayout(import_row)
        
        # Character table
        self.characters_table = QTableWidget()
        self.characters_table.setColumnCount(4)
        self.characters_table.setHorizontalHeaderLabels(["STT", "Tên Nhân Vật", "Ảnh", "Thao tác"])
        self.characters_table.setMinimumHeight(200)
        self.characters_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.characters_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.characters_table.verticalHeader().setVisible(False)
        self.characters_table.setColumnWidth(0, 50)
        self.characters_table.setColumnWidth(1, 150)
        self.characters_table.setColumnWidth(3, 100)
        self.characters_table.horizontalHeader().setStretchLastSection(True)
        self.characters_table.itemChanged.connect(self.on_character_name_changed)
        char_layout.addWidget(self.characters_table)
        
        # Count label
        self.lbl_char_count = QLabel("Đã thêm: 0/10 nhân vật")
        self.lbl_char_count.setStyleSheet("color: #333333; font-size: 11px;")
        char_layout.addWidget(self.lbl_char_count)
        
        char_group.setLayout(char_layout)
        content_layout.addWidget(char_group)
        
        # File prompt
        prompt_label = QLabel("File txt chứa prompt:")
        content_layout.addWidget(prompt_label)
        
        prompt_row = QHBoxLayout()
        self.txt_prompt_file = QLineEdit()
        self.txt_prompt_file.setPlaceholderText("Chọn file prompt...")
        prompt_row.addWidget(self.txt_prompt_file)
        btn_browse = QPushButton("Chọn file")
        btn_browse.setFixedSize(80, 25)
        btn_browse.clicked.connect(self.browse_prompt_file)
        prompt_row.addWidget(btn_browse)
        content_layout.addLayout(prompt_row)
        
        # Gemini API Key + AI Analysis row
        analyze_row = QHBoxLayout()
        analyze_row.setSpacing(10)
        
        lbl_gemini = QLabel("Gemini API Key: <span style='color: red;'>(Bắt buộc)</span>")
        lbl_gemini.setStyleSheet("font-weight: bold;")
        lbl_gemini.setTextFormat(Qt.RichText)
        analyze_row.addWidget(lbl_gemini)
        
        self.txt_gemini_api_key = QPlainTextEdit()
        self.txt_gemini_api_key.setPlaceholderText("Nhập Gemini API Key (mỗi dòng một key) - BẮT BUỘC")
        self.txt_gemini_api_key.setMinimumWidth(260)
        self.txt_gemini_api_key.setFixedHeight(70)
        # ✅ Tự động lưu khi user nhập (sau 1 giây không nhập)
        self._integrate_gemini_key_timer = QTimer()
        self._integrate_gemini_key_timer.setSingleShot(True)
        self._integrate_gemini_key_timer.timeout.connect(lambda: self._auto_save_gemini_key_from_input_integrate())
        self.txt_gemini_api_key.textChanged.connect(lambda: self._integrate_gemini_key_timer.start(1000))  # Delay 1s
        analyze_row.addWidget(self.txt_gemini_api_key)
        
        # AI Analysis button - Lưu reference để có thể re-enable sau
        self.btn_analyze = QPushButton("AI Phân Tích (Auto ảnh nhân vật)")
        self.btn_analyze.setFixedSize(250, 35)
        self.btn_analyze.clicked.connect(self.on_analyze)
        analyze_row.addWidget(self.btn_analyze)
        analyze_row.addStretch()
        content_layout.addLayout(analyze_row)
        
        # Kết quả matching - Đơn giản hóa, chỉ hiển thị summary
        result_group = QGroupBox("Kết Quả Matching")
        result_layout = QVBoxLayout()
        
        # Summary label
        self.lbl_matching_summary = QLabel("Chưa có kết quả matching")
        self.lbl_matching_summary.setStyleSheet("color: #666666; font-size: 12px; padding: 10px;")
        result_layout.addWidget(self.lbl_matching_summary)
        
        # Nút mở popup chỉnh sửa
        btn_edit_matching = QPushButton("✏️ Kiểm tra ảnh đã Auto")
        btn_edit_matching.setFixedSize(200, 35)
        btn_edit_matching.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        btn_edit_matching.clicked.connect(self.open_matching_edit_dialog)
        result_layout.addWidget(btn_edit_matching)
        
        result_group.setLayout(result_layout)
        content_layout.addWidget(result_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        # Nút Lưu & Generate
        self.btn_save_generate = QPushButton("💾 Lưu để ra Bắt đầu chạy")
        self.btn_save_generate.setFixedSize(220, 35)
        self.btn_save_generate.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.btn_save_generate.clicked.connect(self.on_save_and_generate)
        btn_layout.addWidget(self.btn_save_generate)
        
        btn_close = QPushButton("Đóng")
        btn_close.setFixedSize(100, 30)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        content_layout.addLayout(btn_layout)
        
        # Set content widget vào scroll
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
        
        # Load data từ parent
        self.load_data_from_parent()
        # Refresh summary
        self.refresh_matching_summary()
    
    def _get_entered_gemini_keys(self) -> List[str]:
        """Lấy danh sách Gemini keys đang nhập"""
        try:
            text = self.txt_gemini_api_key.toPlainText().strip()
        except Exception:
            text = ""
        return [line.strip() for line in text.splitlines() if line.strip()]
    
    def load_data_from_parent(self):
        """Load data từ parent app"""
        if not self.parent_app:
            return
        
        # Load prompt file path
        if hasattr(self.parent_app, 'txt_integrate_custom_prompt_file'):
            self.txt_prompt_file.setText(self.parent_app.txt_integrate_custom_prompt_file.text())
        
        # Refresh tables
        self.refresh_characters_table()
        self.refresh_matching_summary()
        
        # Load Gemini API keys
        try:
            keys = []
            if hasattr(self.parent_app, 'integrate_gemini_api_keys'):
                keys = self.parent_app.integrate_gemini_api_keys
            if keys:
                self.txt_gemini_api_key.setPlainText("\n".join(keys))
            else:
                self.txt_gemini_api_key.clear()
        except Exception:
            self.txt_gemini_api_key.clear()
        
        # Re-enable button nếu đã từng analyze (tránh trường hợp đóng dialog khi đang analyze)
        if hasattr(self, 'btn_analyze'):
            # Kiểm tra xem có đang trong trạng thái "đang phân tích" không
            if "⏳" in self.btn_analyze.text() or not self.btn_analyze.isEnabled():
                self.btn_analyze.setEnabled(True)
                self.btn_analyze.setText("AI Phân Tích (Auto ảnh nhân vật)")
    
    def save_data_to_parent(self):
        """Save data về parent app"""
        if not self.parent_app:
            return
        
        # Save prompt file path
        if hasattr(self.parent_app, 'txt_integrate_custom_prompt_file'):
            self.parent_app.txt_integrate_custom_prompt_file.setText(self.txt_prompt_file.text())
        
        # Save Gemini keys locally (không đẩy server ở đây)
        try:
            keys = self._get_entered_gemini_keys()
            if hasattr(self.parent_app, 'integrate_gemini_api_keys'):
                self.parent_app.integrate_gemini_api_keys = keys
        except Exception:
            pass

    def _collect_matching_from_ui(self):
        """Ghi lại các checkbox nhân vật đang chọn vào parent_app.character_matching_results"""
        if not self.parent_app:
            return
        if not hasattr(self.parent_app, 'character_matching_results') or self.parent_app.character_matching_results is None:
            self.parent_app.character_matching_results = {}
        
        # Duyệt từng prompt row, đọc checkbox đã tick
        for i in range(self.prompts_layout.count()):
            row_widget = self.prompts_layout.itemAt(i).widget()
            if not row_widget:
                continue
            prompt_idx = row_widget.property('prompt_idx') or (i + 1)
            try:
                prompt_idx = int(prompt_idx)
            except Exception:
                prompt_idx = i + 1
            matched = []
            for chk in row_widget.findChildren(QCheckBox):
                if not isinstance(chk, QCheckBox):
                    continue
                if not chk.property("is_prompt_checkbox"):
                    continue
                if chk.isChecked():
                    name = chk.property("char_name") or chk.text()
                    if name:
                        matched.append(str(name))
            # Giới hạn 3 để tránh lỗi sau này
            matched = matched[:3]
            self.parent_app.character_matching_results[int(prompt_idx)] = matched
    
    def on_import_characters(self):
        """Import characters"""
        if not self.parent_app:
            return
        self.parent_app.on_import_characters()
        self.refresh_characters_table()
    
    def on_import_characters_folder(self):
        """Import characters từ một thư mục chứa nhiều ảnh"""
        if not self.parent_app:
            return
        try:
            from PySide6.QtWidgets import QFileDialog
            folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục ảnh nhân vật")
            if not folder:
                return
            folder_path = Path(folder)
            if not folder_path.exists():
                QMessageBox.warning(self, "Cảnh báo", "Thư mục không tồn tại!")
                return
            
            # Chuẩn bị dict lưu
            if not hasattr(self.parent_app, 'custom_characters') or self.parent_app.custom_characters is None:
                self.parent_app.custom_characters = {}
            
            # Số slot còn lại
            remaining = max(0, 10 - len(self.parent_app.custom_characters))
            if remaining == 0:
                QMessageBox.information(self, "Thông báo", "Đã đủ 10 nhân vật.")
                return
            
            # Collect ảnh trong folder (đệ quy)
            exts = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
            image_files = [p for p in folder_path.rglob("*") if p.suffix.lower() in exts]
            if not image_files:
                QMessageBox.information(self, "Thông báo", "Không tìm thấy ảnh hợp lệ trong thư mục.")
                return
            
            added = 0
            for img in image_files:
                if added >= remaining:
                    break
                try:
                    # Tên mặc định từ file name (không extension)
                    base_name = img.stem.strip() or f"character_{len(self.parent_app.custom_characters)+1}"
                    candidate = base_name
                    # Đảm bảo tên duy nhất
                    suffix = 2
                    while candidate in self.parent_app.custom_characters:
                        candidate = f"{base_name}_{suffix}"
                        suffix += 1
                    # Lưu
                    self.parent_app.custom_characters[candidate] = str(img)
                    # Đồng bộ Kho Character bên ngoài
                    if not hasattr(self.parent_app, 'extracted_characters') or self.parent_app.extracted_characters is None:
                        self.parent_app.extracted_characters = []
                    if not hasattr(self.parent_app, 'character_images') or self.parent_app.character_images is None:
                        self.parent_app.character_images = {}
                    if not hasattr(self.parent_app, 'character_image_sources') or self.parent_app.character_image_sources is None:
                        self.parent_app.character_image_sources = {}
                    if candidate not in [c.get('name') for c in self.parent_app.extracted_characters]:
                        self.parent_app.extracted_characters.append({
                            'name': candidate,
                            'description': 'Manual import',
                            'scenes': []
                        })
                    self.parent_app.character_images[candidate] = str(img)
                    self.parent_app.character_image_sources[candidate] = 'uploaded'
                    added += 1
                except Exception as e:
                    if hasattr(self.parent_app, 'log'):
                        self.parent_app.log(f"⚠️ Bỏ qua ảnh {img}: {e}")
                    continue
            
            # Refresh UI
            try:
                self._rebuild_top_rows()
            except Exception:
                pass
            self.refresh_characters_table()
            self.refresh_matching_summary()
            # Đồng bộ bảng/khung ở ngoài (nếu có) thông qua signal
            try:
                if hasattr(self.parent_app, 'signals') and hasattr(self.parent_app.signals, 'update_character_tree'):
                    self.parent_app.signals.update_character_tree.emit()
                    QTimer.singleShot(0, self.parent_app._update_character_tree)
            except Exception:
                pass
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"✅ Đã import {added} ảnh từ thư mục (Tổng: {len(self.parent_app.custom_characters)}/10)")
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"❌ Lỗi import folder: {e}")
            QMessageBox.critical(self, "Lỗi", f"Lỗi import folder: {e}")
    
    def on_character_name_changed(self, item):
        """Xử lý khi sửa tên character"""
        if not self.parent_app:
            return
        self.parent_app.on_character_name_changed(item)
        self.refresh_characters_table()
        self.refresh_matching_summary()
    
    def browse_prompt_file(self):
        """Browse prompt file"""
        if not self.parent_app:
            return
        self.parent_app.browse_integrate_custom_prompt_file()
        if hasattr(self.parent_app, 'txt_integrate_custom_prompt_file'):
            self.txt_prompt_file.setText(self.parent_app.txt_integrate_custom_prompt_file.text())
    
    def open_matching_edit_dialog(self):
        """Mở dialog chỉnh sửa matching"""
        if not self.parent_app:
            return
        
        # Cho phép mở dialog ngay cả khi chưa chạy AI; dùng dữ liệu rỗng để chỉnh thủ công
        if not hasattr(self.parent_app, 'character_matching_results') or self.parent_app.character_matching_results is None:
            self.parent_app.character_matching_results = {}
        
        # Tạo và hiện dialog chỉnh sửa
        try:
            dialog = MatchingEditDialog(self.parent_app, self)
            dialog.exec()
            # Refresh summary sau khi đóng
            self.refresh_matching_summary()
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"❌ Lỗi mở dialog: {e}")
            import traceback
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"📋 Traceback: {traceback.format_exc()[:500]}")
            QMessageBox.critical(self, "Lỗi", f"Không thể mở dialog chỉnh sửa:\n{e}")
    
    def _auto_save_gemini_key_from_input_integrate(self):
        """Auto save gemini key từ input của Integrate dialog"""
        try:
            if hasattr(self, 'txt_gemini_api_key') and self.parent_app:
                text = self.txt_gemini_api_key.toPlainText().strip()
                if text and hasattr(self.parent_app, '_auto_save_gemini_key_from_input'):
                    self.parent_app._auto_save_gemini_key_from_input(self.txt_gemini_api_key, "Integrate tab")
        except Exception:
            pass
    
    def on_analyze(self):
        """AI Analysis"""
        if not self.parent_app:
            return
        
        keys = self.parent_app.get_gemini_api_keys() if hasattr(self.parent_app, 'get_gemini_api_keys') else self._get_entered_gemini_keys()
        if not keys:
            QMessageBox.warning(
                self, "Cảnh báo", 
                "Vui lòng nhập Gemini API Key!\n\n"
                "Cách 1: Nhấn nút '🔑 Cài Đặt Gemini API' ở header (khuyến nghị)\n"
                "Cách 2: Nhập vào ô Gemini API Key bên dưới"
            )
            self.txt_gemini_api_key.setFocus()
            return
        if not self.parent_app.save_integrate_gemini_keys(keys):
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng thử lại.")
            return
        
        # ✅ Tự động lưu Gemini API Key local (lấy key đầu tiên)
        if keys and len(keys) > 0:
            self.parent_app.save_gemini_api_key(keys[0])
        
        # Save prompt file trước
        self.save_data_to_parent()
        # Disable button
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setText("⏳ Đang phân tích...")
        # Disable nút Generate khi đang phân tích
        if hasattr(self, 'btn_save_generate'):
            self.btn_save_generate.setEnabled(False)
        # Gọi analyze từ parent
        self.parent_app.on_analyze_characters_match()
        # Refresh sau khi analyze (sẽ được gọi từ parent)
    
    def on_save_and_generate(self):
        """Lưu và tự động generate video"""
        if not self.parent_app:
            return
        
        # Thu thập mapping mới nhất từ popup matching (nếu đang mở)
        try:
            if hasattr(self, '_custom_dialog') and self._custom_dialog and self._custom_dialog.isVisible():
                if hasattr(self._custom_dialog, '_collect_matching_from_ui'):
                    self._custom_dialog._collect_matching_from_ui()
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"⚠️ Không thể đồng bộ matching từ dialog (save_generate): {e}")
        
        keys = self.parent_app.get_gemini_api_keys() if hasattr(self.parent_app, 'get_gemini_api_keys') else self._get_entered_gemini_keys()
        if not keys:
            QMessageBox.warning(
                self, "Cảnh báo", 
                "Vui lòng nhập Gemini API Key!\n\n"
                "Cách 1: Nhấn nút '🔑 Cài Đặt Gemini API' ở header (khuyến nghị)\n"
                "Cách 2: Nhập vào ô Gemini API Key bên dưới"
            )
            self.txt_gemini_api_key.setFocus()
            return
        if not self.parent_app.save_integrate_gemini_keys(keys):
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng thử lại.")
            return
        
        # Đưa nút AI Phân Tích về trạng thái ban đầu trước khi đóng dialog
        try:
            if hasattr(self, 'btn_analyze'):
                self.btn_analyze.setEnabled(True)
                self.btn_analyze.setText("AI Phân Tích (Auto ảnh nhân vật)")
        except Exception:
            pass
        try:
            # Gọi re-enable ở parent để đồng bộ khi dialog đóng
            QTimer.singleShot(0, lambda: self.parent_app._re_enable_analyze_button())
        except Exception:
            pass
        
        # Prompts đã được lưu tự động trong on_prompt_text_changed khi user chỉnh sửa
        # Không cần lấy từ table nữa vì đã dùng QTextEdit
        
        # Save data trước (prompt, matching, characters...)
        self.save_data_to_parent()
        
        # Validate: mỗi prompt tối đa 3 characters
        for prompt_idx, matched_chars in self.parent_app.character_matching_results.items():
            if len(matched_chars) > 3:
                QMessageBox.warning(self, "Cảnh báo", f"Prompt {prompt_idx} có {len(matched_chars)} characters. Tối đa 3 characters mỗi prompt!")
                return
        
        # Kiểm tra có characters không
        if not hasattr(self.parent_app, 'custom_characters') or not self.parent_app.custom_characters:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng import nhân vật!")
            return
        
        # Kiểm tra output folder
        output_folder = self.parent_app.output_folder.text().strip()
        if not output_folder:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn thư mục output!")
            return
        
        # Đóng dialog
        self.accept()
        
        # ✅ KHÔNG tự động start - User phải ấn "Bắt đầu" để chạy
        # QTimer.singleShot(300, lambda: self.parent_app._auto_start_custom_integrate())  # Đã xóa
        self.parent_app.log("✅ Đã lưu cấu hình. Vui lòng ấn 'Bắt đầu' để chạy.")
    
    def refresh_characters_table(self):
        """Refresh characters table"""
        if not self.parent_app or not hasattr(self.parent_app, 'custom_characters'):
            return
        
        try:
            self.characters_table.itemChanged.disconnect(self.on_character_name_changed)
        except:
            pass
        
        self.characters_table.setRowCount(0)
        
        for idx, (char_name, img_path) in enumerate(self.parent_app.custom_characters.items(), 1):
            row = self.characters_table.rowCount()
            self.characters_table.insertRow(row)
            
            stt_item = QTableWidgetItem(str(idx))
            stt_item.setFlags(stt_item.flags() & ~Qt.ItemIsEditable)
            self.characters_table.setItem(row, 0, stt_item)
            
            name_item = QTableWidgetItem(char_name)
            name_item.setData(Qt.UserRole, char_name)
            self.characters_table.setItem(row, 1, name_item)
            
            path_item = QTableWidgetItem(str(img_path))
            path_item.setFlags(path_item.flags() & ~Qt.ItemIsEditable)
            self.characters_table.setItem(row, 2, path_item)
            
            btn_delete = QPushButton("Xóa")
            btn_delete.setFixedSize(60, 25)
            btn_delete.clicked.connect(lambda checked, name=char_name: self.on_delete_character(name))
            self.characters_table.setCellWidget(row, 3, btn_delete)
        
        self.characters_table.itemChanged.connect(self.on_character_name_changed)
        self.lbl_char_count.setText(f"Đã import: {len(self.parent_app.custom_characters)}/10 nhân vật")
    
    def on_delete_character(self, char_name):
        """Xóa character"""
        if not self.parent_app:
            return
        self.parent_app.on_delete_character(char_name)
        self.refresh_characters_table()
        self.refresh_matching_summary()
    
    def refresh_matching_summary(self):
        """Refresh summary label"""
        if not self.parent_app or not hasattr(self.parent_app, 'character_matching_results'):
            self.lbl_matching_summary.setText("Chưa có kết quả matching")
            return
        
        results = self.parent_app.character_matching_results
        if not results:
            self.lbl_matching_summary.setText("Chưa có kết quả matching")
            return
        
        total = len(results)
        with_chars = sum(1 for chars in results.values() if chars)
        summary_text = f"✅ {total} prompts, {with_chars} prompts có characters được match"
        self.lbl_matching_summary.setText(summary_text)
    
    def refresh_matching_table(self):
        """Refresh matching table - DEPRECATED: dùng refresh_matching_summary thay thế"""
        # Method này không còn dùng nữa vì không có matching_table trong CustomIntegrateDialog
        # Chỉ giữ lại để tránh lỗi khi có code cũ gọi
        self.refresh_matching_summary()
    
    def on_matching_table_changed(self, item):
        """Xử lý khi user chỉnh sửa prompt trong matching table"""
        if not self.parent_app or item.column() != 1:
            return
        try:
            row = item.row()
            prompt_idx_item = self.matching_table.item(row, 0)
            if not prompt_idx_item:
                return
            prompt_idx = int(prompt_idx_item.text())
            new_prompt = item.text()
            # Lưu prompt mới vào parent (có thể cần lưu vào file hoặc instance variable)
            if hasattr(self.parent_app, 'custom_prompts'):
                self.parent_app.custom_prompts[prompt_idx] = new_prompt
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"✅ Đã cập nhật prompt {prompt_idx}: {new_prompt[:50]}...")
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"❌ Lỗi update prompt: {e}")
    
    def on_character_checkbox_changed(self, char_name, prompt_idx, state):
        """Xử lý khi user check/uncheck character"""
        if not self.parent_app:
            return
        try:
            # Lấy danh sách characters hiện tại cho prompt này
            matched_chars = self.parent_app.character_matching_results.get(prompt_idx, []).copy()
            
            if state == Qt.Checked:
                # Thêm character nếu chưa có và chưa đạt tối đa 3
                if char_name not in matched_chars and len(matched_chars) < 3:
                    matched_chars.append(char_name)
                elif len(matched_chars) >= 3:
                    # Đã đạt tối đa, không cho thêm
                    QMessageBox.warning(self, "Cảnh báo", "Tối đa 3 characters mỗi prompt!")
                    # Uncheck lại
                    for row in range(self.matching_table.rowCount()):
                        widget = self.matching_table.cellWidget(row, 2)
                        if widget and widget.property('prompt_idx') == prompt_idx:
                            checkboxes = widget.property('checkboxes')
                            if checkboxes and char_name in checkboxes:
                                checkboxes[char_name].setChecked(False)
                            break
                    return
            else:
                # Bỏ character
                if char_name in matched_chars:
                    matched_chars.remove(char_name)
            
            # Cập nhật matching results
            self.parent_app.character_matching_results[prompt_idx] = matched_chars
            
            # Enable/disable các checkbox khác dựa trên số lượng đã chọn
            for row in range(self.matching_table.rowCount()):
                widget = self.matching_table.cellWidget(row, 2)
                if widget and widget.property('prompt_idx') == prompt_idx:
                    checkboxes = widget.property('checkboxes')
                    if checkboxes:
                        selected_count = len(matched_chars)
                        for name, chk in checkboxes.items():
                            if name not in matched_chars and selected_count >= 3:
                                chk.setEnabled(False)
                            else:
                                chk.setEnabled(True)
                    break
            
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"✅ Prompt {prompt_idx}: {len(matched_chars)} characters ({', '.join(matched_chars) if matched_chars else 'Không có'})")
        except Exception as e:
            if hasattr(self.parent_app, 'log'):
                self.parent_app.log(f"❌ Lỗi update character: {e}")
    
    def on_add_character_to_prompt(self, prompt_idx):
        """Thêm character vào prompt (dialog để chọn)"""
        if not self.parent_app:
            return
        # Tìm character chưa được chọn
        matched_chars = self.parent_app.character_matching_results.get(prompt_idx, [])
        if len(matched_chars) >= 3:
            QMessageBox.warning(self, "Cảnh báo", "Tối đa 3 characters mỗi prompt!")
            return
        
        available_chars = [name for name in self.parent_app.custom_characters.keys() if name not in matched_chars]
        if not available_chars:
            QMessageBox.information(self, "Thông báo", "Đã chọn hết characters!")
            return
        
        # Hiện dialog chọn character (đơn giản: chọn character đầu tiên chưa được chọn)
        char_to_add = available_chars[0]
        matched_chars.append(char_to_add)
        self.parent_app.character_matching_results[prompt_idx] = matched_chars
        self.refresh_matching_table()
    
    def on_remove_character_from_prompt(self, prompt_idx):
        """Bỏ character khỏi prompt"""
        if not self.parent_app:
            return
        matched_chars = self.parent_app.character_matching_results.get(prompt_idx, [])
        if not matched_chars:
            return
        
        # Bỏ character cuối cùng
        matched_chars.pop()
        self.parent_app.character_matching_results[prompt_idx] = matched_chars
        self.refresh_matching_table()
    
    def accept(self):
        """Override accept để save data"""
        self.save_data_to_parent()
        super().accept()


class AdPopupDialog(QDialog):
    """Popup quảng cáo - Hiển thị ảnh full popup từ Supabase"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📢 Quảng Cáo")
        self.setModal(False)  # Non-modal - không block UI
        
        # ✅ RESPONSIVE - Kích thước theo màn hình và parent window
        if parent:
            parent_width = parent.width()
            parent_height = parent.height()
            self.window_width = min(int(parent_width * 0.85), 1200)
            self.window_height = min(int(parent_height * 0.85), 900)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.window_width = min(int(screen.width() * 0.7), 1100)
            self.window_height = min(int(screen.height() * 0.7), 800)
        
        self.setFixedSize(self.window_width, self.window_height)
        
        # Window flags
        self.setWindowFlags(
            Qt.Dialog | 
            Qt.FramelessWindowHint
        )
        
        # Nền đen với border
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 0.98);
                border: 3px solid #ffd700;
                border-radius: 15px;
            }
        """)
        
        self.ad_image_url = None
        self.init_ui()
    
    def fetch_random_ad_image(self):
        """Lấy random một ảnh quảng cáo từ Supabase"""
        try:
            import requests
            import random
            
            # ✅ Lấy tất cả ảnh quảng cáo active từ Supabase
            supabase_url = "https://snkrixiuryophtxamixu.supabase.co"
            supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNua3JpeGl1cnlvcGh0eGFtaXh1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDU1MTE3NTYsImV4cCI6MjA2MTA4Nzc1Nn0.aDxeneo2LoJLmEK3RZZ6dUhVLmYN5cCdZBaE7mtFe00"
            
            headers = {
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json"
            }
            
            # Query lấy tất cả ảnh active
            response = requests.get(
                f"{supabase_url}/rest/v1/ad_images?is_active=eq.true&select=*",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                images = response.json()
                if images and len(images) > 0:
                    # Random chọn 1 ảnh
                    selected = random.choice(images)
                    return selected.get('image_url')
            
            return None
            
        except Exception as e:
            print(f"❌ Lỗi fetch ad image: {e}")
            return None
    
    def init_ui(self):
        """Initialize popup UI - Full ảnh quảng cáo"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Container chính
        container = QFrame()
        container.setStyleSheet("background: transparent;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        container_layout.setSpacing(0)
        
        # Nút đóng (X) ở góc trên phải - overlay
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(45, 45)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 0, 0, 0.7);
                color: white;
                border: 2px solid rgba(255, 255, 255, 0.5);
                border-radius: 22px;
                font-size: 22px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 0, 0, 0.9);
                border: 2px solid rgba(255, 0, 0, 1);
            }
        """)
        close_btn.clicked.connect(self.close)
        
        # Header layout với nút đóng
        header_layout = QHBoxLayout()
        header_layout.addStretch()
        header_layout.addWidget(close_btn)
        container_layout.addLayout(header_layout)
        
        # ✅ Label hiển thị ảnh full
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("""
            background: transparent;
            border-radius: 10px;
        """)
        self.image_label.setMinimumSize(self.window_width - 20, self.window_height - 70)
        
        # Fetch và hiển thị ảnh từ Supabase
        self.load_ad_image()
        
        container_layout.addWidget(self.image_label, 1)
        main_layout.addWidget(container)
    
    def load_ad_image(self):
        """Load ảnh quảng cáo từ Supabase"""
        try:
            import requests
            
            # Lấy URL ảnh random từ Supabase
            image_url = self.fetch_random_ad_image()
            
            if image_url:
                self.ad_image_url = image_url
                
                # Tải ảnh từ URL
                response = requests.get(image_url, timeout=15)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    
                    if not pixmap.isNull():
                        # Scale ảnh để fit full popup (giữ tỷ lệ)
                        max_width = self.window_width - 30
                        max_height = self.window_height - 80
                        
                        scaled_pixmap = pixmap.scaled(
                            max_width, max_height,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        )
                        self.image_label.setPixmap(scaled_pixmap)
                        return
            
            # Fallback nếu không có ảnh từ Supabase
            self.show_fallback_content()
            
        except Exception as e:
            print(f"❌ Lỗi load ad image: {e}")
            self.show_fallback_content()
    
    def show_fallback_content(self):
        """Hiển thị nội dung fallback khi không có ảnh"""
        self.image_label.setText(
            "<div style='text-align: center; color: #ffd700; font-size: 24px;'>"
            "<p style='font-size: 48px; margin-bottom: 20px;'>📢</p>"
            "<p style='font-weight: bold; margin-bottom: 15px;'>QUẢNG CÁO</p>"
            "<p style='font-size: 18px; color: white;'>Ủng hộ shop để không hiện quảng cáo!</p>"
            "<p style='font-size: 16px; color: rgba(255,255,255,0.8); margin-top: 20px;'>"
            "Liên hệ Admin qua Zalo để biết thêm chi tiết"
            "</p>"
            "</div>"
        )
        self.image_label.setTextFormat(Qt.RichText)
        self.image_label.setStyleSheet("""
            background: rgba(255, 215, 0, 0.1);
            border: 2px dashed #ffd700;
            border-radius: 15px;
            padding: 50px;
        """)
    
    def closeEvent(self, event):
        """Override close event để cleanup"""
        event.accept()
