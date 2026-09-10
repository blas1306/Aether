#!/usr/bin/env python3
"""Descriptive OOP-V1 process timing; includes startup and LLVM optimizations."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


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
    with tempfile.TemporaryDirectory(prefix='aether-oop-cost-') as temporary:
        output = Path(temporary)
        for name in ['alias_direct_keepalive', 'allocate_alias_last_release',
                     'nested_buffer_last_release']:
            source = workspace / f'tests/programs/oop_v1_cost_{name}.ae'
            build = subprocess.run([str(compiler), 'build', str(source), '-o',
                                    str(output / name), '--emit', 'llvm'],
                                   capture_output=True, text=True, check=True)
            llvm = build.stdout.split('== llvm ==\n', 1)[1].rsplit('\nbuilt ', 1)[0]
            ir = output / f'{name}.ll'
            ir.write_text(llvm)
            for opt in ['O0', 'O2']:
                executable = output / f'{name}-{opt}'
                subprocess.run(['clang', '-Wno-override-module', f'-{opt}',
                                str(ir), '-o', str(executable)], check=True)
                subprocess.run([str(executable)], check=True)
                samples = []
                for _ in range(args.runs):
                    start = time.perf_counter_ns()
                    subprocess.run([str(executable)], check=True)
                    samples.append((time.perf_counter_ns() - start) / 1e6)
                size = subprocess.run(['size', str(executable)], capture_output=True,
                                      text=True, check=True).stdout.splitlines()[1].split()
                rows.append(dict(case=name, optimization=opt,
                                 median_process_ms=round(statistics.median(samples), 3),
                                 range_ms=[round(min(samples), 3), round(max(samples), 3)],
                                 elf_text_bytes=int(size[0])))
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
