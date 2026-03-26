"""
Worker signals dùng chung cho thread-safe communication giữa worker threads và UI.
"""

from PySide6.QtCore import Signal, QObject


class WorkerSignals(QObject):
    """Thread-safe signals for worker - PHẢI là QObject"""
    # General
    new_log = Signal(str)
    add_task = Signal(object, int)  # (task, index)
    update_status = Signal(int, str)  # (task_index, status)
    update_progress = Signal(int, int)  # (task_index, progress_percent)
    update_batch = Signal(int, int)  # (current, total)
    finished = Signal()

    # Subscription
    subscription_expired = Signal(str)
    subscription_warning = Signal(str, int)

    # Image Whisk tab
    update_image_status = Signal(int, str)
    update_image_path = Signal(int, str)
    update_image_progress = Signal(int, int, int)  # (index, current, total)
    create_image_card = Signal(int, str, int)  # (prompt_index, prompt_text, num_images)
    update_reference_image_preview_signal = Signal(str)

    # Video tab - Integrate / Extend
    matching_results_ready = Signal(dict, list)
    update_extend_project = Signal(str, int)
    update_extend_segment = Signal(str, int, int)

    # Flow (Banana Pro) tab
    flow_update_tile_status = Signal(int, str)
    flow_set_tile_image = Signal(int, str)
    flow_update_success_label = Signal(int)
    flow_update_status_text = Signal(str)
    flow_update_hint_text = Signal(str)
    flow_enable_run_button = Signal(bool)
    flow_start_next_batch = Signal()
    flow_worker_done = Signal(bool, object)
    show_flow_success_popup = Signal(int)
    flow_update_task_grid_status = Signal(int, str, str)
    flow_update_task_grid_preview = Signal(int, str)

    # Update
    show_update_available = Signal(object)
