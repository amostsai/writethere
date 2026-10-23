"""Create a relocatable-at-install-time launcher in the project folder."""

from pathlib import Path
import argparse
import os
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]


def exec_quote(value):
    # Desktop Entry Exec escaping, including the field-code escape for percent.
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"'


launcher = root / "手機手寫板.desktop"
launcher.write_text("\n".join([
    "[Desktop Entry]", "Version=1.0", "Type=Application", "Name=WriteThere",
    "Comment=手機掃碼輸入文字，自動貼到電腦",
    "Exec=" + exec_quote(root / "run.sh"),
    "Icon=" + str(root / "phone_pad/assets/icon.svg"),
    "Terminal=false", "Categories=Utility;Accessibility;", "StartupNotify=true",
    "StartupWMClass=tw.local.PhoneHandwritingPad", "",
]))
launcher.chmod(0o755)

parser = argparse.ArgumentParser(description="產生手機手寫板啟動圖示")
parser.add_argument("--install", action="store_true", help="安裝到使用者的應用程式列表與桌面")
args = parser.parse_args()
if args.install:
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    applications = data_home / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    shutil.copy2(launcher, applications / "tw.local.PhoneHandwritingPad.desktop")
    desktop_result = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, check=True)
    desktop = Path(desktop_result.stdout.strip())
    if desktop.is_dir() and desktop != Path.home():
        destination = desktop / launcher.name
        shutil.copy2(launcher, destination)
        # GNOME uses this per-file flag for desktop launcher trust.
        subprocess.run(["gio", "set", str(destination), "metadata::trusted", "true"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(applications)], check=False)
