import os
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "pola_tanam.db"

app = Flask(__name__)
app.config["GEOAPIFY_API_KEY"] = os.getenv("GEOAPIFY_API_KEY", "YOUR_GEOAPIFY_KEY")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_columns(conn, table_name, columns):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    for name, col_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {col_type}")


def has_column(conn, table_name, column_name):
    return any(
        row["name"] == column_name
        for row in conn.execute(f"PRAGMA table_info({table_name})")
    )


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pola_tanam (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kode_petani TEXT NOT NULL DEFAULT '',
            nama_petani TEXT NOT NULL,
            kelompok_tani TEXT NOT NULL DEFAULT '',
            lokasi TEXT NOT NULL,
            alamat_lengkap TEXT NOT NULL DEFAULT '',
            telepon TEXT NOT NULL DEFAULT '',
            komoditas TEXT NOT NULL,
            kontrak_bulan INTEGER NOT NULL DEFAULT 1,
            target_yield REAL NOT NULL DEFAULT 0,
            lat REAL,
            lon REAL,
            created_at TEXT NOT NULL
        )
        """
    )

    ensure_columns(
        conn,
        "pola_tanam",
        {
            "kode_petani": "TEXT NOT NULL DEFAULT ''",
            "kelompok_tani": "TEXT NOT NULL DEFAULT ''",
            "alamat_lengkap": "TEXT NOT NULL DEFAULT ''",
            "telepon": "TEXT NOT NULL DEFAULT ''",
            "kontrak_bulan": "INTEGER NOT NULL DEFAULT 1",
            "target_yield": "REAL NOT NULL DEFAULT 0",
            "lat": "REAL",
            "lon": "REAL",
        },
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jadwal_tanam (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pola_id INTEGER NOT NULL,
            tanggal TEXT NOT NULL,
            jenis TEXT NOT NULL DEFAULT 'panen',
            kegiatan TEXT NOT NULL,
            estimasi_kg REAL NOT NULL DEFAULT 0,
            realisasi_kg REAL NOT NULL DEFAULT 0,
            qty_benih_kg REAL NOT NULL DEFAULT 0,
            qty_pemberian_bibit REAL NOT NULL DEFAULT 0,
            kode_bibit TEXT NOT NULL DEFAULT '',
            no_pendistribusian TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (pola_id) REFERENCES pola_tanam(id)
        )
        """
    )

    ensure_columns(
        conn,
        "jadwal_tanam",
        {
            "jenis": "TEXT NOT NULL DEFAULT 'panen'",
            "qty_benih_kg": "REAL NOT NULL DEFAULT 0",
            "qty_pemberian_bibit": "REAL NOT NULL DEFAULT 0",
            "kode_bibit": "TEXT NOT NULL DEFAULT ''",
            "no_pendistribusian": "TEXT NOT NULL DEFAULT ''",
            "realisasi_kg": "REAL NOT NULL DEFAULT 0",
        },
    )

    conn.commit()
    conn.close()


