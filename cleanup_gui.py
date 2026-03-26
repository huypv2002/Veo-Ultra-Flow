"""
Script to remove dead code blocks from gui_app_mac.py.
Removes methods belonging to deleted tabs: Edit, Sync, Rewrite, Script Writing, 
Image Extraction, Clone Videos.
"""
import re

with open("gui_app_mac.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Methods/classes to REMOVE (exact method names)
REMOVE_METHODS = {
    # FrameExtractionWorker class
    "class FrameExtractionWorker",
    
    # Edit tab build
    "def build_edit_tab_content",
    "def build_edit_left_panel",
    "def build_edit_right_panel",
    "def force_update_edit_ui",
    "def enable_all_edit_features",
    "def limit_edit_features",
    "def rebuild_full_edit_interface",
    "def fix_edit_tab_layout",
    
    # Sync tab build
    "def build_sync_tab_content",
    "def build_sync_left_panel",
    "def build_sync_middle_panel",
    "def build_sync_right_panel",
    
    # Rewrite tab build
    "def build_rewrite_tab_content",
    
    # Script Writing tab build
    "def build_script_writing_tab_content",
    "def build_stage4_prompt_tab",
    
    # Image Extraction tab build
    "def build_image_extraction_tab_content",
    
    # Clone Videos tab build
    "def build_clone_videos_tab_content",
    
    # Stage4 (Script Writing) handlers
    "def _update_stage4_generate_state",
    "def on_stage4_select_script_file",
    "def _load_stage4_script_file",
    "def on_stage4_select_character_file",
    "def _load_stage4_character_file",
    "def _set_stage4_generating",
    "def _parse_stage4_text_script",
    "def _extract_stage4_section",
    "def _build_stage4_topic_text",
    "def _stage4_get_profile_field",
    "def _summarize_character_profile",
    "def _format_stage4_dialogue",
    "def _compose_stage4_prompt",
    "def _stage4_on_ai_prompts_ready",
    "def _stage4_on_ai_error",
    "def _extract_stage4_ai_title",
    "def _extract_stage4_ai_characters",
    "def on_stage4_generate_prompts",
    "def on_stage4_export_prompts",
    "def _stage4_prompt_to_record",
    
    # Script Writing handlers (story manager)
    "def on_setup_mode_changed",
    "def on_speech_changed",
    "def on_start_project_setup",
    "def on_add_character",
    "def on_load_character_from_file",
    "def on_delete_character",
    "def on_save_character_to_file",
    "def on_export_character",
    "def update_character_combo",
    "def on_character_selected",
    "def on_browse_profile_file",
    "def on_import_profile",
    "def on_save_character_profile",
    "def on_query_character",
    "def on_add_story_log",
    "def refresh_story_log_display",
    "def on_generate_type_changed",
    "def _set_generate_script_button_state",
    "def on_generate_script",
    "def _on_generate_script_finished",
    "def _on_generate_script_error",
    "def display_scene_cards",
    "def create_scene_card",
    "def on_export_script",
    
    # Image Extraction handlers
    "def on_extraction_mode_changed",
    "def browse_extraction_video_file",
    "def get_extraction_video_info",
    "def get_extraction_video_duration_sync",
    "def get_extraction_detailed_video_info",
    "def find_extraction_tool",
    "def browse_extraction_folder",
    "def browse_extraction_output_dir",
    "def on_extraction_interval_changed",
    "def on_start_extraction",
    "def start_batch_extraction",
    "def process_next_batch_video",
    "def on_stop_extraction",
    "def on_open_extraction_output_folder",
    "def update_extraction_progress",
    "def on_extraction_finished",
    "def clear_extraction_logs",
    "def export_extraction_logs",
    "def extraction_log",
    
    # Edit tab handlers
    "def on_edit_add_videos",
    "def on_edit_add_folder",
    "def on_edit_select_all",
    "def on_edit_deselect_all",
    "def on_edit_remove_selected",
    "def on_edit_move_selected",
    "def on_edit_random_order",
    "def refresh_edit_video_list",
    "def on_edit_choose_bgm",
    "def on_edit_choose_output",
    "def on_fill_duration_from_bgm",
    "def on_edit_run",
    "def on_edit_cancel",
    "def edit_log",
    "def probe_duration_seconds",
    "def find_tool",
    "def edit_worker",
    "def finalize_edit",
    
    # Sync tab handlers
    "def on_sync_script_changed_debounced",
    "def on_sync_script_changed",
    "def on_sync_total_secs_changed",
    "def on_sync_choose_outdir",
    "def on_sync_export_json",
    "def on_sync_start",
    "def on_sync_start_t2v",
    "def on_sync_refresh_preview",
    "def on_sync_open_output_folder",
    "def on_sync_play_video",
    "def _initialize_sync_tab",
    "def _do_initialize_sync_tab",
    "def toggle_manual_controls",
    "def on_sync_complete_workflow",
    "def _complete_workflow_worker_wrapper",
    "def _complete_workflow_worker",
    "def _create_integrate_videos_sync",
    "def _process_single_video_file_sync",
    "def _generate_single_integrate_video_sync",
    "def _download_integrate_video_sync",
    "def _concat_videos_sync",
    "def _poll_concat_status_sync",
    "def _decode_and_save_video",
    "def _upload_image_to_google_labs_background",
    "def _prepare_image_path_for_upload",
    "def on_sync_extract_characters",
    "def on_sync_upload_character_images",
    "def on_sync_auto_generate_all_characters",
    "def _upload_all_character_images_to_labs",
    "def _extract_characters_worker",
    "def _update_extracted_characters",
    "def _extract_characters_from_script",
    "def _call_gemini_api_wrapper",
    "def on_sync_generate_character_images",
    "def _generate_character_images_sync",
    "def _generate_character_images_worker",
    "def _extract_image_url_from_response",
    "def on_sync_generate_veo3_prompts",
    "def _generate_veo3_prompts_worker",
    "def _build_master_prompt",
    "def handleGenerateVeo3Script",
    "def _generate_single_veo3_batch",
    "def _clean_and_parse_json_response",
    "def on_sync_generate_prompts_new",
    "def _generate_prompts_with_character_definitions_worker",
    "def on_sync_view_character_image",
    "def _handle_sync_log_message",
    "def _handle_update_progress_bar",
    "def _handle_show_upload_dialog",
    "def _handle_show_review_dialog",
    "def _show_prompt_review_dialog",
    "def _handle_update_prompts_table",
    "def sync_log",
    "def _sync_parse_script_lines",
    "def _sync_log_header",
    "def _sync_log_step",
    "def _sync_log_success",
    "def _sync_log_error",
    "def _sync_log_warning",
    "def _sync_log_info",
    "def _clear_old_workflow_data",
    "def _update_character_tree",
    "def _show_image_generation_choice_dialog",
    "def _show_character_upload_dialog",
    "def _show_character_upload_dialog_sync",
    "def reset_start_button_to_normal",
    
    # Rewrite tab handlers
    "def _rewrite_log",
    "def _handle_rewrite_log_message",
    "def _handle_update_rewrite_subtitle_ui",
    "def _handle_update_rewrite_rewritten_ui",
    "def on_rewrite_get_subtitle",
    "def _extract_rewrite_video_id",
    "def _get_rewrite_subtitle_worker",
    "def _build_rewrite_fake_cookie_string",
    "def _build_rewrite_cookie_dict",
    "def _extract_rewrite_subtitle_text",
    "def on_rewrite_script",
    "def _rewrite_script_worker",
    "def _format_rewrite_output",
    "def _create_rewrite_prompt",
    "def _call_rewrite_gemini_api",
    "def _extract_prompts_only",
    "def on_rewrite_copy_to_clipboard",
}

def find_method_end(lines, start_idx, is_class=False):
    """Find the end line of a method/class starting at start_idx."""
    if is_class:
        indent = 0
    else:
        line = lines[start_idx]
        indent = len(line) - len(line.lstrip())
    
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        
        if not stripped or stripped.startswith('#'):
            continue
        
        current_indent = len(line) - len(line.lstrip())
        
        if is_class:
            if current_indent == 0 and (stripped.startswith('class ') or stripped.startswith('def ')):
                return i
        else:
            if current_indent <= indent:
                return i
    
    return len(lines)

# Build list of (start, end) ranges to remove
remove_ranges = []

for i, line in enumerate(lines):
    stripped = line.strip()
    for pattern in REMOVE_METHODS:
        if pattern.startswith("class "):
            class_name = pattern.replace("class ", "")
            if stripped.startswith(f"class {class_name}"):
                end = find_method_end(lines, i, is_class=True)
                remove_ranges.append((i, end))
                break
        elif pattern.startswith("def "):
            method_name = pattern.replace("def ", "")
            if stripped.startswith(f"def {method_name}(") or stripped.startswith(f"def {method_name} ("):
                end = find_method_end(lines, i, is_class=False)
                remove_ranges.append((i, end))
                break

# Sort and merge overlapping ranges
remove_ranges.sort()
merged = []
for start, end in remove_ranges:
    if merged and start <= merged[-1][1]:
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    else:
        merged.append((start, end))

# Build set of lines to remove
remove_lines = set()
for start, end in merged:
    for i in range(start, end):
        remove_lines.add(i)

# Count removed
print(f"Total lines: {len(lines)}")
print(f"Lines to remove: {len(remove_lines)}")
print(f"Remaining lines: {len(lines) - len(remove_lines)}")
print(f"\nRemoved ranges ({len(merged)}):")
for start, end in merged:
    print(f"  Lines {start+1}-{end}: ({end-start} lines) {lines[start].strip()[:80]}")

# Write output
output_lines = [line for i, line in enumerate(lines) if i not in remove_lines]

with open("gui_app_mac.py", "w", encoding="utf-8") as f:
    f.writelines(output_lines)

print(f"\nDone! New file has {len(output_lines)} lines")
