#!/usr/bin/env bash
set -uo pipefail

workspace=$(cd "$(dirname "$0")/.." && pwd)
manifest=${AETHER_QUALIFICATION_MANIFEST:-"$workspace/tests/differential.tsv"}

if [[ -n "${AETHER_NEXT_BIN:-}" ]]; then
    next=$AETHER_NEXT_BIN
else
    cargo build --quiet --manifest-path "$workspace/Cargo.toml" \
        -p aether-driver --bin aether-next || exit 2
    next="$workspace/target/debug/aether-next"
fi

if [[ ! -x "$next" ]]; then
    echo "qualification infrastructure error: compiler-next driver is not executable: $next" >&2
    exit 2
fi
if [[ ! -r "$manifest" ]]; then
    echo "qualification infrastructure error: manifest is not readable: $manifest" >&2
    exit 2
fi

failures=0
checked=0

while IFS=$'\t' read -r id class current_result legacy_result source extra; do
    [[ -z "$id" || "$id" == \#* ]] && continue
    checked=$((checked + 1))

    if [[ -z "$class" || -z "$current_result" || -z "$legacy_result" || -z "$source" || -n "$extra" ]]; then
        echo "$id: FAIL malformed qualification row" >&2
        failures=$((failures + 1))
        continue
    fi

    source_path="$workspace/tests/$source"
    if [[ ! -r "$source_path" ]]; then
        echo "$id: FAIL source is not readable: $source_path" >&2
        failures=$((failures + 1))
        continue
    fi

    output=$("$next" run "$source_path" 2>&1)
    current_status=$?

    case "$current_result" in
        accept:*)
            expected=${current_result#accept:}
            if [[ ! "$expected" =~ ^[0-9]+$ ]]; then
                echo "$id: FAIL invalid current expectation: $current_result" >&2
                failures=$((failures + 1))
            elif [[ $current_status -ne $expected ]]; then
                echo "$id: FAIL compiler-next status=$current_status expected=$expected [$class]" >&2
                [[ -n "$output" ]] && printf '%s\n' "$output" >&2
                failures=$((failures + 1))
            else
                echo "$id: PASS compiler-next=$current_status [$class]"
            fi
            ;;
        reject:*)
            expected=${current_result#reject:}
            if [[ -z "$expected" ]]; then
                echo "$id: FAIL invalid current expectation: $current_result" >&2
                failures=$((failures + 1))
            elif [[ $current_status -eq 0 ]]; then
                echo "$id: FAIL compiler-next unexpectedly accepted; expected=$expected [$class]" >&2
                failures=$((failures + 1))
            elif ! grep -Fq "error[$expected]" <<<"$output"; then
                echo "$id: FAIL compiler-next rejected without expected diagnostic $expected (status=$current_status) [$class]" >&2
                [[ -n "$output" ]] && printf '%s\n' "$output" >&2
                failures=$((failures + 1))
            else
                echo "$id: PASS compiler-next=reject:$expected [$class]"
            fi
            ;;
        trap)
            # aether-next maps signal termination to status 1. Compilation and
            # driver/infrastructure failures use status 2 and cannot satisfy a trap.
            if [[ $current_status -ne 1 ]]; then
                echo "$id: FAIL compiler-next status=$current_status expected=trap [$class]" >&2
                [[ -n "$output" ]] && printf '%s\n' "$output" >&2
                failures=$((failures + 1))
            else
                echo "$id: PASS compiler-next=trap [$class]"
            fi
            ;;
        *)
            echo "$id: FAIL unknown current expectation: $current_result" >&2
            failures=$((failures + 1))
            ;;
    esac
done < "$manifest"

echo "qualification: mode=official checked=$checked failures=$failures"
[[ $failures -eq 0 ]]
