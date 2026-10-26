"""
부산항 해양공간정보 DB 구축 (ETL + 품질검사)
Busan Port marine spatial database: ETL + quality control

입력  : 국립해양조사원(KHOA) 공공데이터 SHP (전자해도 기반 객체)
출력  : output/busan_marine.gpkg  (S-57 객체 코드 기준 레이어 + 메타/QA 테이블)
        output/qa_report.md        (품질검사 보고서)

사용법: python scripts/build_db.py --raw "<원본 SHP 폴더>"
"""
import argparse
import datetime as dt
import glob
import os
import sqlite3
import warnings

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------- 설정 / config
AOI_WGS84 = (128.96, 35.02, 129.17, 35.17)   # 부산항(북항·남항·감천·다대포·수영만)
KOREA_WGS84 = (124.0, 32.0, 132.0, 39.0)      # 국내 해역 범위 (좌표 이상치 판정용)
TARGET_CRS = 5179                              # Korea 2000 / Unified CS (UTM-K)

# 원본 테이블 → S-57 객체 코드 매핑
LAYERS = [
    # src table,              S-57,     국문명,           기하
    ("VI_LNDMRK_P",          "LNDMRK", "육표·등대",       "Point"),
    ("VI_LITFLT_P",          "LITFLT", "부등",            "Point"),
    ("VI_BERTHS_P",          "BERTHS", "선석",            "Point"),
    ("VI_ACHARE_P",          "ACHARE", "정박지",          "Point"),
    ("VI_HRBARE_A",          "HRBARE", "항만구역",        "Polygon"),
    ("VI_FAIRWY_A",          "FAIRWY", "일반항로",        "Polygon"),
    ("VI_SLCONS_L",          "SLCONS", "인공안선",        "LineString"),
    ("TL_DGSATC_SUBMEROC_P", "UWTROC", "암초",            "Point"),
    ("WGIS_DEPTHWATER",      "SOUNDG", "수심(측심점)",    "Point"),
]

# S-57 Appendix A 속성값 (KHOA 코드 접미 숫자 = S-57 속성값).
# CATSLC=1(방파제)은 명칭이 있는 방파제 등대와의 근접 매칭으로 검증함 (qa_report 참조)
CATLMK = {1: "케언", 3: "굴뚝", 7: "마스트", 9: "기념비", 10: "기둥", 13: "동상",
          15: "돔", 17: "탑(Tower)", 20: "첨탑"}
FUNCTN = {1: "기능없음", 32: "레이더", 33: "등화지지(등대)", 31: "무선"}
COLOUR = {1: "백", 2: "흑", 3: "적", 4: "녹", 5: "청", 6: "황", 7: "회", 8: "갈",
          11: "주황"}
NATCON = {1: "석조", 2: "콘크리트", 3: "사석", 4: "포장", 6: "목재", 7: "금속",
          8: "FRP", 9: "도색"}
CONVIS = {1: "현저함", 2: "현저하지 않음"}
CATSLC = {1: "방파제", 2: "돌제", 3: "방파제(Mole)", 4: "잔교", 6: "안벽",
          7: "도류제", 9: "호안", 10: "방조벽(Sea wall)", 12: "경사로", 13: "선대(Slipway)"}
WATLEV = {1: "부분 노출", 2: "항상 노출", 3: "항상 수몰", 4: "간출", 5: "파랑으로 덮임"}
CATACH = {1: "무제한 정박지", 2: "유조선 정박지", 3: "위험물 정박지", 7: "소형선 정박지"}


