from ml.task2.common.split import leaks, session_split, split_examples


def _ex(session, text, source="selfplay"):
    return {"session": session, "text": text, "source": source}


def test_session_split_is_deterministic_and_roughly_80_10_10():
    splits = [session_split(f"run-{i:04d}") for i in range(2000)]
    assert splits == [session_split(f"run-{i:04d}") for i in range(2000)]
    frac = splits.count("train") / len(splits)
    assert 0.75 < frac < 0.85


def test_turns_of_one_session_stay_together_and_no_leaks():
    exs = [_ex(f"s{i}", f"unique sentence number {i} about the crate and Leo") for i in range(200)]
    buckets, stats = split_examples(exs)
    seen = {}
    for name, rows in buckets.items():
        for r in rows:
            assert seen.setdefault(r["session"], name) == name
    assert leaks(buckets) == 0


def test_near_duplicates_are_capped_and_kept_out_of_test():
    exs = [_ex(f"s{i}", "I smile and hand her my coat.") for i in range(40)]
    buckets, stats = split_examples(exs, cap=3)
    assert len(buckets["train"]) <= 3
    assert buckets["val"] == [] and buckets["test"] == []
    assert leaks(buckets) == 0


def test_rewrites_only_in_train():
    exs = [_ex(f"s{i}", f"rewrite text {i} for the hall and the phone", source="rewrite") for i in range(50)]
    exs += [_ex(f"t{i}", f"player text {i} asking Julian about the afternoon") for i in range(300)]
    buckets, _ = split_examples(exs)
    assert all(r["source"] != "rewrite" for r in buckets["val"] + buckets["test"])
    n_rw = sum(r["source"] == "rewrite" for r in buckets["train"])
    assert n_rw <= int(0.15 * len(buckets["train"])) + 1


def test_example_count_cut_gives_close_to_80_10_10_with_few_sessions():
    import random
    rng = random.Random(1)
    exs = [_ex(f"g{i}", f"game {i} turn {t} says something new about item {rng.random()}") for i in range(50) for t in range(rng.randint(5, 45))]
    buckets, _ = split_examples(exs)
    n = sum(len(v) for v in buckets.values())
    assert 0.75 < len(buckets["train"]) / n < 0.85
    assert 0.05 < len(buckets["test"]) / n < 0.16


def test_pinned_sessions_keep_their_split_and_new_ones_split_80_10_10():
    old = [_ex(f"old{i}", f"old game {i} sentence about the parcel and Nora") for i in range(100)]
    first, _ = split_examples(old)
    pinned = {r["session"]: name for name, rows in first.items() for r in rows}
    new = [_ex(f"new{i}", f"new game {i} sentence about the hall and Mia") for i in range(400)]
    second, _ = split_examples(old + new, pinned=pinned)
    where = {r["session"]: name for name, rows in second.items() for r in rows}
    assert all(where[s] == split for s, split in pinned.items())
    new_train = sum(where[f"new{i}"] == "train" for i in range(400))
    assert 0.75 < new_train / 400 < 0.85
    assert leaks(second) == 0
