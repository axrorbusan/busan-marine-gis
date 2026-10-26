"""
부산항 해도 양식 지도 제작 (A3, PDF/PNG)
Chart-style map of Busan Port from the GeoPackage built by build_db.py

사용법: python scripts/make_chart.py --db output/busan_marine.gpkg
"""
import argparse
import datetime as dt
import math
import os
import warnings

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.path import Path
from pyproj import Transformer

warnings.filterwarnings("ignore")
matplotlib.use("Agg")

CHART_CRS = 3395  # World Mercator (WGS84) — 해도 표준 도법
EXTENT = (128.965, 35.035, 129.165, 35.165)   # lon/lat
KO_FONT = "Noto Sans CJK KR"

# 해도 색상 (종이해도 관례)
LAND = "#F4E4B4"
SEA = "#FFFFFF"
SHALLOW = "#D7ECF7"
MAGENTA = "#B0167A"
INK = "#1A1A1A"


def pick_font():
    import glob
    for f in (glob.glob("/usr/share/fonts/**/NotoSansCJK-*.ttc", recursive=True)
              + glob.glob("/System/Library/Fonts/AppleSDGothicNeo.ttc")):
        try:
            font_manager.fontManager.addfont(f)
        except Exception:
            pass
    names = {f.name for f in font_manager.fontManager.ttflist}
    for n in (KO_FONT, "Noto Sans CJK JP", "Apple SD Gothic Neo", "AppleGothic",
              "NanumGothic", "Malgun Gothic"):
        if n in names:
            return n
    return "DejaVu Sans"


def flare_marker():
    """등화 표시 (magenta flare) — 물방울 모양 마커"""
    verts = [(0, 0), (0.18, 0.55), (0.0, 1.0), (-0.18, 0.55), (0, 0)]
    codes = [Path.MOVETO, Path.CURVE3, Path.CURVE3, Path.CURVE3, Path.CURVE3]
    p = Path(verts, codes)
    # 해도 관례대로 45° 기울임
    return p.transformed(matplotlib.transforms.Affine2D().rotate_deg(-45))


