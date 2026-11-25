#!/usr/bin/env bash
set -uo pipefail

workspace=$(cd "$(dirname "$0")/.." && pwd)
repo_root=$(cd "$workspace/.." && pwd)
manifest=${AETHER_QUALIFICATION_MANIFEST:-"$workspace/tests/differential.tsv"}
legacy_python=${AETHER_LEGACY_PYTHON:-"$repo_root/.venv/bin/python"}

echo "historical differential: NON-NORMATIVE opt-in mode"
echo "historical differential: results never contribute to compiler-next qualification"

if [[ ! -x "$legacy_python" ]]; then
    echo "historical differential infrastructure error: Python is not executable: $legacy_python" >&2
    exit 2
fi
if [[ ! -r "$manifest" ]]; then
    echo "historical differential infrastructure error: manifest is not readable: $manifest" >&2
    exit 2
fi

probe_output=$(
    cd "$repo_root" && "$legacy_python" -c 'import aether.cli' 2>&1
)
probe_status=$?
if [[ $probe_status -ne 0 ]]; then
    echo "historical differential infrastructure error: cannot import aether.cli" >&2
    [[ -n "$probe_output" ]] && printf '%s\n' "$probe_output" >&2
    exit 2
fi

failures=0
checked=0

while IFS=$'\t' read -r id class current_result legacy_result source extra; do
    [[ -z "$id" || "$id" == \#* || "$legacy_result" == "n/a" ]] && continue
    checked=$((checked + 1))

    if [[ -z "$class" || -z "$current_result" || -z "$source" || -n "$extra" ]]; then
        echo "$id: FAIL malformed historical row" >&2
        failures=$((failures + 1))
        continue
    fi

    source_path="$workspace/tests/$source"
    if [[ ! -r "$source_path" ]]; then
        echo "$id: FAIL historical source is not readable: $source_path" >&2
        failures=$((failures + 1))
        continue
    fi

    output=$(
        cd "$repo_root" && "$legacy_python" -m aether.cli "$source_path" 2>&1
    )
    legacy_status=$?

    case "$legacy_result" in
        accept:*)
            expected=${legacy_result#accept:}
            if [[ ! "$expected" =~ ^[0-9]+$ ]]; then
                echo "$id: FAIL invalid historical expectation: $legacy_result" >&2
                failures=$((failures + 1))
            elif [[ $legacy_status -ne $expected ]]; then
                echo "$id: historical observation changed: legacy=$legacy_status expected=$expected; no compiler-next defect is implied [$class]" >&2
                [[ -n "$output" ]] && printf '%s\n' "$output" >&2
                failures=$((failures + 1))
            else
                echo "$id: historical PASS current-contract=$current_result legacy=$legacy_status [$class]"
            fi
            ;;
        reject*)
            if [[ $legacy_status -eq 0 ]]; then
                echo "$id: historical observation changed: legacy accepted but expected rejection; no compiler-next defect is implied [$class]" >&2
                failures=$((failures + 1))
            else
                echo "$id: historical PASS current-contract=$current_result legacy=reject(status=$legacy_status) [$class]"
            fi
            ;;
        *)
            echo "$id: FAIL unknown historical expectation: $legacy_result" >&2
            failures=$((failures + 1))
            ;;
    esac
done < "$manifest"

echo "historical differential: non_normative=true checked=$checked failures=$failures"
[[ $failures -eq 0 ]]
