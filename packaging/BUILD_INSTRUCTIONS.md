# Building "AI Trader Pro Setup.exe"

The app itself (Python + customtkinter + the live data API) is fully
cross-platform-buildable, but the **final `.exe` installer can only be
produced on Windows** (or a Windows CI runner) -- PyInstaller builds a
native binary for whatever OS it's run on, and Inno Setup is a Windows
tool. There are two ways to get your `Setup.exe`:

## Option A -- Build automatically with GitHub Actions (no Windows PC needed)

1. Push this project to a GitHub repo.
2. Go to the **Actions** tab -> "Build Windows Setup.exe" -> **Run workflow**.
3. When it finishes, download the `AI-Trader-Pro-Setup` artifact -- that's
   your `AI Trader Pro Setup.exe`, built fresh on a real Windows machine.

(The workflow file is at `.github/workflows/build-windows-installer.yml`;
it also re-runs automatically on every push to `main` if you want it kept
up to date.)

## Option B -- Build it yourself on a Windows PC

1. Install Python 3.12 and Git.
2. `pip install -r requirements.txt`
3. `pyinstaller packaging/AI_Trader_Pro.spec --noconfirm`
   -> produces `dist/AI Trader Pro/AI Trader Pro.exe` and its supporting files.
4. Install [Inno Setup](https://jrsoftware.org/isinfo.php) (free).
5. Compile `packaging/installer.iss` (open it in the Inno Setup IDE and
   click **Build**, or run `ISCC.exe packaging\installer.iss` from a
   command prompt).
   -> produces `packaging/output/AI Trader Pro Setup.exe`.

## What the installer does

- Installs the app to `Program Files\AI Trader Pro` (no admin rights
  required -- per-user install).
- Adds a Start Menu shortcut and optional desktop icon.
- Ships `.env.example` (never a real API key) so the user knows to copy
  it to `.env` and paste in their own Twelve Data / Finnhub / Alpha
  Vantage key before first launch.
- The resulting app needs **only an internet connection** to run --
  no MetaTrader 5, no Python install, on any Windows PC.

## Notes

- `MetaTrader5` is explicitly excluded in the PyInstaller spec -- it's
  no longer a dependency anywhere in the codebase.
- If you add an app icon, drop an `app_icon.ico` file into `assets/`;
  the spec picks it up automatically.
