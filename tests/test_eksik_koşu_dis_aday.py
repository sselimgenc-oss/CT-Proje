"""Eksik koşu (görev 24) ve dış adaylar (görev 16). Ağsız."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from copytrade.kapi import (build_universe, external_candidates, load_rules, merge_shards,
                            read_universe_snapshot, run_status, shard_universe, write_universe_snapshot)

RULES = load_rules()
A, B, C = "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40


def board_row(address, value, pnl):
    return {"ethAddress": address, "accountValue": str(value), "windowPerformances": [["allTime", {"pnl": str(pnl), "roi": "1", "vlm": "1"}]]}


class FakeClient:
    def __init__(self, value=None): self.value, self.calls = value, []
    def info(self, payload, weight=20):
        self.calls.append(payload)
        if self.value is None: raise KeyError("yok")
        return {"marginSummary": {"accountValue": str(self.value)}}


def test_external_candidates_are_unique_lowercase_addresses_from_all_files(tmp_path):
    (tmp_path / "x.md").write_text(f"- {A.upper().replace('0X', '0x')} ve {B}\nkısa 0x1234 değil")
    (tmp_path / "y.txt").write_text(f"{A} {C}")
    assert external_candidates(tmp_path) == sorted([A, B, C]) and external_candidates(tmp_path / "yok") == []
    assert len(external_candidates()) > 50      # gerçek bağımsız seçim notları


def test_universe_marks_external_and_bypasses_prefilter():
    board = [board_row(A, 500_000, 10), board_row(B, 100, 5), board_row(C, 900_000, -5)]        # B çok küçük, C zararda
    universe = {row["address"]: row for row in build_universe(board, [B, C, "0x" + "d" * 40], FakeClient(value=1234))}
    assert universe[A]["kaynak"] == "leaderboard"
    assert universe[B]["kaynak"] == "dis_aday" and universe[B]["accountValue"] == 100        # süzgeçe takılsa da girer, değer lider tablosundan
    assert universe[C]["kaynak"] == "dis_aday"
    assert universe["0x" + "d" * 40]["accountValue"] == 1234                                  # lider tablosunda yok → clearinghouseState
    assert len(universe) == 4
    assert build_universe(board, [A], None)[0]["kaynak"] == "dis_aday"                         # süzgeçten geçen de dış adaysa işaretlenir
    assert build_universe([], [A], FakeClient())[0]["accountValue"] == 0.0                     # değer alınamazsa 0


def test_altin_ornek_ortak_evren_parcalari_cakismadan_birlesir(tmp_path):
    """Altın örnek: tek plan dosyası her adresi yalnız bir parçaya verir."""
    board = [board_row(address, 500_000, 10) for address in (A, B, C)]
    snapshot = tmp_path / "evren.json"
    write_universe_snapshot(snapshot, board, [], FakeClient())
    frozen = read_universe_snapshot(snapshot)
    pieces = [shard_universe(frozen, index, 2) for index in range(2)]
    addresses = [{row["address"] for row in piece} for piece in pieces]
    assert addresses[0].isdisjoint(addresses[1])
    assert addresses[0] | addresses[1] == {A, B, C}
    assert [row["address"] for row in read_universe_snapshot(snapshot)] == [A, B, C]


def test_run_status_incomplete_when_shard_missing_or_coverage_low():
    assert run_status(32, 32, 985, 1000, "tam", RULES)["durum"] == "tamam"
    missing = run_status(31, 32, 990, 1000, "tam", RULES)
    assert missing["durum"] == "eksik" and "31" in missing["neden"]
    low = run_status(32, 32, 100, 1000, "tam", RULES)
    assert low["durum"] == "eksik" and "kapsam" in low["neden"]
    assert run_status(24, 24, 40, 1000, "hizli", RULES)["durum"] == "tamam"                    # hızlı koşu evrenin tamamını işlemez


def make_shard(base: Path, index: int, address: str, finished: bool):
    folder = base / f"stage1-{index}" / "2026-10-28"
    folder.mkdir(parents=True)
    row = {"address": address, "asama1": "Yetersiz"}
    pd.DataFrame([row]).to_csv(folder / "sonuc.csv", index=False)
    (folder / "evren.json").write_text(json.dumps({"evren": 2}))
    if finished:
        (folder / "bitti.json").write_text("{}")


def test_merge_publishes_incomplete_run_as_eksik(tmp_path):
    make_shard(tmp_path / "shards", 0, "0xa", True)
    make_shard(tmp_path / "shards", 1, "0xb", False)         # zaman aşımı: bitti.json yok
    statuses = merge_shards(tmp_path / "shards", tmp_path / "root", 2, "tam")
    day = tmp_path / "root" / "kapi" / "2026-10-28"
    durum = json.loads((day / "durum.json").read_text())
    assert statuses["2026-10-28"]["durum"] == "eksik" and durum["durum"] == "eksik" and durum["parca_biten"] == 1 and durum["parca_beklenen"] == 2
    assert "DURUM: EKSİK" in (day / "RAPOR.md").read_text(encoding="utf-8")
    assert sorted(pd.read_csv(day / "sonuc.csv").address) == ["0xa", "0xb"]         # sonuç yine de yayımlanır


def test_merge_complete_run_is_tamam(tmp_path):
    make_shard(tmp_path / "shards", 0, "0xa", True)
    make_shard(tmp_path / "shards", 1, "0xb", True)
    assert merge_shards(tmp_path / "shards", tmp_path / "root", 2, "tam")["2026-10-28"]["durum"] == "tamam"
    assert "DURUM: EKSİK" not in (tmp_path / "root" / "kapi" / "2026-10-28" / "RAPOR.md").read_text(encoding="utf-8")


def test_merge_reports_distinct_code_hashes(tmp_path):
    for index, digest in enumerate(("a" * 64, "b" * 64)):
        folder = tmp_path / "shards" / f"stage1-{index}" / "2026-10-28"
        folder.mkdir(parents=True)
        pd.DataFrame([{"address": f"0x{index}", "asama1": "Yetersiz", "kod_hash": digest, "now_ms": 1_800_000_000_000}]).to_csv(folder / "sonuc.csv", index=False)
        (folder / "evren.json").write_text(json.dumps({"evren": 2}))
        (folder / "bitti.json").write_text("{}")
    status = merge_shards(tmp_path / "shards", tmp_path / "root", 2, "tam")["2026-10-28"]
    report = (tmp_path / "root" / "kapi" / "2026-10-28" / "RAPOR.md").read_text(encoding="utf-8")
    assert status["kod_hash_farkli"] is True and status["kod_hashler"] == ["a" * 64, "b" * 64]
    assert "Farklı kod hash'leri" in report and "`" + "a" * 64 + "`" in report


def test_merge_ignores_shared_universe_snapshot_artifact(tmp_path):
    # Run 29: publish tüm artifact'leri indirince kapi-evren/evren.json ({"liderler": ...}) sayı dosyası sanılıp KeyError verdi.
    make_shard(tmp_path / "shards", 0, "0xa", True)
    make_shard(tmp_path / "shards", 1, "0xb", True)
    (tmp_path / "shards" / "kapi-evren").mkdir()
    write_universe_snapshot(tmp_path / "shards" / "kapi-evren" / "evren.json", [board_row(A, 1000, 10)], [], FakeClient(1000))
    assert merge_shards(tmp_path / "shards", tmp_path / "root", 2, "tam")["2026-10-28"]["durum"] == "tamam"
