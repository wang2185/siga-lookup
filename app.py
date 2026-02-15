"""
시가표준액/공시가격 종합 조회 포털
Flask + 모듈별 조회 (WeTax/ETAX/data.go.kr/HomeTax)
"""

from flask import Flask, render_template, request, jsonify, session

from config import Config
from modules.base import PROPERTY_TYPES, LookupResult
from modules.address import parse_address, search_juso, search_vworld, extract_address_components
from modules.building_nonseoul import WeTaxModule
from modules.building_seoul import (
    SeoulETaxModule, get_dong_cache, ETAX_SIGU, ETAX_TSJ,
)
from modules.factory import FactoryModule
from modules.land import LandPriceModule
from modules.apartment import ApartmentPriceModule
from modules.house import HousePriceModule
from modules.commercial import CommercialPriceModule
from modules.cache import LookupCache
from modules.pdf import generate_pdf_response

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

# 모듈 초기화
wetax_module = WeTaxModule()
etax_module = SeoulETaxModule()
factory_module = FactoryModule()
land_module = LandPriceModule(api_key=Config.VWORLD_API_KEY)
apartment_module = ApartmentPriceModule(api_key=Config.DATA_GO_KR_API_KEY)
house_module = HousePriceModule(api_key=Config.DATA_GO_KR_API_KEY)
commercial_module = CommercialPriceModule()

lookup_cache = LookupCache()

MODULES = {
    "land": land_module,
    "apartment": apartment_module,
    "house": house_module,
    "building": None,  # 서울/비서울 자동 분기
    "commercial": commercial_module,
    "factory": factory_module,
}


def _resolve_address(form) -> dict:
    """폼 데이터에서 주소 정보를 구성한다."""
    # Juso.go.kr 자동완성으로 선택한 경우
    juso_data = form.get("juso_data", "")
    if juso_data:
        import json
        try:
            juso_item = json.loads(juso_data)
            addr = extract_address_components(juso_item)
            addr["_raw"] = juso_item.get("jibunAddr", "") or juso_item.get("roadAddr", "")
            addr["dong_no"] = form.get("dong_no", "")
            addr["ho_no"] = form.get("ho_no", "")
            return addr
        except (json.JSONDecodeError, KeyError):
            pass

    # 수동 입력 폴백
    addr_str = form.get("address", "").strip()
    addr = parse_address(addr_str)
    addr["_raw"] = addr_str
    return addr


def _get_module(property_type: str, address: dict):
    """부동산 유형과 주소에 따라 적절한 모듈을 반환한다."""
    if property_type == "building":
        sido = address.get("sido", "")
        if sido in ("서울", "서울특별시"):
            return etax_module
        return wetax_module
    return MODULES.get(property_type)


# ─── 메인 라우트 ───

@app.route("/")
def index():
    return render_template(
        "index.html",
        property_types=PROPERTY_TYPES,
        years=list(range(2026, 2010, -1)),
    )


@app.route("/search", methods=["POST"])
def search():
    property_type = request.form.get("property_type", "")
    year = request.form.get("year", "").strip()

    # year 검증: 빈 문자열(전체) 또는 2010~2030 사이 숫자
    if year and (not year.isdigit() or not (2010 <= int(year) <= 2030)):
        return render_template(
            "index.html", error="유효하지 않은 기준년도입니다.",
            property_types=PROPERTY_TYPES, years=list(range(2026, 2010, -1)),
        )

    if property_type not in PROPERTY_TYPES:
        return render_template(
            "index.html", error="부동산 유형을 선택해주세요.",
            property_types=PROPERTY_TYPES, years=list(range(2026, 2010, -1)),
        )

    address = _resolve_address(request.form)

    # building(서울) → ETAX 전용 파라미터 처리
    module = _get_module(property_type, address)
    if module is None:
        return render_template(
            "index.html", error="지원하지 않는 조회 유형입니다.",
            property_types=PROPERTY_TYPES, years=list(range(2026, 2010, -1)),
        )

    # 템플릿 매핑 (경로 조작 방지)
    TEMPLATE_MAP = {
        "land": "results/land.html",
        "apartment": "results/apartment.html",
        "house": "results/house.html",
        "building": "results/building.html",
        "commercial": "results/commercial.html",
        "factory": "results/factory.html",
    }
    template = TEMPLATE_MAP.get(property_type)
    if not template:
        return render_template(
            "index.html", error="지원하지 않는 조회 유형입니다.",
            property_types=PROPERTY_TYPES, years=list(range(2026, 2010, -1)),
        )

    # 캐시 확인
    cached = lookup_cache.get(property_type, address, year)
    if cached:
        cached.cached = True
        session["last_result"] = _result_to_dict(cached)
        return render_template(template, result=cached)

    # ETAX용 추가 파라미터
    kwargs = {}
    if isinstance(module, SeoulETaxModule):
        kwargs["sigu_code"] = request.form.get("sigu_cd", "")
        kwargs["hdong_code"] = request.form.get("hdong_cd", "")
        kwargs["tsj_gubun"] = request.form.get("tsj_gubun", "1")
        kwargs["dong_no"] = request.form.get("dong_no", "")
        kwargs["ho_no"] = request.form.get("ho_no", "")

    # 검색 실행
    result = module.search(address, year, **kwargs)

    # 캐시 저장 (성공 시)
    if result.success and result.results:
        lookup_cache.set(property_type, address, year, result)

    session["last_result"] = _result_to_dict(result)
    return render_template(template, result=result)


