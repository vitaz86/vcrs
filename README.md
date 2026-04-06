# VCS Recording Auto-Mover

Cross-platform tray application that monitors conferencing recording folders and automatically moves completed files.

## Setup

1. Create and activate a Python 3.11+ environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run:
   ```bash
   python main.py
   ```

On first launch, config and logs are stored in `~/.vcs_automover/`.

## Configuration

- Rules are stored in `~/.vcs_automover/config.json`.
- Sample `config.json` is included in this repository.
- Rule fields:
  - `name`
  - `source_folder`
  - `destination_folder`
  - `extensions`
  - `move_mode` (`wait_for_stable` or `immediate`)
  - `delete_source_folder`
  - `delete_delay_seconds`
  - `enabled`

## Tray Menu

- Open Settings
- View Log
- Pause / Resume
- Exit

## Settings UI

- Shows all rules in a table.
- Add/Edit/Delete rules.
- Save writes config and restarts watchers immediately.
- Includes startup registration toggle:
  - Windows: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
  - macOS: `~/Library/LaunchAgents/com.vcs.automover.plist`
  - Linux: `~/.config/autostart/vcs-automover.desktop`

## Logs

Daily log files are written to:

`~/.vcs_automover/logs/log_YYYY-MM-DD.txt`
