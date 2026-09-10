#!/usr/bin/env python3
"""Descriptive OOP-V2 costs: instrumented semantic events, ELF text, process time.

Each workload has 10,000 iterations. Timing includes instrumentation and process
startup; LLVM may inline/devirtualize. This is not isolated dispatch latency.
"""
import argparse
import json
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import time


COUNTERS = ['object_alloc', 'object_retain', 'object_release', 'object_destroy',
            'object_buffer_drop', 'heap_alloc', 'heap_free', 'interface_slot_load',
            'interface_release_load']
EXPECTED = {
    'lvalue_adaptation': [1, 10000, 10001, 1, 0, 1, 1, 0, 10000],
    'fresh_adaptation': [10000, 0, 10000, 10000, 0, 10000, 10000, 0, 10000],
    'interface_alias': [1, 10000, 10001, 1, 0, 1, 1, 0, 10001],
    'read_call': [1, 10000, 10001, 1, 0, 1, 1, 10000, 10001],
    'mut_call': [1, 10000, 10001, 1, 0, 1, 1, 10000, 10001],
    'final_release': [10000, 0, 10000, 10000, 10000, 20000, 20000, 0, 10000],
}


def instrument(llvm):
    for kind, pattern in [('slot', r'  %target\d+ = load ptr, ptr %slot\d+'),
                          ('release', r'  %release = load ptr, ptr %witness')]:
        name = f'interface_{kind}_load'
        llvm += f'\n@aether_{name}_count = internal global i64 0\n'
        def insert(match):
            return (match[0] + f'\n  %{name}_old = load i64, ptr @aether_{name}_count'
                    f'\n  %{name}_next = add i64 %{name}_old, 1'
                    f'\n  store i64 %{name}_next, ptr @aether_{name}_count')
        # These bounded workloads have one dispatch per function.
        llvm = re.sub(pattern, insert, llvm)
    llvm = llvm.replace('define i32 @main()', 'define i32 @aether_cost_main()')
    fmt = ' '.join(['%ld'] * len(COUNTERS)) + '\n'
    encoded = fmt.replace('\n', r'\0A') + r'\00'
    llvm += f'\n@cost_format = private constant [{len(fmt)+1} x i8] c"{encoded}"\n'
    llvm += 'declare i32 @printf(ptr, ...)\ndefine i32 @main() {\nentry:\n  %status = call i32 @aether_cost_main()\n'
    for index, counter in enumerate(COUNTERS):
        llvm += f'  %c{index} = load i64, ptr @aether_{counter}_count\n'
    operands = ', '.join(f'i64 %c{i}' for i in range(len(COUNTERS)))
    llvm += f'  %printed = call i32 (ptr, ...) @printf(ptr @cost_format, {operands})\n  ret i32 %status\n}}\n'
    return llvm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=7)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs must be positive')
    workspace = Path(__file__).resolve().parents[1]
    subprocess.run(['cargo', 'build', '--quiet', '-p', 'aether-driver', '--bin',
                    'aether-next'], cwd=workspace, check=True)
    compiler = workspace / 'target/debug/aether-next'
    rows = []
    with tempfile.TemporaryDirectory(prefix='aether-oop-v2-cost-') as temporary:
        output = Path(temporary)
        for name, expected in EXPECTED.items():
            source = workspace / f'tests/programs/oop_v2_cost_{name}.ae'
            build = subprocess.run([str(compiler), 'build', str(source), '-o',
                                    str(output / name), '--emit', 'llvm'],
                                   capture_output=True, text=True, check=True)
            llvm = build.stdout.split('== llvm ==\n', 1)[1].rsplit('\nbuilt ', 1)[0]
            ir = output / f'{name}.ll'
            ir.write_text(instrument(llvm))
            for opt in ['O0', 'O2']:
                executable = output / f'{name}-{opt}'
                subprocess.run(['clang', '-Wno-override-module', f'-{opt}',
                                str(ir), '-o', str(executable)], check=True)
                optimized_ir = output / f'{name}-{opt}.ll'
                subprocess.run(['clang', '-Wno-override-module', f'-{opt}', '-S',
                                '-emit-llvm', str(ir), '-o', str(optimized_ir)], check=True)
                indirect_sites = len(re.findall(r'\bcall\b[^@\n]*\s%[\w.]+\(',
                                                optimized_ir.read_text()))
                samples = []
                for _ in range(args.runs):
                    start = time.perf_counter_ns()
                    run = subprocess.run([str(executable)], capture_output=True,
                                         text=True, check=True)
                    samples.append((time.perf_counter_ns() - start) / 1e6)
                    actual = list(map(int, run.stdout.split()))
                    assert actual == expected, (name, opt, actual, expected)
                size = subprocess.run(['size', str(executable)], capture_output=True,
                                      text=True, check=True).stdout.splitlines()[1].split()
                rows.append(dict(case=name, optimization=opt,
                                 median_process_ms=round(statistics.median(samples), 3),
                                 range_ms=[round(min(samples), 3), round(max(samples), 3)],
                                 elf_text_bytes=int(size[0]), events=dict(zip(COUNTERS, actual)),
                                 semantic_indirect_calls=actual[-2] + actual[-1],
                                 optimized_indirect_call_sites=indirect_sites,
                                 wrapper_allocations=actual[5] - actual[0] - actual[4]))
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