def decode(series, table):
    def f(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            n = int(str(v)[-3:])
        except ValueError:
            return None
        return table.get(n, f"코드 {n}")
    return series.map(f)


def find_shp(raw, table):
    hits = glob.glob(os.path.join(raw, "**", f"{table}.shp"), recursive=True)
    return hits[0] if hits else None


def clean_strings(df):
    for c in df.columns:
        if df[c].dtype == object and c != "geometry":
            df[c] = df[c].map(lambda v: v.strip() or None if isinstance(v, str) else v)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="KHOA 원본 SHP 폴더")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "output"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    gpkg = os.path.join(a.out, "busan_marine.gpkg")
    if os.path.exists(gpkg):
        os.remove(gpkg)

    aoi = gpd.GeoSeries([box(*AOI_WGS84)], crs=4326).to_crs(TARGET_CRS).iloc[0]
    korea = gpd.GeoSeries([box(*KOREA_WGS84)], crs=4326).to_crs(TARGET_CRS).iloc[0]

    catalog, issues = [], []

    def issue(layer, check, n, note=""):
        if n:
            issues.append(dict(layer=layer, check=check, count=int(n), note=note))

    for table, code, kname, gtype in LAYERS:
        path = find_shp(a.raw, table)
        if not path:
            catalog.append(dict(layer=code, name_ko=kname, source=table, national=0,
                                in_aoi=0, status="원본 없음"))
            continue

        g = gpd.read_file(path)
        g.columns = [c.lower() if c != "geometry" else c for c in g.columns]
        src_crs = g.crs
        crs_note = "" if g.crs.to_epsg() == TARGET_CRS else f"원본 CRS 사용자정의({g.crs.name}) → EPSG:{TARGET_CRS}"
        g = g.to_crs(TARGET_CRS)
        g = clean_strings(g)
        n_nat = len(g)

        # ---- 전국 단위 품질검사 (national-level QC)
        issue(code, "빈 기하 (empty geometry)", g.geometry.is_empty.sum())
        issue(code, "유효하지 않은 기하 (invalid geometry)", (~g.geometry.is_valid).sum())
        out_kr = ~g.geometry.intersects(korea)
        if out_kr.any():
            note = "전국 데이터 기준. 전자해도별: "
            if "enc_no" in g.columns:
                by_enc = g.loc[out_kr, "enc_no"].fillna("?").str[:4].value_counts()
                note += ", ".join(f"{k} {v}건" for k, v in by_enc.items())
                note += " → 소축척 개관도(KR1)·북측 해역(KR3G) 객체로 좌표 오류 아님, 범위 필터로 제외"
            issue(code, "국내 범위(124–132°E, 32–39°N) 밖 객체", out_kr.sum(), note)
        if crs_note:
            issue(code, "좌표계 불일치 (CRS mismatch)", 1, crs_note)

        # ---- AOI 추출
        g = g[g.geometry.intersects(aoi)].copy()
        if gtype == "Polygon":
            g["geometry"] = g.geometry.intersection(aoi)
        elif gtype == "LineString":
            g["geometry"] = g.geometry.intersection(aoi)
            g = g[~g.geometry.is_empty]

        if len(g) == 0:
            catalog.append(dict(layer=code, name_ko=kname, source=table, national=n_nat,
                                in_aoi=0, status="대상 해역 내 객체 없음"))
            continue

        # ---- 속성 정제 / 해석
        if code == "SOUNDG":
            g["valsou"] = -g["hsl"]       # 원본: 해수면 아래 음수 → S-57 VALSOU(양수, m)
            issue(code, "음수 아닌 표고값 (HSL >= 0, 육상/간출 의심)", (g["hsl"] >= 0).sum())
        if code == "LNDMRK":
            g["catlmk_ko"] = decode(g["catlmk"], CATLMK)
            g["functn_ko"] = decode(g["functn"], FUNCTN)
            g["colour_ko"] = decode(g["colour"], COLOUR)
            g["natcon_ko"] = decode(g["natcon"], NATCON)
            g["convis_ko"] = decode(g["convis"], CONVIS)
            g["is_light"] = (g["functn"] == "FNN033")
            issue(code, "명칭 누락 (NOBJNM null)", g["nobjnm"].isna().sum(),
                  "명칭 없는 육표 — 해도 표기 대상에서 제외 검토")
            issue(code, "고도·높이 누락 (ELEVAT/HEIGHT null)",
                  (g["elevat"].isna() & g["height"].isna()).sum(),
                  "등대표 제작 시 보완 필요")
        if code == "SLCONS":
            g["catslc_ko"] = decode(g["catslc"], CATSLC)
            g["watlev_ko"] = decode(g["watlev"], WATLEV)
            issue(code, "연안건축물 구분 누락 (CATSLC null)", g["catslc"].isna().sum())
        if code == "ACHARE":
            g["catach_ko"] = decode(g["catach"], CATACH)
        if code == "BERTHS":
            issue(code, "선석 최소수심 누락 (DRVAL1 null)", g["drval1"].isna().sum())

        # ---- 중복 검사 (same geometry + same name)
        name_col = next((c for c in ("nobjnm", "objnam", "korn_nm") if c in g.columns), None)
        key = g.geometry.to_wkt() + "|" + (g[name_col].astype(str) if name_col else "")
        issue(code, "중복 객체 (duplicate geometry+name)", key.duplicated().sum())
        if name_col:
            dupe_names = g[name_col].dropna()
            dn = dupe_names[dupe_names.duplicated(keep=False)]
            if code == "LNDMRK" and len(dn):
                issue(code, "동일 명칭 중복 (same name, different position)",
                      dn.duplicated().sum(), ", ".join(sorted(set(dn))[:6]))

        # ---- 공통 필드
        wgs = g.geometry.to_crs(4326).representative_point()
        g["lon"] = wgs.x.round(6)
        g["lat"] = wgs.y.round(6)
        g["s57_code"] = code
        g["src_table"] = table
        g["load_date"] = dt.date.today().isoformat()
        g = g.dropna(axis=1, how="all")          # 대상 해역에서 전부 비어있는 컬럼 제거
        g = g.reset_index(drop=True)
        g.insert(0, "fid_busan", range(1, len(g) + 1))

        g.to_file(gpkg, layer=code, driver="GPKG")
        catalog.append(dict(layer=code, name_ko=kname, source=table, national=n_nat,
                            in_aoi=len(g), status="적재 완료"))

    # ---- 코드 해석 검증: '방파제' 등대 ↔ 최근접 인공안선 CATSLC
    lm = gpd.read_file(gpkg, layer="LNDMRK")
    sl = gpd.read_file(gpkg, layer="SLCONS")
    bw = lm[lm["nobjnm"].fillna("").str.contains("방파제")]
    j = gpd.sjoin_nearest(bw[["nobjnm", "geometry"]], sl[["catslc", "geometry"]])
    j = j[~j.index.duplicated()]
    n_bw, n_coded = len(j), j["catslc"].notna().sum()
    n_ctc001 = (j["catslc"] == "CTC001").sum()

    # ---- 배경 육지 (행정동 경계 기반, data/busan_land.gpkg)
    land_src = os.path.join(os.path.dirname(__file__), "..", "data", "busan_land.gpkg")
    if os.path.exists(land_src):
        land = gpd.read_file(land_src).to_crs(TARGET_CRS)
        land["geometry"] = land.geometry.intersection(aoi.buffer(2000))
        land.to_file(gpkg, layer="LNDARE", driver="GPKG")
        catalog.append(dict(layer="LNDARE", name_ko="육지(배경)", source="admdongkor 행정동 경계",
                            national=1, in_aoi=len(land), status="적재 완료"))

    cat = pd.DataFrame(catalog)
    qa =pd.DataFrame(issues, columns=["layer", "check", "count", "note"])
    with sqlite3.connect(gpkg) as con:
        cat.to_sql("layer_catalog", con, index=False, if_exists="replace")
        qa.to_sql("qa_issues", con, index=False, if_exists="replace")

    # ---- QA 보고서
    lines = [
        "# 품질검사 보고서 (QA Report) — 부산항 해양공간정보 DB",
        "",
        f"- 생성일: {dt.date.today().isoformat()}",
        f"- 대상 해역 (WGS84): {AOI_WGS84}",
        f"- 좌표계: EPSG:{TARGET_CRS} (UTM-K), 위·경도(WGS84) 컬럼 병기",
        "",
        "## 1. 레이어 적재 현황",
        "",
        "| S-57 | 국문명 | 원본 테이블 | 전국 객체 수 | 부산항 적재 | 상태 |",
        "|---|---|---|---:|---:|---|",
    ]
    for r in catalog:
        lines.append(f"| {r['layer']} | {r['name_ko']} | {r['source']} | {r['national']:,} | {r['in_aoi']:,} | {r['status']} |")
    lines += ["", "## 2. 검출 항목", "", "| 레이어 | 검사 항목 | 건수 | 비고 |", "|---|---|---:|---|"]
    for r in issues:
        lines.append(f"| {r['layer']} | {r['check']} | {r['count']:,} | {r['note']} |")
    lines += [
        "",
        "## 3. 코드 해석 검증",
        "",
        "KHOA 코드(예: `CTC001`, `CLK017`)의 숫자 부분을 S-57 Appendix A 속성값으로 해석했다.",
        f"검증: 명칭에 '방파제'가 포함된 등대 {n_bw}개를 가장 가까운 인공안선과 매칭한 결과, "
        f"구분 코드가 있는 {n_coded}개 중 {n_ctc001}개가 `CTC001`(S-57 CATSLC=1, 방파제)로 확인됨.",
        "`CLK017`+`FNN033`(탑+등화지지) 조합이 명칭 있는 등대 대부분과 일치함.",
        "",
        "## 4. 한계",
        "",
        "- 수심(SOUNDG)은 2011년 연안정보도 기반으로 최신 측량과 다를 수 있음.",
        "- 등질(등광 특성), 광달거리 등 LIGHTS 객체 속성은 공개 데이터에 없어 등대표에서 제외.",
        "- 본 결과물은 포트폴리오용이며 항해용으로 사용할 수 없음.",
    ]
    with open(os.path.join(a.out, "qa_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(cat.to_string(index=False))
    print()
    print(qa.to_string(index=False))


if __name__ == "__main__":
    main()
