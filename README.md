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
- Sample config includes Zoom, Telemost, and Kontur Talk (`KTalk`) rules.
- All default rules are disabled initially; enable needed ones in Settings.
- Supported interface languages: English and Russian (switch in Settings).
- Each rule can transfer files either to a local destination folder or to S3-compatible object storage.

Rule fields:
- `zoom_conversion_timeout_seconds` (global, default `1200` seconds for forced Zoom conversion launch)
- `name`
- `source_folder`
- `destination_folder`
- `transfer_target` (`folder` or `s3`)
- `s3_endpoint_url` (for example `https://s3.amazonaws.com` or a provider endpoint)
- `s3_bucket_name`
- `s3_access_key`
- `s3_secret_key`
- `s3_region` (optional, defaults to `us-east-1`)
- `extensions`
- `move_mode` (`wait_for_stable` or `immediate`)
- `delete_source_folder`
- `delete_delay_seconds`
- `enabled`

For S3 transfers, files are uploaded to:

`s3://<bucket>/New/<recording-folder>/<file>`

The app does not list S3 bucket contents; it only uploads completed files. S3 credentials are stored in `~/.vcs_automover/config.json`, so protect that file like any other credentials file.

## Tray Menu

- Open Settings
- View Log
- Pause / Resume
- Exit

## Settings UI

- Shows all rules in a table.
- Add/Edit/Delete rules.
- Double-click any rule row to open Edit.
- Windows paths are shown with backslashes in UI fields for easy copy/paste.
- Transfer target selector supports local folder moves and S3-compatible uploads.
- Save writes config and restarts watchers immediately.
- Includes startup registration toggle:
  - Windows: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
  - macOS: `~/Library/LaunchAgents/com.vcs.automover.plist`
  - Linux: `~/.config/autostart/vcs-automover.desktop`

## Logs

Daily log files are written to:

`~/.vcs_automover/logs/log_YYYY-MM-DD.txt`
