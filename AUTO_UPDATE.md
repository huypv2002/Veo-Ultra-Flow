# Auto-Update System Documentation

## Overview

This document describes the auto-update system used in Veo3-Ultra application. The system checks GitHub Releases for new versions, downloads updates, and applies them automatically while preserving user data.

## Components

### 1. Version File (`src/core/version.py`)

Simple text file containing the current version number:

```
2.0
```

### 2. Updater Module (`src/core/updater.py`)

The core auto-update functionality with three main classes:

- **`UpdateChecker`** - Checks GitHub Releases API for new versions (runs in background thread)
- **`UpdateDownloader`** - Downloads ZIP file and extracts it to temp directory
- **`apply_update()`** - Creates batch script to replace old files with new ones

### 3. Update Dialog (`src/gui/update_dialog.py`)

PySide6 UI components:
- **`UpdateDialog`** - Modal dialog showing update info, release notes, and download progress
- **`UpdateButton`** - Toolbar button showing when update is available

## Configuration

Edit these constants in `src/core/updater.py`:

```python
# ============================================================
# CẤU HÌNH — SỬA CHO PHÙ HỢP PROJECT CỦA BÂN
# ============================================================
GITHUB_OWNER = "huypv2002"           # GitHub username/organization
GITHUB_REPO = "Veo-Ultra-Flow"       # Repository name
ASSET_NAME = "Veo3-Ultra-windows.zip" # Name of the ZIP asset in release
EXE_NAME = "Veo3-Ultra.exe"          # Executable name
# ============================================================
```

## How It Works

### Step 1: Check for Updates

```python
from src.core.updater import UpdateChecker

# Create checker thread
checker = UpdateChecker()
checker.result.connect(on_update_checked)
checker.start()
```

The checker calls GitHub API:
```
https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest
```

### Step 2: Download Update

```python
from src.core.updater import UpdateDownloader

downloader = UpdateDownloader(download_url)
downloader.progress.connect(on_progress)
downloader.finished.connect(on_finished)
downloader.start()
```

The downloader:
1. Creates `_update_tmp` folder in app directory
2. Downloads ZIP file in 64KB chunks
3. Extracts ZIP to temp folder
4. Locates the EXE file in extracted folder

### Step 3: Apply Update

```python
from src.core.updater import apply_update

apply_update(new_app_dir)  # Path to extracted app folder
```

The function:
1. Creates `_updater.bat` batch script
2. Launches it with `CREATE_NEW_CONSOLE` flag
3. Exits current app with `os._exit(0)`

The batch script:
1. Waits for old process to close (max 30 seconds)
2. Deletes old files (except `data/`, `output/`, `_update_tmp/`)
3. Copies new files from extracted folder
4. Starts new version
5. Deletes itself

## Important Notes

### Windows-Specific Behavior

- **DO NOT use `DETACHED_PROCESS`** when launching the batch script
- **Always use `CREATE_NEW_CONSOLE`** - this allows the batch to run properly
- Use `os._exit(0)` instead of `sys.exit(0)` to force kill all threads

### Preserving User Data

The update process preserves these folders:
- `data/` - User accounts, settings, cookies
- `output/` - Generated files

### Release Asset Requirements

The GitHub Release must contain:
- A tag matching pattern `v*` (e.g., `v1.0`, `v2.0`)
- A ZIP asset with the exact name configured in `ASSET_NAME`

## Integration Example

```python
from PySide6.QtWidgets import QApplication
from src.core.updater import UpdateChecker, UpdateDownloader, apply_update
from src.gui.update_dialog import UpdateDialog

class MyApp:
    def __init__(self):
        self.downloader = None
        self.dialog = None
    
    def check_for_updates(self):
        checker = UpdateChecker()
        checker.result.connect(self._on_update_checked)
        checker.start()
    
    def _on_update_checked(self, has_update, tag, url, notes, error):
        if has_update:
            # Show dialog
            self.dialog = UpdateDialog(tag, notes)
            self.dialog.update_requested.connect(lambda: self._start_download(url))
            self.dialog.exec()
    
    def _start_download(self, url):
        self.dialog.set_downloading(True)
        self.downloader = UpdateDownloader(url)
        self.dialog.connect(self.downloader.progress, self.dialog.set_progress)
        self.downloader.finished.connect(self._on_download_finished)
        self.downloader.start()
    
    def _on_download_finished(self, ok, new_app_dir):
        if ok:
            self.dialog.set_ready_to_install()
            apply_update(new_app_dir)
        else:
            self.dialog.set_error(new_app_dir)  # Error message
```

## GitHub Workflow for Building

Create `.github/workflows/build.yml`:

```yaml
name: Build Windows EXE

on:
  push:
    tags: ['v*']
  workflow_dispatch:

jobs:
  build-windows:
    runs-on: windows-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      
      - name: Install dependencies
        run: |
          pip install PySide6 requests httpx playwright nuitka ...
      
      - name: Build with Nuitka
        run: |
          python -m nuitka --standalone --windows-console-mode=disable ...
      
      - name: Create ZIP
        run: |
          Compress-Archive -Path "app-folder" -DestinationPath "YOUR-APP-windows.zip"
      
      - name: Upload Release
        uses: softprops/action-gh-release@v1
        with:
          files: YOUR-APP-windows.zip
```

## Troubleshooting

### "httpx not installed"
Install httpx: `pip install httpx`

### "HTTP 404"
Check that:
- Repository exists and is public
- Tag exists on GitHub
- Release has an asset with correct name

### "Cannot find EXE in ZIP"
Ensure the ZIP structure contains the EXE file at:
```
ZIP/
  YourApp/
    YourApp.exe
```
Or the EXE is directly in the root of ZIP.

### Update fails silently
Check `updater.log` in app directory for detailed error messages.

### Batch script doesn't run
- Ensure antivirus isn't blocking `.bat` files
- Check that app has write permissions to its directory
