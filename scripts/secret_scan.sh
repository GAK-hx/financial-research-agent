#!/usr/bin/env bash
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "secret scan requires a Git work tree" >&2
  exit 2
fi

pattern='sk-[A-Za-z0-9]{20,}|(MODEL_API_KEY|API_KEY|SECRET|TOKEN|PASSWORD)[[:space:]]*=[[:space:]]*[^<${[:space:]][^[:space:]]{7,}'
found=0

# Scan tracked files and, before the first commit, every non-ignored candidate file.
# This makes the guard useful immediately after `git init`, before anything is staged.
while IFS= read -r file; do
  case "$file" in
    scripts/secret_scan.sh|*.example) continue ;;
  esac
  if [ -f "$file" ] && LC_ALL=C grep -Iq . "$file"; then
    while IFS=: read -r line_number _; do
      [ -n "$line_number" ] || continue
      line=$(sed -n "${line_number}p" "$file")
      # References to an environment variable are injection instructions, not values.
      if printf '%s\n' "$line" | LC_ALL=C grep -Eq \
        '(MODEL_API_KEY|API_KEY|SECRET|TOKEN|PASSWORD)[[:space:]]*=[[:space:]]*["]?\$\{?[A-Z0-9_]+\}?["]?'; then
        continue
      fi
      # Never print the matching line: CI logs must not repeat a leaked credential.
      printf 'potential secret: %s:%s\n' "$file" "$line_number"
      found=1
    done < <(LC_ALL=C grep -nE "$pattern" "$file" || true)
  fi
done < <(git ls-files --cached --others --exclude-standard)

if [ "$found" -ne 0 ]; then
  echo "potential secret found in Git candidate files" >&2
  exit 1
fi

echo "Git candidate-file secret scan passed"
