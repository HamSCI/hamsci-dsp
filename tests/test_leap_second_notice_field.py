"""The L1 metrology row carries the broadcast's leap-second advance notice.

hf-timestd's leap-second Kalman hold lost its only witness when the CHU FSK
decode retired (2026-09-04).  WWVB's dst_ls bits (and WWV/WWVH BCD second 3,
once that decoder is wired) carry the same notice a month ahead.  It rides on
the L1 metrology row as an optional field so fusion can arm the hold before
the boundary rather than after observing the step."""
import sqlite3

from hamsci_dsp.schemas import get_schema


def test_l1_metrology_has_optional_leap_second_notice():
    fields = {f["name"]: f for f in get_schema("L1", "metrology_measurements")["fields"]}
    f = fields["leap_second_notice"]
    assert f["type"] == "string" and f.get("required") is False
    assert set(f["enum"]) == {"none", "positive", "negative"}


def test_existing_l1_table_gains_the_column(tmp_path):
    from hamsci_dsp.io.sqlite_writer import SqliteDataProductWriter
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE L1_metrology_measurements (channel TEXT NOT NULL, timestamp_utc TEXT)")
    conn.commit(); conn.close()
    w = SqliteDataProductWriter(output_dir=tmp_path, db_path=db, product_level="L1",
                                product_name="metrology_measurements", channel="WWVB")
    try:
        cols = {r[1] for r in sqlite3.connect(str(db)).execute("PRAGMA table_info(L1_metrology_measurements)")}
        assert "leap_second_notice" in cols
    finally:
        w.close()
