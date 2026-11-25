#!/usr/bin/env bash
set -euo pipefail

workspace=$(cd "$(dirname "$0")/.." && pwd)
official="$workspace/tests/run-differential.sh"
historical="$workspace/tests/run-legacy-differential.sh"
scratch=$(mktemp -d "${TMPDIR:-/tmp}/aether-differential-harness.XXXXXX")
trap 'rm -rf "$scratch"' EXIT

fake_next="$scratch/aether-next"
fake_python="$scratch/python"
legacy_marker="$scratch/legacy-invoked"

cat > "$fake_next" <<'SCRIPT'
#!/usr/bin/env bash
case "${2##*/}" in
    return_zero.ae) exit 0 ;;
    unknown_identifier.ae) echo 'error[E0202]: expected rejection' >&2; exit 2 ;;
    dynamic_overflow.ae) exit 1 ;;
    *) echo 'unexpected fake compiler input' >&2; exit 2 ;;
esac
SCRIPT
chmod +x "$fake_next"

cat > "$fake_python" <<SCRIPT
#!/usr/bin/env bash
if [[ "\${1:-}" == "-c" ]]; then
    exit 0
fi
printf '%s\n' invoked >> "$legacy_marker"
case "\${3##*/}" in
    return_zero.ae) exit 9 ;;
    unknown_identifier.ae) exit 1 ;;
    *) exit 99 ;;
esac
SCRIPT
chmod +x "$fake_python"

official_manifest="$scratch/official.tsv"
cat > "$official_manifest" <<'TSV'
# id	class	current_result	legacy_result	source
positive	CURRENT_CONTRACT	accept:0	accept:9	programs/return_zero.ae
negative	CURRENT_CONTRACT	reject:E0202	reject	programs/unknown_identifier.ae
trap	CURRENT_CONTRACT	trap	n/a	programs/dynamic_overflow.ae
TSV

# Legacy availability and results are irrelevant to the official gate.
AETHER_NEXT_BIN="$fake_next" \
AETHER_LEGACY_PYTHON="$fake_python" \
AETHER_QUALIFICATION_MANIFEST="$official_manifest" \
    "$official" > "$scratch/official-available.out"
[[ ! -e "$legacy_marker" ]]

AETHER_NEXT_BIN="$fake_next" \
AETHER_LEGACY_PYTHON="$scratch/does-not-exist" \
AETHER_QUALIFICATION_MANIFEST="$official_manifest" \
    "$official" > "$scratch/official-unavailable.out"

# Execute the same gate from a minimal tree in which compiler-rs does not exist.
isolated_workspace="$scratch/isolated/compiler-next"
mkdir -p "$isolated_workspace/tests/programs"
cp "$official" "$isolated_workspace/tests/run-differential.sh"
touch "$isolated_workspace/tests/programs/return_zero.ae"
touch "$isolated_workspace/tests/programs/unknown_identifier.ae"
touch "$isolated_workspace/tests/programs/dynamic_overflow.ae"
AETHER_NEXT_BIN="$fake_next" \
AETHER_LEGACY_PYTHON="$scratch/does-not-exist" \
AETHER_QUALIFICATION_MANIFEST="$official_manifest" \
    "$isolated_workspace/tests/run-differential.sh" > "$scratch/official-isolated.out"
[[ ! -e "$scratch/isolated/compiler-rs" ]]

# The official harness itself must contain no compiler-rs/Python/core dependency.
if grep -Eqi 'compiler-rs|aether-compiler-core|legacy_python|aether\.cli|pyo3|maturin' "$official"; then
    echo "official harness contains a legacy dependency" >&2
    exit 1
fi

wrong_expectation="$scratch/wrong-expectation.tsv"
cat > "$wrong_expectation" <<'TSV'
wrong	CURRENT_CONTRACT	accept:7	n/a	programs/return_zero.ae
TSV
if AETHER_NEXT_BIN="$fake_next" AETHER_QUALIFICATION_MANIFEST="$wrong_expectation" \
    "$official" > "$scratch/wrong.out" 2>&1; then
    echo "official harness accepted a violated current expectation" >&2
    exit 1
fi
grep -Fq 'failures=1' "$scratch/wrong.out"

broken_compiler="$scratch/broken-aether-next"
cat > "$broken_compiler" <<'SCRIPT'
#!/usr/bin/env bash
echo 'compiler-next failed' >&2
exit 2
SCRIPT
chmod +x "$broken_compiler"
if AETHER_NEXT_BIN="$broken_compiler" AETHER_QUALIFICATION_MANIFEST="$official_manifest" \
    "$official" > "$scratch/broken.out" 2>&1; then
    echo "official harness hid a genuine compiler-next failure" >&2
    exit 1
fi

# An expected historical semantic divergence is informative and does not alter
# the already successful official result.
historical_manifest="$scratch/historical.tsv"
cat > "$historical_manifest" <<'TSV'
divergence	INTENTIONAL_CHANGE	accept:0	accept:9	programs/return_zero.ae
legacy_reject	PRESERVE_REJECTION	reject:E0202	reject	programs/unknown_identifier.ae
TSV
AETHER_LEGACY_PYTHON="$fake_python" \
AETHER_QUALIFICATION_MANIFEST="$historical_manifest" \
    "$historical" > "$scratch/historical.out"
grep -Fq 'NON-NORMATIVE' "$scratch/historical.out"
grep -Fq 'non_normative=true checked=2 failures=0' "$scratch/historical.out"

historical_mismatch="$scratch/historical-mismatch.tsv"
cat > "$historical_mismatch" <<'TSV'
changed	LEGACY_EQUIVALENT	accept:0	accept:0	programs/return_zero.ae
TSV
if AETHER_LEGACY_PYTHON="$fake_python" \
    AETHER_QUALIFICATION_MANIFEST="$historical_mismatch" \
    "$historical" > "$scratch/historical-mismatch.out" 2>&1; then
    echo "historical mode accepted an unexpected observation" >&2
    exit 1
fi
grep -Fq 'no compiler-next defect is implied' "$scratch/historical-mismatch.out"

if AETHER_LEGACY_PYTHON="$scratch/does-not-exist" \
    AETHER_QUALIFICATION_MANIFEST="$historical_manifest" \
    "$historical" > "$scratch/historical-missing.out" 2>&1; then
    echo "historical mode hid an infrastructure failure" >&2
    exit 1
fi
grep -Fq 'infrastructure error' "$scratch/historical-missing.out"

echo "differential harness tests: PASS"
