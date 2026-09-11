#!/usr/bin/env python3
"""OOP-V3: compare true compiler O0/O2, physical events/sites and native cost.

Times include process startup and qualification counters, not isolated latency.
Static SSA-lowered sites are recorded BEFORE clang; clang sites are separate.
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
            'object_buffer_drop', 'heap_alloc', 'heap_free']


def instrument(llvm):
    llvm = llvm.replace('define i32 @main()', 'define i32 @aether_cost_main()')
    fmt = ' '.join(['%ld'] * len(COUNTERS)) + '\n'
    encoded = fmt.replace('\n', r'\0A') + r'\00'
    llvm += f'\n@cost_format = private constant [{len(fmt)+1} x i8] c"{encoded}"\n'
    llvm += ('declare i32 @printf(ptr, ...)\ndefine i32 @main() {\nentry:\n'
             '  %status = call i32 @aether_cost_main()\n')
    for index, counter in enumerate(COUNTERS):
        llvm += f'  %c{index} = load i64, ptr @aether_{counter}_count\n'
    operands = ', '.join(f'i64 %c{i}' for i in range(len(COUNTERS)))
    return llvm + (f'  %printed = call i32 (ptr, ...) @printf(ptr @cost_format, {operands})\n'
                   '  ret i32 %status\n}\n')


def indirect(ir):
    return len(re.findall(r'\bcall\b[^@\n]*\s%[\w.]+\(', ir))


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
    sources = sorted((workspace / 'tests/programs').glob('oop_v3_cost_*.ae'))
    rows = []
    with tempfile.TemporaryDirectory(prefix='aether-oop-opt-1-') as temporary:
        output = Path(temporary)
        for source in sources:
            baseline = None
            for opt in ['O0', 'O2']:
                build = subprocess.run([str(compiler), 'build', str(source), f'-{opt}',
                                        '-o', str(output / 'unmodified'), '--emit', 'llvm'],
                                       capture_output=True, text=True, check=True)
                llvm = build.stdout.split('== llvm ==\n', 1)[1].rsplit('\nbuilt ', 1)[0]
                # Source function bodies exclude unused runtime glue definitions.
                bodies = '\n'.join(re.findall(r'^define [^\n]*@__aether_[\s\S]*?^}',
                                               llvm, re.MULTILINE))
                sites = dict(descriptor_load=len(re.findall(r'= load ptr, ptr %descriptor_addr\d+', bodies)),
                             retain=bodies.count('call void @aether_object_retain('),
                             release=len(re.findall(r'call void @aether_drop_(?:c\d+|iface\d+)', bodies)),
                             method_witness_load=len(re.findall(r'= load ptr, ptr %slot\d+', bodies)),
                             indirect_method=indirect(bodies),
                             indirect_including_glue=indirect(llvm),
                             elided_pairs=llvm.count('; OOP-OPT-1 paired release elision'),
                             devirtualized=llvm.count('; OOP-OPT-1 devirtualization'))
                ir = output / 'instrumented.ll'
                ir.write_text(instrument(llvm))
                exe = output / 'instrumented'
                subprocess.run(['clang', '-Wno-override-module', f'-{opt}', str(ir),
                                '-o', str(exe)], check=True)
                optimized_ir = output / 'clang.ll'
                subprocess.run(['clang', '-Wno-override-module', f'-{opt}', '-S',
                                '-emit-llvm', str(ir), '-o', str(optimized_ir)], check=True)
                samples = []
                events = None
                for run_index in range(args.runs + 1):
                    start = time.perf_counter_ns()
                    run = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
                    duration = (time.perf_counter_ns() - start) / 1e6
                    actual = list(map(int, run.stdout.split()))
                    assert events is None or events == actual
                    events = actual
                    if run_index:
                        samples.append(duration)
                assert events[0] == events[3] and events[5] == events[6]
                assert events[2] == events[0] + events[1]
                if baseline is None:
                    baseline = events
                else:
                    assert [events[i] for i in [0, 3, 4, 5, 6]] == [baseline[i] for i in [0, 3, 4, 5, 6]]
                    assert events[1] <= baseline[1]
                size = subprocess.run(['size', str(exe)], capture_output=True,
                                      text=True, check=True).stdout.splitlines()[1].split()
                rows.append(dict(case=source.stem, profile=opt, emitted_sites=sites,
                                 physical_events=dict(zip(COUNTERS, events)),
                                 clang_indirect_sites=indirect(optimized_ir.read_text()),
                                 elf_text_bytes=int(size[0]),
                                 median_process_ms=round(statistics.median(samples), 3),
                                 range_ms=[round(min(samples), 3), round(max(samples), 3)]))
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