def dm(v, is_lat):
    d = int(abs(v))
    m = (abs(v) - d) * 60
    h = ("N" if v >= 0 else "S") if is_lat else ("E" if v >= 0 else "W")
    return f"{d}°{m:04.1f}'{h}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "output", "busan_marine.gpkg"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "output"))
    a = ap.parse_args()

    font = pick_font()
    plt.rcParams["font.family"] = [font, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    L = lambda name: gpd.read_file(a.db, layer=name).to_crs(CHART_CRS)
    land, slc, lm = L("LNDARE"), L("SLCONS"), L("LNDMRK")
    berths, sound, hrb, ach = L("BERTHS"), L("SOUNDG"), L("HRBARE"), L("ACHARE")

    tf = Transformer.from_crs(4326, CHART_CRS, always_xy=True)
    x0, y0 = tf.transform(EXTENT[0], EXTENT[1])
    x1, y1 = tf.transform(EXTENT[2], EXTENT[3])

    fig = plt.figure(figsize=(16.54, 11.69))            # A3 가로
    ax = fig.add_axes([0.045, 0.07, 0.70, 0.86])
    ax.set_facecolor(SEA)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal", adjustable="box")

    # ---- 육지 / 인공안선
    land.plot(ax=ax, color=LAND, edgecolor="#8C7A4B", linewidth=0.5, zorder=2)
    bw = slc[slc["catslc"] == "CTC001"]
    other = slc[slc["catslc"] != "CTC001"]
    other.plot(ax=ax, color=INK, linewidth=0.55, zorder=3)
    bw.plot(ax=ax, color=INK, linewidth=1.4, zorder=3)

    # ---- 항만구역 경계
    hrb.boundary.plot(ax=ax, color=MAGENTA, linewidth=1.0, linestyle=(0, (6, 3)), zorder=4)

    # ---- 수심 (해도식 표기: 정수 + 소수 아래첨자)
    for _, r in sound.iterrows():
        v = r["valsou"]
        if v < 0:
            continue
        whole, dec = int(v), int(round((v - int(v)) * 10)) % 10
        txt = f"${whole}_{{{dec}}}$" if dec else f"${whole}$"
        ax.text(r.geometry.x, r.geometry.y, txt, fontsize=6, color="#333333",
                ha="center", va="center", style="italic", zorder=5, clip_on=True)

    # ---- 선석 번호
    for _, r in berths.iterrows():
        if not r.get("objnam"):
            continue
        ax.text(r.geometry.x, r.geometry.y, r["objnam"], fontsize=4.2, color=MAGENTA,
                ha="center", va="center", zorder=6,
                bbox=dict(boxstyle="circle,pad=0.18", fc="white", ec=MAGENTA, lw=0.4))

    # ---- 정박지
    for _, r in ach.iterrows():
        ax.text(r.geometry.x, r.geometry.y, "⚓", fontsize=13, color=MAGENTA,
                ha="center", va="center", zorder=6, family="DejaVu Sans")

    # ---- 등대 / 육표
    lights = lm[lm["functn"] == "FNN033"]
    others = lm[lm["functn"] != "FNN033"]
    flare = flare_marker()
    ax.scatter(lights.geometry.x, lights.geometry.y, marker=flare, s=170,
               color=MAGENTA, edgecolor="none", zorder=7)
    ax.scatter(lights.geometry.x, lights.geometry.y, s=5, color=INK, zorder=8)
    ax.scatter(others.geometry.x, others.geometry.y, s=9, facecolor="white",
               edgecolor=INK, linewidth=0.6, zorder=7)

    # 주요 등대 명칭 (충돌방지등 등 반복 명칭은 생략)
    # 라벨 충돌 방지: 이미 표기한 등대에서 900m 이내면 생략
    named = lights[lights["nobjnm"].notna() & ~lights["nobjnm"].str.contains("충돌방지|케이블카|오리엔트")]
    placed = []
    for _, r in named.iterrows():
        p = r.geometry
        if any(p.distance(q) < 900 for q in placed):
            continue
        placed.append(p)
        ax.annotate(r["nobjnm"], (p.x, p.y), xytext=(5, -7), textcoords="offset points",
                    fontsize=6.2, color=INK, zorder=9, clip_on=True,
                    bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.75))

    # ---- 경위도 테두리 (해도식 분 눈금)
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_linewidth(1.6)
    inv = Transformer.from_crs(CHART_CRS, 4326, always_xy=True)
    step = 1 / 60  # 1'
    lon = math.ceil(EXTENT[0] / step) * step
    while lon < EXTENT[2]:
        x, _ = tf.transform(lon, EXTENT[1])
        minute = round(lon * 60) % 60
        major = minute % 2 == 0
        for yy, sgn in ((y0, 1), (y1, -1)):
            ax.plot([x, x], [yy, yy + sgn * (y1 - y0) * (0.012 if major else 0.006)],
                    color=INK, lw=0.7, clip_on=False, zorder=10)
        if major:
            ax.text(x, y0 - (y1 - y0) * 0.012, dm(lon, False), ha="center", va="top", fontsize=7)
            ax.text(x, y1 + (y1 - y0) * 0.008, dm(lon, False), ha="center", va="bottom", fontsize=7)
        lon += step
    lat = math.ceil(EXTENT[1] / step) * step
    while lat < EXTENT[3]:
        _, y = tf.transform(EXTENT[0], lat)
        minute = round(lat * 60) % 60
        major = minute % 2 == 0
        for xx, sgn in ((x0, 1), (x1, -1)):
            ax.plot([xx, xx + sgn * (x1 - x0) * (0.009 if major else 0.0045)], [y, y],
                    color=INK, lw=0.7, clip_on=False, zorder=10)
        if major:
            ax.text(x0 - (x1 - x0) * 0.006, y, dm(lat, True), ha="right", va="center",
                    fontsize=7, rotation=90)
            ax.text(x1 + (x1 - x0) * 0.006, y, dm(lat, True), ha="left", va="center",
                    fontsize=7, rotation=90)
        lat += step

    # ---- 축척 막대 (해리 / km)
    mid_lat = (EXTENT[1] + EXTENT[3]) / 2
    k = 1 / math.cos(math.radians(mid_lat))            # 메르카토르 축척계수
    nm = 1852 * k
    bx, by = x1 - nm * 2.6, y0 + (y1 - y0) * 0.035
    ax.add_patch(Rectangle((bx - nm * 0.25, by - (y1 - y0) * 0.012), nm * 2.5, (y1 - y0) * 0.042,
                           fc="white", ec=INK, lw=0.5, zorder=10.5))
    for i in range(2):
        ax.add_patch(Rectangle((bx + i * nm, by), nm, (y1 - y0) * 0.006,
                               fc=INK if i % 2 == 0 else "white", ec=INK, lw=0.6, zorder=11))
    ax.text(bx, by + (y1 - y0) * 0.012, "0", fontsize=6.5, ha="center", zorder=11)
    ax.text(bx + nm, by + (y1 - y0) * 0.012, "1", fontsize=6.5, ha="center", zorder=11)
    ax.text(bx + 2 * nm, by + (y1 - y0) * 0.012, "2 해리 (NM)", fontsize=6.5, ha="right", zorder=11)

    # ---- 축척 계산 (A3 출력 기준)
    ax_w_in = ax.get_position().width * fig.get_figwidth()
    fig.canvas.draw()
    bbox = ax.get_window_extent().transformed(fig.dpi_scale_trans.inverted())
    ground_m = (x1 - x0) / k
    scale = ground_m / (bbox.width * 0.0254)
    scale = int(round(scale / 1000) * 1000)

    # ---- 표제 (cartouche)
    side = fig.add_axes([0.77, 0.07, 0.205, 0.86])
    side.axis("off")
    y = 0.98
    def put(t, size, weight="normal", color=INK, dy=0.035):
        nonlocal y
        side.text(0.0, y, t, fontsize=size, weight=weight, color=color, va="top", wrap=True)
        y -= dy
    put("대한민국 · 남해안", 10)
    put("부산항", 26, "bold", dy=0.055)
    put("BUSAN HANG", 14, "bold", dy=0.045)
    put("해양공간정보 시범 해도 (포트폴리오)", 10.5, dy=0.04)
    put(f"축척 약 1:{scale:,} (A3 출력 기준)", 9)
    put("도법: 메르카토르 · 측지계: WGS84", 9)
    put("수심: 미터 (m)", 9, dy=0.05)

    legend = [
        Line2D([], [], marker=flare, color=MAGENTA, ls="", ms=13, label="등대·등화 (Light)"),
        Line2D([], [], marker="o", mfc="white", mec=INK, ls="", ms=5, label="육표 (Landmark)"),
        Line2D([], [], color=INK, lw=1.4, label="방파제 (Breakwater)"),
        Line2D([], [], color=INK, lw=0.6, label="인공안선 (Shoreline construction)"),
        Line2D([], [], color=MAGENTA, lw=1, ls=(0, (6, 3)), label="항만구역 (Harbour limit)"),
        Line2D([], [], marker="o", mfc="white", mec=MAGENTA, ls="", ms=7, label="선석 번호 (Berth)"),
        Line2D([], [], marker="$12_{4}$", color="#333333", ls="", ms=12, label="수심 12.4m (Sounding)"),
        Line2D([], [], marker="s", mfc=LAND, mec="#8C7A4B", ls="", ms=9, label="육지 (Land)"),
    ]
    side.legend(handles=legend, loc="upper left", bbox_to_anchor=(0, y), frameon=False,
                fontsize=8.5, title="범례 · Legend", title_fontsize=9.5, alignment="left")
    side.text(0, 0.30,
              "자료 출처\n"
              "· 국립해양조사원 공공데이터 (전자해도 기반 SHP,\n  2025.08 공개): 육표, 선석, 정박지, 항만구역, 인공안선\n"
              "· 해양수산부 1/25,000 연안정보도 수심 (2011)\n"
              "· 육지: 행정동 경계 (vuski/admdongkor, 2026.10)\n\n"
              "처리: Python (GeoPandas, GDAL) ETL → GeoPackage\n"
              "→ 품질검사 → 해도 양식 출력",
              fontsize=7.4, va="top", color="#333333", linespacing=1.45)
    side.text(0, 0.07, "항해용으로 사용 불가\nNOT FOR NAVIGATION", fontsize=11, weight="bold",
              color=MAGENTA, va="bottom")
    side.text(0, 0.0, f"제작: 악스로 (Axror Abduhamitov) · {dt.date.today():%Y.%m}",
              fontsize=7.5, va="bottom", color="#333333")

    os.makedirs(a.out, exist_ok=True)
    fig.savefig(os.path.join(a.out, "busan_port_chart.pdf"))
    fig.savefig(os.path.join(a.out, "busan_port_chart.png"), dpi=170)
    print("scale 1:", scale, "| font:", font)


if __name__ == "__main__":
    main()
