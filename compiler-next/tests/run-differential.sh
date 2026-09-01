#!/usr/bin/env bash
set -uo pipefail

workspace=$(cd "$(dirname "$0")/.." && pwd)
repo_root=$(cd "$workspace/.." && pwd)
legacy_python=${AETHER_LEGACY_PYTHON:-"$repo_root/.venv/bin/python"}

cargo build --quiet --manifest-path "$workspace/Cargo.toml" -p aether-driver --bin aether-next || exit 1
next="$workspace/target/debug/aether-next"
failures=0
checked=0

while IFS=$'\t' read -r id class new_result legacy_result source; do
    [[ -z "$id" || "$id" == \#* || "$legacy_result" == "n/a" ]] && continue
    source_path="$workspace/tests/$source"

    "$next" run "$source_path" >/dev/null 2>&1
    new_status=$?
    if [[ "$new_result" == accept:* ]]; then
        expected=${new_result#accept:}
        if [[ $new_status -ne $expected ]]; then
            echo "$id: new=$new_status expected=$expected"
            failures=$((failures + 1))
        fi
    elif [[ "$new_result" == reject:* && $new_status -eq 0 ]]; then
        echo "$id: new unexpectedly accepted"
        failures=$((failures + 1))
    fi

    (
        cd "$repo_root" || exit 125
        "$legacy_python" -m aether.cli "$source_path" >/dev/null 2>&1
    )
    legacy_status=$?
    if [[ "$legacy_result" == accept:* ]]; then
        expected=${legacy_result#accept:}
        if [[ $legacy_status -ne $expected ]]; then
            echo "$id: legacy=$legacy_status expected=$expected"
            failures=$((failures + 1))
        fi
    elif [[ "$legacy_result" == reject* && $legacy_status -eq 0 ]]; then
        echo "$id: legacy unexpectedly accepted"
        failures=$((failures + 1))
    fi
    checked=$((checked + 1))
    echo "$id: new=$new_status legacy=$legacy_status [$class]"
done < "$workspace/tests/differential.tsv"

echo "differential: checked=$checked failures=$failures"
exit "$failures"
