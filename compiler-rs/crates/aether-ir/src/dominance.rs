//! Entry-rooted dominator analysis for SSA construction.
//!
//! Production computes immediate dominators directly with the
//! Cooper-Harvey-Kennedy reverse-postorder algorithm.  The former full-set
//! solver is retained below only as a test oracle.

use std::collections::BTreeSet;

#[derive(Debug)]
pub(crate) struct DominanceInfo {
    pub(crate) reachable: Vec<bool>,
    pub(crate) predecessors: Vec<Vec<usize>>,
    #[cfg(test)]
    pub(crate) idom: Vec<Option<usize>>,
    pub(crate) children: Vec<Vec<usize>>,
    pub(crate) frontiers: Vec<BTreeSet<usize>>,
}

impl DominanceInfo {
    pub(crate) fn compute(successors: &[Vec<usize>], entry: usize) -> Self {
        let block_count = successors.len();
        debug_assert!(entry < block_count);

        let (reachable, reverse_postorder) = reverse_postorder(successors, entry);
        let mut predecessors = vec![Vec::new(); block_count];
        for (block, targets) in successors.iter().enumerate() {
            if !reachable[block] {
                continue;
            }
            for &target in targets {
                if reachable[target] {
                    predecessors[target].push(block);
                }
            }
        }

        let mut rpo_number = vec![usize::MAX; block_count];
        for (number, &block) in reverse_postorder.iter().enumerate() {
            rpo_number[block] = number;
        }

        // `Some(entry)` is the standard temporary root sentinel.  It is
        // removed before exposing the result so entry retains no idom.
        let mut idom = vec![None; block_count];
        idom[entry] = Some(entry);
        loop {
            let mut changed = false;
            for &block in reverse_postorder.iter().skip(1) {
                let mut known_predecessors = predecessors[block]
                    .iter()
                    .copied()
                    .filter(|&predecessor| idom[predecessor].is_some());
                let Some(mut next_idom) = known_predecessors.next() else {
                    continue;
                };
                for predecessor in known_predecessors {
                    next_idom = intersect(predecessor, next_idom, &idom, &rpo_number);
                }
                if idom[block] != Some(next_idom) {
                    idom[block] = Some(next_idom);
                    changed = true;
                }
            }
            if !changed {
                break;
            }
        }
        idom[entry] = None;

        // Source block index order is the frozen dominator-child order.
        let mut children = vec![Vec::new(); block_count];
        for (block, parent) in idom.iter().copied().enumerate() {
            if let Some(parent) = parent {
                children[parent].push(block);
            }
        }

        let mut frontiers = vec![BTreeSet::new(); block_count];
        for block in 0..block_count {
            if !reachable[block] || predecessors[block].len() < 2 {
                continue;
            }
            for &predecessor in &predecessors[block] {
                let mut runner = predecessor;
                while Some(runner) != idom[block] {
                    frontiers[runner].insert(block);
                    let Some(parent) = idom[runner] else {
                        break;
                    };
                    runner = parent;
                }
            }
        }

        Self {
            reachable,
            predecessors,
            #[cfg(test)]
            idom,
            children,
            frontiers,
        }
    }

    #[cfg(test)]
    fn dominates(&self, dominator: usize, mut block: usize) -> bool {
        if !self.reachable.get(block).copied().unwrap_or(false)
            || !self.reachable.get(dominator).copied().unwrap_or(false)
        {
            return false;
        }
        loop {
            if block == dominator {
                return true;
            }
            let Some(parent) = self.idom[block] else {
                return false;
            };
            block = parent;
        }
    }
}

fn reverse_postorder(successors: &[Vec<usize>], entry: usize) -> (Vec<bool>, Vec<usize>) {
    let mut reachable = vec![false; successors.len()];
    let mut postorder = Vec::with_capacity(successors.len());
    let mut stack = vec![(entry, 0)];
    reachable[entry] = true;

    while let Some((block, next_successor)) = stack.last_mut() {
        if *next_successor < successors[*block].len() {
            let successor = successors[*block][*next_successor];
            *next_successor += 1;
            if !reachable[successor] {
                reachable[successor] = true;
                stack.push((successor, 0));
            }
        } else {
            postorder.push(*block);
            stack.pop();
        }
    }
    postorder.reverse();
    (reachable, postorder)
}

