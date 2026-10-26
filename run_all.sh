#!/usr/bin/env bash
# 전체 파이프라인 실행: DB 구축 → QGIS 스타일 → 해도 → 등대표
# 사용법: ./run_all.sh "<국립해양조사원 SHP 폴더>"
set -euo pipefail
RAW="${1:?원본 SHP 폴더 경로를 입력하세요}"
cd "$(dirname "$0")"
python3 scripts/build_db.py --raw "$RAW"
python3 scripts/make_qgis_styles.py
python3 scripts/make_chart.py
(cd scripts && python3 make_light_list.py)
echo "완료 → output/"