# ─── PDF 다운로드 ───

@app.route("/download/pdf", methods=["POST"])
def download_pdf():
    last = session.get("last_result")
    if not last:
        return "조회 결과가 없습니다.", 400
    result = _dict_to_result(last)
    return generate_pdf_response(result)


# ─── 주소 API ───

@app.route("/api/address/search")
def api_address_search():
    keyword = request.args.get("q", "").strip()
    if len(keyword) < 2:
        return jsonify({"items": []})
    # V-World API 우선, 실패 시 Juso.go.kr 폴백
    result = search_vworld(keyword, Config.VWORLD_API_KEY)
    if not result.get("items"):
        result = search_juso(keyword, Config.VWORLD_API_KEY)
    return jsonify(result)


# ─── ETAX 호환 라우트 (하위 호환) ───

@app.route("/etax")
def etax_index():
    get_dong_cache()
    return render_template(
        "etax.html",
        sigu_list=sorted(ETAX_SIGU.items()),
        tsj_list=ETAX_TSJ,
        years=list(range(2026, 2011, -1)),
    )


@app.route("/etax/dongs")
def etax_dongs():
    sigu_code = request.args.get("sigu", "")
    dong_cache = get_dong_cache()
    dongs = dong_cache.get(sigu_code, {})
    return jsonify(sorted(dongs.items(), key=lambda x: x[1]))


@app.route("/etax/search", methods=["POST"])
def etax_search_route():
    sigu_code = request.form.get("sigu_cd", "")
    hdong_code = request.form.get("hdong_cd", "")
    bonbun = request.form.get("bonbun", "").strip()
    bubun = request.form.get("bubun", "").strip()
    tsj = request.form.get("tsj_gubun", "1")
    year = request.form.get("gwapo_year", "")
    dong = request.form.get("dong", "").strip()
    hosu = request.form.get("hosu", "").strip()

    if not sigu_code or not hdong_code or not bonbun:
        return render_template(
            "etax.html",
            error="자치구, 법정동, 본번은 필수입니다.",
            sigu_list=sorted(ETAX_SIGU.items()),
            tsj_list=ETAX_TSJ,
            years=list(range(2026, 2011, -1)),
        )

    sigu_name = next((k for k, v in ETAX_SIGU.items() if v == sigu_code), sigu_code)
    address = {"bonji": bonbun, "bunji": bubun, "_raw": f"서울 {sigu_name} {bonbun}"}

    result = etax_module.search(
        address, year,
        sigu_code=sigu_code, hdong_code=hdong_code,
        tsj_gubun=tsj, dong_no=dong, ho_no=hosu,
    )

    query = {
        "sigu_name": sigu_name, "bonbun": bonbun, "bubun": bubun,
        "year": year or "전체", "dong": dong, "hosu": hosu,
    }
    return render_template("etax_result.html", results=result.results, query=query)


# ─── 유틸리티 ───

def _result_to_dict(result: LookupResult) -> dict:
    return {
        "success": result.success,
        "property_type": result.property_type,
        "property_type_label": result.property_type_label,
        "address": result.address,
        "year": result.year,
        "results": result.results,
        "source": result.source,
        "error": result.error,
        "message": result.message,
    }


def _dict_to_result(d: dict) -> LookupResult:
    return LookupResult(
        success=d.get("success", False),
        property_type=d.get("property_type", ""),
        property_type_label=d.get("property_type_label", ""),
        address=d.get("address", ""),
        year=d.get("year", ""),
        results=d.get("results", []),
        source=d.get("source", ""),
        error=d.get("error"),
        message=d.get("message"),
    )


if __name__ == "__main__":
    app.run(debug=Config.DEBUG, port=Config.PORT)