def parse_float(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def parse_int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_date_filter(period: str, value: str):
    where = ""
    params = []
    if not period or not value:
        return where, params

    if period == "month":
        where = "strftime('%Y-%m', tanggal) = ?"
        params = [value]
    elif period == "year":
        where = "strftime('%Y', tanggal) = ?"
        params = [value]
    elif period == "week":
        try:
            year_str, week_str = value.split("-W")
            where = "strftime('%Y', tanggal) = ? AND strftime('%W', tanggal) = ?"
            params = [year_str, f"{int(week_str):02d}"]
        except ValueError:
            pass
    return where, params


@app.route("/", methods=["GET"])
def dashboard():
    period = request.args.get("period", "")
    value = request.args.get("value", "")
    if period == "month":
        value = value or request.args.get("month_value", "")
    elif period == "week":
        value = value or request.args.get("week_value", "")
    elif period == "year":
        value = value or request.args.get("year_value", "")

    where, params = build_date_filter(period, value)

    conn = get_db()

    months = [
        row["month"]
        for row in conn.execute(
            "SELECT DISTINCT strftime('%Y-%m', tanggal) AS month FROM jadwal_tanam WHERE tanggal != '' ORDER BY month DESC"
        ).fetchall()
        if row["month"]
    ]
    years = [
        row["year"]
        for row in conn.execute(
            "SELECT DISTINCT strftime('%Y', tanggal) AS year FROM jadwal_tanam WHERE tanggal != '' ORDER BY year DESC"
        ).fetchall()
        if row["year"]
    ]
    weeks = [
        row["week"]
        for row in conn.execute(
            "SELECT DISTINCT (strftime('%Y', tanggal) || '-W' || printf('%02d', strftime('%W', tanggal))) AS week FROM jadwal_tanam WHERE tanggal != '' ORDER BY week DESC"
        ).fetchall()
        if row["week"]
    ]

    activity_query = "SELECT COUNT(*) AS total FROM jadwal_tanam"
    panen_query = "SELECT COUNT(*) AS total FROM jadwal_tanam WHERE jenis = 'panen'"
    distribusi_query_count = "SELECT COUNT(*) AS total FROM jadwal_tanam WHERE jenis = 'tanam_benih'"

    kode_query = """
        SELECT j.kode_bibit,
               p.komoditas,
               SUM(j.qty_pemberian_bibit) AS total_pemberian,
               SUM(j.qty_benih_kg) AS total_tanam
        FROM jadwal_tanam j
        JOIN pola_tanam p ON p.id = j.pola_id
        WHERE j.kode_bibit != ''
        GROUP BY j.kode_bibit, p.komoditas
        ORDER BY total_tanam DESC
    """
    distribusi_query = """
        SELECT j.no_pendistribusian,
               COUNT(*) AS total_aktivitas,
               SUM(j.qty_pemberian_bibit) AS total_bibit,
               GROUP_CONCAT(DISTINCT p.komoditas) AS komoditas
        FROM jadwal_tanam j
        JOIN pola_tanam p ON p.id = j.pola_id
        WHERE j.no_pendistribusian != ''
        GROUP BY j.no_pendistribusian
        ORDER BY total_aktivitas DESC
    """
    komoditas_query = """
        SELECT p.komoditas,
               SUM(p.target_yield) AS total_estimasi,
               SUM(CASE WHEN j.jenis = 'panen' THEN j.realisasi_kg ELSE 0 END) AS total_realisasi
        FROM pola_tanam p
        LEFT JOIN jadwal_tanam j ON j.pola_id = p.id
        GROUP BY p.komoditas
        ORDER BY total_estimasi DESC
    """
    bibit_komoditas_query = """
        SELECT p.komoditas,
               SUM(j.qty_pemberian_bibit) AS total_bibit
        FROM jadwal_tanam j
        JOIN pola_tanam p ON p.id = j.pola_id
        WHERE j.qty_pemberian_bibit > 0
        GROUP BY p.komoditas
        ORDER BY total_bibit DESC
    """

    if where:
        activity_query += f" WHERE {where}"
        panen_query += f" AND {where}"
        distribusi_query_count += f" AND {where}"
        kode_query = kode_query.replace("WHERE j.kode_bibit != ''", f"WHERE j.kode_bibit != '' AND {where}")
        distribusi_query = distribusi_query.replace("WHERE j.no_pendistribusian != ''", f"WHERE j.no_pendistribusian != '' AND {where}")
        komoditas_query = komoditas_query.replace("LEFT JOIN jadwal_tanam j ON j.pola_id = p.id", f"LEFT JOIN jadwal_tanam j ON j.pola_id = p.id AND {where}")
        komoditas_query = komoditas_query.replace("FROM pola_tanam p", f"FROM pola_tanam p WHERE p.id IN (SELECT DISTINCT pola_id FROM jadwal_tanam WHERE {where})")
        bibit_komoditas_query = bibit_komoditas_query.replace("WHERE j.qty_pemberian_bibit > 0", f"WHERE j.qty_pemberian_bibit > 0 AND {where}")

    total_aktivitas = conn.execute(activity_query, params).fetchone()["total"]
    total_panen = conn.execute(panen_query, params).fetchone()["total"]
    total_distribusi = conn.execute(distribusi_query_count, params).fetchone()["total"]
    total_mitra = conn.execute("SELECT COUNT(*) AS total FROM pola_tanam").fetchone()["total"]

    kode_bibit_rows = conn.execute(kode_query, params).fetchall()
    distribusi_rows = conn.execute(distribusi_query, params).fetchall()
    komoditas_rows = conn.execute(komoditas_query, params).fetchall()
    conn.close()

    return render_template(
        "dashboard.html",
        total_aktivitas=total_aktivitas,
        total_panen=total_panen,
        total_distribusi=total_distribusi,
        total_mitra=total_mitra,
        kode_bibit_rows=kode_bibit_rows,
        distribusi_rows=distribusi_rows,
        komoditas_rows=komoditas_rows,
        period=period,
        value=value,
        months=months,
        weeks=weeks,
        years=years,
    )


@app.route("/input", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        kode_petani = request.form.get("kode_petani", "").strip()
        nama_petani = request.form.get("nama_petani", "").strip()
        kelompok_tani = request.form.get("kelompok_tani", "").strip()
        lokasi = request.form.get("lokasi", "").strip()
        alamat_lengkap = request.form.get("alamat_lengkap", "").strip()
        telepon = request.form.get("telepon", "").strip()
        komoditas = request.form.get("komoditas", "").strip()
        kontrak_bulan = parse_int(request.form.get("kontrak_bulan", 1), 1)
        target_yield = parse_float(request.form.get("target_yield", 0))
        lat = request.form.get("lat")
        lon = request.form.get("lon")

        if all([kode_petani, nama_petani, lokasi, alamat_lengkap, komoditas]):
            conn = get_db()
            kontrak_lama_text = f"{kontrak_bulan} bulan"
            if has_column(conn, "pola_tanam", "kontrak_lama"):
                conn.execute(
                    """
                    INSERT INTO pola_tanam
                    (kode_petani, nama_petani, kelompok_tani, lokasi, alamat_lengkap, telepon, komoditas, kontrak_lama, kontrak_bulan, target_yield, lat, lon, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        kode_petani,
                        nama_petani,
                        kelompok_tani,
                        lokasi,
                        alamat_lengkap,
                        telepon,
                        komoditas,
                        kontrak_lama_text,
                        kontrak_bulan,
                        target_yield,
                        parse_float(lat) if lat else None,
                        parse_float(lon) if lon else None,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO pola_tanam
                    (kode_petani, nama_petani, kelompok_tani, lokasi, alamat_lengkap, telepon, komoditas, kontrak_bulan, target_yield, lat, lon, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        kode_petani,
                        nama_petani,
                        kelompok_tani,
                        lokasi,
                        alamat_lengkap,
                        telepon,
                        komoditas,
                        kontrak_bulan,
                        target_yield,
                        parse_float(lat) if lat else None,
                        parse_float(lon) if lon else None,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
            conn.commit()
            conn.close()
        return redirect(url_for("list_pola"))

    conn = get_db()
    return render_template(
        "index.html",
        edit_row=None,
        geoapify_key=app.config["GEOAPIFY_API_KEY"],
    )


@app.get("/edit/<int:row_id>")
def edit_row(row_id: int):
    conn = get_db()
    row = conn.execute(
        """
        SELECT id, kode_petani, nama_petani, kelompok_tani, lokasi, alamat_lengkap, telepon, komoditas,
               kontrak_bulan, target_yield, lat, lon
        FROM pola_tanam
        WHERE id = ?
        """,
        (row_id,),
    ).fetchone()
    conn.close()

    return render_template(
        "index.html",
        edit_row=row,
        geoapify_key=app.config["GEOAPIFY_API_KEY"],
    )


@app.post("/update/<int:row_id>")
def update_row(row_id: int):
    kode_petani = request.form.get("kode_petani", "").strip()
    nama_petani = request.form.get("nama_petani", "").strip()
    kelompok_tani = request.form.get("kelompok_tani", "").strip()
    lokasi = request.form.get("lokasi", "").strip()
    alamat_lengkap = request.form.get("alamat_lengkap", "").strip()
    telepon = request.form.get("telepon", "").strip()
    komoditas = request.form.get("komoditas", "").strip()
    kontrak_bulan = parse_int(request.form.get("kontrak_bulan", 1), 1)
    target_yield = parse_float(request.form.get("target_yield", 0))
    lat = request.form.get("lat")
    lon = request.form.get("lon")

    if all([kode_petani, nama_petani, lokasi, alamat_lengkap, komoditas]):
        conn = get_db()
        kontrak_lama_text = f"{kontrak_bulan} bulan"
        if has_column(conn, "pola_tanam", "kontrak_lama"):
            conn.execute(
                """
                UPDATE pola_tanam
                SET kode_petani = ?, nama_petani = ?, kelompok_tani = ?, lokasi = ?, alamat_lengkap = ?, telepon = ?,
                    komoditas = ?, kontrak_lama = ?, kontrak_bulan = ?, target_yield = ?, lat = ?, lon = ?
                WHERE id = ?
                """,
                (
                    kode_petani,
                    nama_petani,
                    kelompok_tani,
                    lokasi,
                    alamat_lengkap,
                    telepon,
                    komoditas,
                    kontrak_lama_text,
                    kontrak_bulan,
                    target_yield,
                    parse_float(lat) if lat else None,
                    parse_float(lon) if lon else None,
                    row_id,
                ),
            )
        else:
            conn.execute(
                """
            UPDATE pola_tanam
            SET kode_petani = ?, nama_petani = ?, kelompok_tani = ?, lokasi = ?, alamat_lengkap = ?, telepon = ?,
                komoditas = ?, kontrak_bulan = ?, target_yield = ?, lat = ?, lon = ?
            WHERE id = ?
            """,
            (
                kode_petani,
                nama_petani,
                kelompok_tani,
                lokasi,
                alamat_lengkap,
                telepon,
                komoditas,
                kontrak_bulan,
                    target_yield,
                    parse_float(lat) if lat else None,
                    parse_float(lon) if lon else None,
                    row_id,
                ),
            )
        conn.commit()
        conn.close()

    return redirect(url_for("list_pola"))


@app.get("/list")
def list_pola():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, kode_petani, nama_petani, kelompok_tani, lokasi, alamat_lengkap, telepon, komoditas,
               kontrak_bulan, target_yield, lat, lon, created_at
        FROM pola_tanam
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("list.html", rows=rows)


@app.post("/delete/<int:row_id>")
def delete_row(row_id: int):
    conn = get_db()
    conn.execute("DELETE FROM pola_tanam WHERE id = ?", (row_id,))
    conn.execute("DELETE FROM jadwal_tanam WHERE pola_id = ?", (row_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("list_pola"))


@app.route("/schedule/<int:row_id>", methods=["GET", "POST"])
def schedule(row_id: int):
    conn = get_db()
    pola = conn.execute(
        """
        SELECT id, kode_petani, nama_petani, kelompok_tani, lokasi, alamat_lengkap, telepon, komoditas,
               kontrak_bulan, target_yield
        FROM pola_tanam WHERE id = ?
        """,
        (row_id,),
    ).fetchone()

    if not pola:
        conn.close()
        return redirect(url_for("index"))

    if request.method == "POST":
        tanggal = request.form.get("tanggal", "").strip()
        jenis = request.form.get("jenis", "panen").strip() or "panen"
        kegiatan = request.form.get("kegiatan", "").strip()
        estimasi_kg = parse_float(request.form.get("estimasi_kg", 0))
        realisasi_kg = parse_float(request.form.get("realisasi_kg", 0))
        qty_benih_kg = parse_float(request.form.get("qty_benih_kg", 0))
        qty_pemberian_bibit = parse_float(request.form.get("qty_pemberian_bibit", 0))
        kode_bibit = request.form.get("kode_bibit", "").strip()
        no_pendistribusian = request.form.get("no_pendistribusian", "").strip()
        if tanggal and kegiatan:
            conn.execute(
                """
                INSERT INTO jadwal_tanam (pola_id, tanggal, jenis, kegiatan, estimasi_kg, realisasi_kg, qty_benih_kg, qty_pemberian_bibit, kode_bibit, no_pendistribusian, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    tanggal,
                    jenis,
                    kegiatan,
                    estimasi_kg,
                    realisasi_kg,
                    qty_benih_kg,
                    qty_pemberian_bibit,
                    kode_bibit,
                    no_pendistribusian,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
        conn.close()
        return redirect(url_for("schedule", row_id=row_id))

    jadwal = conn.execute(
        """
        SELECT id, tanggal, jenis, kegiatan, estimasi_kg, realisasi_kg, qty_benih_kg, qty_pemberian_bibit, kode_bibit, no_pendistribusian
        FROM jadwal_tanam
        WHERE pola_id = ?
        ORDER BY tanggal ASC
        """,
        (row_id,),
    ).fetchall()

    total_estimasi = sum(
        parse_float(item["estimasi_kg"]) for item in jadwal if item["jenis"] == "panen"
    )
    total_realisasi = sum(
        parse_float(item["realisasi_kg"]) for item in jadwal if item["jenis"] == "panen"
    )
    total_tanam_benih = sum(
        parse_float(item["qty_benih_kg"])
        for item in jadwal
        if item["jenis"] == "tanam_benih"
    )
    total_pemberian_bibit = sum(parse_float(item["qty_pemberian_bibit"]) for item in jadwal)
    target_yield = parse_float(pola["target_yield"])
    sisa = target_yield - total_estimasi
    if sisa < 0:
        sisa = 0

    conn.close()
    return render_template(
        "schedule.html",
        pola=pola,
        jadwal=jadwal,
        total_estimasi=total_estimasi,
        total_realisasi=total_realisasi,
        sisa=sisa,
        total_tanam_benih=total_tanam_benih,
        total_pemberian_bibit=total_pemberian_bibit,
        edit_item=None,
    )


@app.get("/schedule/<int:row_id>/edit/<int:item_id>")
def edit_schedule(row_id: int, item_id: int):
    conn = get_db()
    pola = conn.execute(
        """
        SELECT id, kode_petani, nama_petani, kelompok_tani, lokasi, alamat_lengkap, telepon, komoditas,
               kontrak_bulan, target_yield
        FROM pola_tanam WHERE id = ?
        """,
        (row_id,),
    ).fetchone()
    item = conn.execute(
        """
        SELECT id, tanggal, jenis, kegiatan, estimasi_kg, realisasi_kg, qty_benih_kg, qty_pemberian_bibit, kode_bibit, no_pendistribusian
        FROM jadwal_tanam WHERE id = ? AND pola_id = ?
        """,
        (item_id, row_id),
    ).fetchone()
    jadwal = conn.execute(
        """
        SELECT id, tanggal, jenis, kegiatan, estimasi_kg, realisasi_kg, qty_benih_kg, qty_pemberian_bibit, kode_bibit, no_pendistribusian
        FROM jadwal_tanam
        WHERE pola_id = ?
        ORDER BY tanggal ASC
        """,
        (row_id,),
    ).fetchall()

    total_estimasi = sum(
        parse_float(entry["estimasi_kg"])
        for entry in jadwal
        if entry["jenis"] == "panen"
    )
    total_realisasi = sum(
        parse_float(entry["realisasi_kg"])
        for entry in jadwal
        if entry["jenis"] == "panen"
    )
    total_tanam_benih = sum(
        parse_float(entry["qty_benih_kg"])
        for entry in jadwal
        if entry["jenis"] == "tanam_benih"
    )
    total_pemberian_bibit = sum(
        parse_float(entry["qty_pemberian_bibit"]) for entry in jadwal
    )
    target_yield = parse_float(pola["target_yield"]) if pola else 0
    sisa = target_yield - total_estimasi
    if sisa < 0:
        sisa = 0
    conn.close()

    if not pola or not item:
        return redirect(url_for("schedule", row_id=row_id))

    return render_template(
        "schedule.html",
        pola=pola,
        jadwal=jadwal,
        total_estimasi=total_estimasi,
        total_realisasi=total_realisasi,
        sisa=sisa,
        total_tanam_benih=total_tanam_benih,
        total_pemberian_bibit=total_pemberian_bibit,
        edit_item=item,
    )


@app.post("/schedule/<int:row_id>/update/<int:item_id>")
def update_schedule(row_id: int, item_id: int):
    tanggal = request.form.get("tanggal", "").strip()
    jenis = request.form.get("jenis", "panen").strip() or "panen"
    kegiatan = request.form.get("kegiatan", "").strip()
    estimasi_kg = parse_float(request.form.get("estimasi_kg", 0))
    realisasi_kg = parse_float(request.form.get("realisasi_kg", 0))
    qty_benih_kg = parse_float(request.form.get("qty_benih_kg", 0))
    qty_pemberian_bibit = parse_float(request.form.get("qty_pemberian_bibit", 0))
    kode_bibit = request.form.get("kode_bibit", "").strip()
    no_pendistribusian = request.form.get("no_pendistribusian", "").strip()

    if tanggal and kegiatan:
        conn = get_db()
        conn.execute(
            """
            UPDATE jadwal_tanam
            SET tanggal = ?, jenis = ?, kegiatan = ?, estimasi_kg = ?, realisasi_kg = ?, qty_benih_kg = ?,
                qty_pemberian_bibit = ?, kode_bibit = ?, no_pendistribusian = ?
            WHERE id = ? AND pola_id = ?
            """,
            (
                tanggal,
                jenis,
                kegiatan,
                estimasi_kg,
                realisasi_kg,
                qty_benih_kg,
                qty_pemberian_bibit,
                kode_bibit,
                no_pendistribusian,
                item_id,
                row_id,
            ),
        )
        conn.commit()
        conn.close()
    return redirect(url_for("schedule", row_id=row_id))


@app.post("/schedule/<int:row_id>/delete/<int:item_id>")
def delete_schedule(row_id: int, item_id: int):
    conn = get_db()
    conn.execute("DELETE FROM jadwal_tanam WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("schedule", row_id=row_id))


@app.get("/distribution/<no_pendistribusian>")
def distribution_detail(no_pendistribusian: str):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT j.tanggal, j.jenis, j.kegiatan, j.qty_pemberian_bibit, j.qty_benih_kg,
               j.estimasi_kg, j.realisasi_kg, j.kode_bibit, j.no_pendistribusian,
               p.nama_petani, p.kode_petani, p.komoditas, p.lokasi
        FROM jadwal_tanam j
        JOIN pola_tanam p ON p.id = j.pola_id
        WHERE j.no_pendistribusian = ?
        ORDER BY j.tanggal ASC
        """,
        (no_pendistribusian,),
    ).fetchall()
    conn.close()
    return render_template("distribution.html", rows=rows, no_pendistribusian=no_pendistribusian)


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
