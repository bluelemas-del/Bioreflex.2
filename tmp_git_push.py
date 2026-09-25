import os
import shutil
import subprocess
import sys

repo = r"C:\Users\as\OneDrive\Desktop\Bioreflex.2"
candidates = [
    r"C:\Program Files\Git\bin\git.exe",
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Users\as\AppData\Local\Programs\Git\bin\git.exe",
    r"C:\Users\as\AppData\Local\Programs\Git\cmd\git.exe",
]

git = next((p for p in candidates if os.path.exists(p)), shutil.which("git"))
if not git:
    print("GIT_NOT_FOUND")
    sys.exit(1)

print(f"GIT:{git}")
print("---STATUS---")
status = subprocess.run([git, "-C", repo, "status", "--short", "--branch"], capture_output=True, text=True)
print(status.stdout.strip() or "(no status output)")
if status.stderr.strip():
    print(status.stderr.strip())

print("---REMOTE---")
remote = subprocess.run([git, "-C", repo, "remote", "-v"], capture_output=True, text=True)
print(remote.stdout.strip() or "NO_REMOTE_CONFIGURED")
if remote.stderr.strip():
    print(remote.stderr.strip())

if not remote.stdout.strip():
    print("REMOTE_MISSING")
    sys.exit(2)

branches = subprocess.run([git, "-C", repo, "branch", "--format=%(refname:short)"], capture_output=True, text=True).stdout.splitlines()
print("---BRANCHES---")
print("\n".join(branches) if branches else "(none)")

if "main" in branches:
    print("---CHECKOUT MAIN---")
    checkout = subprocess.run([git, "-C", repo, "checkout", "main"], capture_output=True, text=True)
else:
    print("---CREATE MAIN---")
    checkout = subprocess.run([git, "-C", repo, "checkout", "-b", "main"], capture_output=True, text=True)
print(checkout.stdout.strip() or "(no checkout output)")
if checkout.stderr.strip():
    print(checkout.stderr.strip())

print("---PUSH---")
push = subprocess.run([git, "-C", repo, "push", "origin", "main"], capture_output=True, text=True)
print(push.stdout.strip() or "(no push output)")
if push.stderr.strip():
    print(push.stderr.strip())
print(f"EXIT:{push.returncode}")
raise SystemExit(push.returncode)
