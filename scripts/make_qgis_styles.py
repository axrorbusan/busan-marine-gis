"""
QGIS 스타일 생성 — 해도 색상 체계를 QML로 저장하고 GeoPackage 기본 스타일로 등록
Writes QML styles to styles/ and registers them in the GeoPackage `layer_styles`
table so QGIS applies them automatically when a layer is added.

사용법: python scripts/make_qgis_styles.py --db output/busan_marine.gpkg
"""
import argparse
import datetime as dt
import os
import sqlite3

HEAD = "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n<qgis version=\"3.34.0\" styleCategories=\"Symbology|Labeling\">\n"


def opt(**kv):
    return "".join(f'<Option type="QString" name="{k}" value="{v}"/>' for k, v in kv.items())


def marker(color, shape="circle", size="2.4", outline="26,26,26,255", fill_alpha=255):
    r, g, b = color
    return (f'<symbol type="marker" name="0" alpha="1" clip_to_extent="1" force_rhr="0">'
            f'<layer class="SimpleMarker" enabled="1" pass="0" locked="0"><Option type="Map">'
            + opt(color=f"{r},{g},{b},{fill_alpha}", name=shape, size=size, size_unit="MM",
                  outline_color=outline, outline_width="0.25", outline_style="solid", angle="0")
            + "</Option></layer></symbol>")


def line(color, width, dash=False, name="0"):
    r, g, b = color
    return (f'<symbol type="line" name="{name}" alpha="1" clip_to_extent="1" force_rhr="0">'
            f'<layer class="SimpleLine" enabled="1" pass="0" locked="0"><Option type="Map">'
            + opt(line_color=f"{r},{g},{b},255", line_width=width, line_width_unit="MM",
                  line_style="dash" if dash else "solid", capstyle="round", joinstyle="round")
            + "</Option></layer></symbol>")


def fill(color, outline, outline_w="0.2", no_fill=False, dash=False):
    r, g, b = color
    o = outline
    return (f'<symbol type="fill" name="0" alpha="1" clip_to_extent="1" force_rhr="0">'
            f'<layer class="SimpleFill" enabled="1" pass="0" locked="0"><Option type="Map">'
            + opt(color=f"{r},{g},{b},255", style="no" if no_fill else "solid",
                  outline_color=f"{o[0]},{o[1]},{o[2]},255", outline_width=outline_w,
                  outline_width_unit="MM", outline_style="dash" if dash else "solid")
            + "</Option></layer></symbol>")


def single(sym):
    return f'<renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0" forceraster="0"><symbols>{sym}</symbols></renderer-v2>\n'


def labels(field, size=7, color="26,26,26,255", italic=False):
    return (f'<labeling type="simple"><settings calloutType="simple">'
            f'<text-style fieldName="{field}" fontSize="{size}" fontSizeUnit="Point" '
            f'textColor="{color}" fontItalic="{1 if italic else 0}" fontFamily="Noto Sans KR" '
            f'isExpression="{1 if any(c in field for c in "(+") else 0}"/>'
            f'<placement placement="0" dist="1" distUnits="MM"/>'
            f'<rendering scaleVisibility="0" obstacle="1"/></settings></labeling>\n')


MAGENTA = (176, 22, 122)
INK = (26, 26, 26)

STYLES = {
    "LNDARE": single(fill((244, 228, 180), (140, 122, 75))),
    "HRBARE": single(fill((255, 255, 255), MAGENTA, "0.4", no_fill=True, dash=True)),
    "SLCONS": ('<renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="0" forceraster="0">'
               '<rules key="r0">'
               '<rule key="r1" symbol="0" label="방파제 (CATSLC=1)" filter="&quot;catslc&quot; = \'CTC001\'"/>'
               '<rule key="r2" symbol="1" label="기타 인공안선" else="1"/>'
               '</rules><symbols>' + line(INK, "0.9", name="0") + line(INK, "0.3", name="1")
               + '</symbols></renderer-v2>\n'),
    "LNDMRK": ('<renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="0" forceraster="0">'
               '<rules key="r0">'
               '<rule key="r1" symbol="0" label="등대 (FUNCTN=33)" filter="&quot;functn&quot; = \'FNN033\'"/>'
               '<rule key="r2" symbol="1" label="육표" else="1"/>'
               '</rules><symbols>'
               + marker(MAGENTA, "star", "3.2").replace('name="0"', 'name="0"', 1)
               + marker((255, 255, 255), "circle", "1.6").replace('name="0"', 'name="1"', 1)
               + '</symbols></renderer-v2>\n') + labels("nobjnm", 7),
    "BERTHS": single(marker((255, 255, 255), "circle", "2.2", outline="176,22,122,255")) + labels("objnam", 5.5, "176,22,122,255"),
    "ACHARE": single(marker(MAGENTA, "diamond", "3")) + labels("catach_ko", 6, "176,22,122,255"),
    "SOUNDG": single(marker((80, 80, 80), "circle", "0.4")) + labels("round(&quot;valsou&quot;, 1)", 6, "60,60,60,255", italic=True),
}


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(__file__)
    ap.add_argument("--db", default=os.path.join(here, "..", "output", "busan_marine.gpkg"))
    ap.add_argument("--styles", default=os.path.join(here, "..", "styles"))
    a = ap.parse_args()
    os.makedirs(a.styles, exist_ok=True)

    con = sqlite3.connect(a.db)
    con.execute("""CREATE TABLE IF NOT EXISTS layer_styles (
        id INTEGER PRIMARY KEY AUTOINCREMENT, f_table_catalog TEXT(256), f_table_schema TEXT(256),
        f_table_name TEXT(256), f_geometry_column TEXT(256), styleName TEXT(30), styleQML TEXT,
        styleSLD TEXT, useAsDefault BOOLEAN, description TEXT, owner TEXT(30), ui TEXT(30),
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("DELETE FROM layer_styles")
    tables = {r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")}
    for name, body in STYLES.items():
        qml = HEAD + body + "</qgis>\n"
        with open(os.path.join(a.styles, f"{name}.qml"), "w", encoding="utf-8") as f:
            f.write(qml)
        if name in tables:
            con.execute("""INSERT INTO layer_styles (f_table_catalog, f_table_schema, f_table_name,
                f_geometry_column, styleName, styleQML, styleSLD, useAsDefault, description, owner,
                ui, update_time) VALUES ('', '', ?, 'geom', ?, ?, '', 1, '해도 양식', '', '', ?)""",
                        (name, f"{name}_chart", qml, dt.datetime.now().isoformat()))
    con.commit()
    con.close()
    print("styles:", ", ".join(STYLES))


if __name__ == "__main__":
    main()