fn intersect(
    mut left: usize,
    mut right: usize,
    idom: &[Option<usize>],
    rpo_number: &[usize],
) -> usize {
    while left != right {
        while rpo_number[left] > rpo_number[right] {
            left = idom[left].expect("known CHK predecessor has an idom chain");
        }
        while rpo_number[right] > rpo_number[left] {
            right = idom[right].expect("known CHK predecessor has an idom chain");
        }
    }
    left
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::hint::black_box;
    use std::time::Instant;

    struct ReferenceDominance {
        reachable: Vec<bool>,
        sets: Vec<BTreeSet<usize>>,
        idom: Vec<Option<usize>>,
        children: Vec<Vec<usize>>,
        frontiers: Vec<BTreeSet<usize>>,
    }

    /// RUST-3.9b qualification oracle: the pre-milestone full-set algorithm.
    /// It is deliberately unavailable in non-test builds.
    fn reference_dominance(successors: &[Vec<usize>], entry: usize) -> ReferenceDominance {
        let (reachable, _) = reverse_postorder(successors, entry);
        let block_count = successors.len();
        let reachable_set = reachable
            .iter()
            .enumerate()
            .filter_map(|(block, &yes)| yes.then_some(block))
            .collect::<BTreeSet<_>>();
        let mut predecessors = vec![Vec::new(); block_count];
        for (block, targets) in successors.iter().enumerate() {
            if reachable[block] {
                for &target in targets {
                    if reachable[target] {
                        predecessors[target].push(block);
                    }
                }
            }
        }
        let mut sets = vec![BTreeSet::new(); block_count];
        for block in 0..block_count {
            if reachable[block] {
                sets[block] = if block == entry {
                    BTreeSet::from([entry])
                } else {
                    reachable_set.clone()
                };
            }
        }
        loop {
            let mut changed = false;
            for block in 0..block_count {
                if !reachable[block] || block == entry {
                    continue;
                }
                let mut next = reachable_set.clone();
                for &predecessor in &predecessors[block] {
                    next = next.intersection(&sets[predecessor]).copied().collect();
                }
                next.insert(block);
                if next != sets[block] {
                    sets[block] = next;
                    changed = true;
                }
            }
            if !changed {
                break;
            }
        }
        let mut idom = vec![None; block_count];
        for block in 0..block_count {
            if reachable[block] && block != entry {
                idom[block] = sets[block]
                    .iter()
                    .copied()
                    .filter(|&candidate| candidate != block)
                    .max_by_key(|&candidate| (sets[candidate].len(), candidate));
            }
        }
        let mut children = vec![Vec::new(); block_count];
        for (block, parent) in idom.iter().copied().enumerate() {
            if let Some(parent) = parent {
                children[parent].push(block);
            }
        }
        let mut frontiers = vec![BTreeSet::new(); block_count];
        for block in 0..block_count {
            if reachable[block] && predecessors[block].len() >= 2 {
                for &predecessor in &predecessors[block] {
                    let mut runner = predecessor;
                    while Some(runner) != idom[block] {
                        frontiers[runner].insert(block);
                        let Some(parent) = idom[runner] else {
                            break;
                        };
                        runner = parent;
                    }
                }
            }
        }
        ReferenceDominance {
            reachable,
            sets,
            idom,
            children,
            frontiers,
        }
    }

    fn assert_matches_reference(name: &str, successors: &[Vec<usize>]) {
        let optimized = DominanceInfo::compute(successors, 0);
        let reference = reference_dominance(successors, 0);
        assert_eq!(
            optimized.reachable, reference.reachable,
            "{name}: reachability"
        );
        assert_eq!(
            optimized.idom, reference.idom,
            "{name}: idom; cfg={successors:?}"
        );
        assert_eq!(
            optimized.children, reference.children,
            "{name}: tree; cfg={successors:?}"
        );
        assert_eq!(
            optimized.frontiers, reference.frontiers,
            "{name}: frontier; cfg={successors:?}"
        );
        assert_eq!(optimized.idom[0], None, "{name}: entry idom");
        for block in 0..successors.len() {
            for dominator in 0..successors.len() {
                assert_eq!(
                    optimized.dominates(dominator, block),
                    reference.sets[block].contains(&dominator),
                    "{name}: dominates({dominator}, {block}); cfg={successors:?}"
                );
            }
        }
    }

    #[test]
    fn adversarial_cfg_families_match_full_set_reference() {
        let cases: &[(&str, &[&[usize]])] = &[
            ("single", &[&[]]),
            ("chain", &[&[1], &[2], &[3], &[]]),
            ("diamond", &[&[1, 2], &[3], &[3], &[]]),
            (
                "nested_diamonds",
                &[&[1, 2], &[3], &[3], &[4, 5], &[6], &[6], &[]],
            ),
            ("simple_loop", &[&[1], &[2, 3], &[1], &[]]),
            (
                "nested_loops",
                &[&[1], &[2, 6], &[3, 5], &[4], &[2], &[1], &[]],
            ),
            (
                "multiple_exits",
                &[&[1], &[2, 4], &[3, 4], &[1, 5], &[5], &[]],
            ),
            ("irreducible", &[&[1, 2], &[3], &[3], &[1, 2, 4], &[]]),
            ("fan_out_in", &[&[1, 2, 3, 4], &[5], &[5], &[5], &[5], &[]]),
            (
                "repeated_merges",
                &[&[1, 2], &[3], &[3], &[4, 5], &[6], &[6], &[7], &[]],
            ),
            (
                "mixed_exception_edges",
                &[&[1, 2], &[3, 4], &[4], &[5], &[5], &[]],
            ),
            ("unreachable_isolated", &[&[1], &[], &[]]),
            ("unreachable_cycle", &[&[1], &[], &[3], &[2]]),
            ("unreachable_predecessor", &[&[1], &[], &[1]]),
            ("entry_backedge", &[&[1], &[0, 2], &[]]),
            ("duplicate_edges", &[&[1, 1], &[]]),
        ];
        for (name, rows) in cases {
            let successors = rows.iter().map(|row| row.to_vec()).collect::<Vec<_>>();
            assert_matches_reference(name, &successors);
        }
    }

    #[test]
    fn fixed_seed_random_cfgs_match_full_set_reference() {
        for seed in [0x039b_u64, 1, 7, 0x5eed, 0xa37e_2026] {
            let mut state = seed;
            for case in 0..80 {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                let block_count = 2 + usize::try_from(state % 47).expect("bounded node count");
                let mut successors = vec![Vec::new(); block_count];
                for targets in &mut successors {
                    state ^= state << 13;
                    state ^= state >> 7;
                    state ^= state << 17;
                    let edge_count = usize::try_from(state % 5).expect("bounded edge count");
                    for _ in 0..edge_count {
                        state ^= state << 13;
                        state ^= state >> 7;
                        state ^= state << 17;
                        let modulus = u64::try_from(block_count).expect("small node count");
                        targets
                            .push(usize::try_from(state % modulus).expect("bounded target index"));
                    }
                }
                assert_matches_reference(&format!("seed={seed:#x},case={case}"), &successors);
            }
        }
    }

    #[test]
    fn ten_thousand_block_chain_is_stack_safe_and_linear_storage() {
        let block_count = 10_000;
        let mut successors = vec![Vec::new(); block_count];
        for (block, targets) in successors.iter_mut().enumerate().take(block_count - 1) {
            targets.push(block + 1);
        }
        let optimized = DominanceInfo::compute(&successors, 0);
        assert!(optimized.reachable.iter().all(|reachable| *reachable));
        assert_eq!(optimized.idom[block_count - 1], Some(block_count - 2));
        assert_eq!(optimized.idom.len(), block_count);
        assert_eq!(
            optimized.frontiers.iter().map(BTreeSet::len).sum::<usize>(),
            0
        );
    }

    /// Manual, qualification-only microbenchmark. The full-set reference is
    /// capped because allocating it at larger sizes is the removed pathology.
    #[test]
    #[ignore = "qualification benchmark; run explicitly with --ignored --nocapture"]
    fn qualification_scaling_benchmark() {
        for block_count in [100, 1_000, 5_000, 10_000, 25_000] {
            let mut successors = vec![Vec::new(); block_count];
            for (block, targets) in successors.iter_mut().enumerate().take(block_count - 1) {
                targets.push(block + 1);
            }
            for _ in 0..2 {
                black_box(DominanceInfo::compute(&successors, 0));
            }
            let mut optimized_ns = Vec::new();
            for _ in 0..7 {
                let started = Instant::now();
                black_box(DominanceInfo::compute(&successors, 0));
                optimized_ns.push(started.elapsed().as_nanos());
            }
            optimized_ns.sort_unstable();
            let reference_ns = (block_count <= 1_000).then(|| {
                let started = Instant::now();
                black_box(reference_dominance(&successors, 0));
                started.elapsed().as_nanos()
            });
            println!(
                "DOMINATOR_BENCH blocks={block_count} optimized_min_ns={} optimized_median_ns={} optimized_max_ns={} reference_ns={reference_ns:?}",
                optimized_ns[0],
                optimized_ns[optimized_ns.len() / 2],
                optimized_ns[optimized_ns.len() - 1],
            );
        }
    }
}
