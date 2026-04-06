## VCS Recording Auto-Mover

Cross-platform system-tray app that monitors video conference recording folders and automatically moves completed files into configured destinations (Yandex Disk, Dropbox, or any local path).

### Requirements

- Python **3.11+**

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
python main.py
```

On first run, configuration is stored at `~/.vcs_automover/config.json` and logs are written to `~/.vcs_automover/logs/log_YYYY-MM-DD.txt` (UTC timestamps).

### Configure rules

- Use the tray menu **Open Settings**
- Add/Edit rules:
  - **Source folder**: where recordings appear (Zoom/Telemost root)
  - **Destination folder**: where files should be moved
  - **Extensions**: comma-separated list (e.g. `.mp4, .m4a`)
  - **Move mode**: `wait_for_stable` or `immediate` (both still perform a stability check)
  - **Delete source subfolder** and **Delete delay** control cleanup after moves
- Click **Save** to write config and restart watchers immediately

### Startup entry

In Settings, toggle **Run at startup**:

- **Windows**: writes to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (no admin rights)
- **Linux**: creates `~/.config/autostart/vcs_automover.desktop`
- **macOS**: creates `~/Library/LaunchAgents/vcs_automover.plist`

