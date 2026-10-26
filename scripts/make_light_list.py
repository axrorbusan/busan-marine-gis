"""
등대표 (Light List) 자동 생성 — 항해용 간행물 양식
Builds a light-list publication (CSV + PDF) from the LNDMRK layer.

사용법: python scripts/make_light_list.py --db output/busan_marine.gpkg
"""
import argparse
import datetime as dt
import os
import warnings

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from make_chart import pick_font

warnings.filterwarnings("ignore")
matplotlib.use("Agg")


def dms(v, is_lat):
    d = int(abs(v))
    m = (abs(v) - d) * 60
    h = ("N" if v >= 0 else "S") if is_lat else ("E" if v >= 0 else "W")
    return f"{d:d}°{m:06.3f}′{h}"


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(__file__)
    ap.add_argument("--db", default=os.path.join(here, "..", "output", "busan_marine.gpkg"))
    ap.add_argument("--out", default=os.path.join(here, "..", "output"))
    a = ap.parse_args()

    lm = gpd.read_file(a.db, layer="LNDMRK")
    lights = lm[(lm["functn"] == "FNN033") & lm["nobjnm"].notna()].copy()

    # 동일 명칭+동일 위치 중복 제거, 서→동 (경도순) 수록 — 간행물 관례대로 지리적 순서
    lights = lights.drop_duplicates(subset=["nobjnm", "lon", "lat"])
    lights = lights.sort_values(["lon", "lat"]).reset_index(drop=True)
    lights["no"] = [f"BS-{i:03d}" for i in range(1, len(lights) + 1)]

    table = lights.assign(
        위도=lights["lat"].map(lambda v: dms(v, True)),
        경도=lights["lon"].map(lambda v: dms(v, False)),
    )[["no", "nobjnm", "objnam", "위도", "경도", "catlmk_ko", "colour_ko", "natcon_ko",
       "convis_ko", "enc_no"]]
    table.columns = ["번호", "명칭", "영문명", "위도", "경도", "구조", "색상", "재질",
                     "현저성", "전자해도"]
    table = table.fillna("—")

    os.makedirs(a.out, exist_ok=True)
    table.to_csv(os.path.join(a.out, "busan_light_list.csv"), index=False, encoding="utf-8-sig")

    # ---- PDF (A4 가로, 쪽당 26행)
    font = pick_font()
    plt.rcParams["font.family"] = [font, "DejaVu Sans"]
    widths = [0.065, 0.17, 0.17, 0.10, 0.11, 0.075, 0.05, 0.07, 0.09, 0.08]
    per_page = 26
    pages = [table.iloc[i:i + per_page] for i in range(0, len(table), per_page)]
    with PdfPages(os.path.join(a.out, "busan_light_list.pdf")) as pdf:
        for pi, chunk in enumerate(pages, 1):
            fig = plt.figure(figsize=(11.69, 8.27))
            fig.text(0.04, 0.95, "등대표 (Light List) — 부산항", fontsize=16, weight="bold")
            fig.text(0.04, 0.915,
                     f"수록 {len(table)}기 · 서→동 순 · 위치 WGS84 · 출처: 국립해양조사원 전자해도 기반 공공데이터 (2025.08)",
                     fontsize=8.5, color="#444")
            fig.text(0.96, 0.95, f"{pi} / {len(pages)}", fontsize=9, ha="right")
            ax = fig.add_axes([0.04, 0.08, 0.92, 0.81])
            ax.axis("off")
            t = ax.table(cellText=chunk.values.tolist(), colLabels=list(table.columns),
                         colWidths=widths, loc="upper left", cellLoc="left")
            t.auto_set_font_size(False)
            t.set_fontsize(7.4)
            t.scale(1, 1.32)
            for (r, c), cell in t.get_celld().items():
                cell.set_linewidth(0.3)
                if r == 0:
                    cell.set_facecolor("#1F3A5F")
                    cell.set_text_props(color="white", weight="bold")
                elif r % 2 == 0:
                    cell.set_facecolor("#F2F5F9")
            fig.text(0.04, 0.035,
                     "주: 등질(등광 특성)·광달거리·등고는 공개 데이터에 포함되지 않아 수록하지 않음. "
                     "포트폴리오용 자료이며 항해용으로 사용할 수 없음.",
                     fontsize=7.5, color="#555")
            fig.text(0.96, 0.035, f"제작: 악스로 (Axror Abduhamitov) · {dt.date.today():%Y.%m}",
                     fontsize=7.5, color="#555", ha="right")
            pdf.savefig(fig)
            plt.close(fig)
    print("lights:", len(table), "| pages:", len(pages))


if __name__ == "__main__":
    main()
