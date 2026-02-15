"""
시가표준액/공시가격 종합 조회 포털
Flask + 모듈별 조회 (WeTax/ETAX/data.go.kr/HomeTax)
"""

from flask import Flask, render_template, request, jsonify, session, send_file

from config import Config
from modules.base import PROPERTY_TYPES, LookupResult, SOURCE_INFO
from modules.address import parse_address, search_juso, search_vworld, extract_address_components, SIDO_MAP
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
from modules.batch import (
    start_batch_job, get_job, parse_excel,
    generate_sample_template, MAX_FILE_SIZE,
)

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

# 모듈 초기화
wetax_module = WeTaxModule()
etax_module = SeoulETaxModule()
factory_module = FactoryModule()
land_module = LandPriceModule(api_key=Config.VWORLD_API_KEY)
apartment_module = ApartmentPriceModule(api_key=Config.VWORLD_API_KEY)
house_module = HousePriceModule(api_key=Config.VWORLD_API_KEY)
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
            # 전체 주소 표시: jibunAddr에 시도가 포함된 경우 우선, 아니면 roadAddr 사용
            jibun = juso_item.get("jibunAddr", "")
            road = juso_item.get("roadAddr", "")
            if jibun and any(jibun.startswith(s) for s in SIDO_MAP):
                addr["_raw"] = jibun
            elif road:
                addr["_raw"] = road
            else:
                addr["_raw"] = jibun
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

    # 유형 미선택 → 자동 통합 조회 (토지/공동주택/개별주택 + 서울 건물)
    if property_type not in PROPERTY_TYPES:
        address = _resolve_address(request.form)
        dong_no = request.form.get("dong_no", "").strip()
        ho_no = request.form.get("ho_no", "").strip()
        auto_results = {}

        for type_key, module, label in [
            ("land", land_module, "토지 개별공시지가"),
            ("apartment", apartment_module, "공동주택 공시가격"),
            ("house", house_module, "개별주택 공시가격"),
        ]:
            try:
                result = module.search(address, year)
                if result.success and result.results:
                    # 공동주택: 동/호 필터링 (정확 일치)
                    if type_key == "apartment" and (dong_no or ho_no):
                        filtered = result.results
                        if dong_no:
                            filtered = [r for r in filtered if str(r.get("dong", "")).strip() == dong_no]
                        if ho_no:
                            filtered = [r for r in filtered if str(r.get("ho", "")).strip() == ho_no]
                        result.results = filtered
                        if not filtered:
                            continue
                    auto_results[type_key] = {
                        "label": label,
                        "result": result,
                    }
            except Exception:
                pass

        # 서울 주소이면 ETAX 주택외건물도 조회
        sido = address.get("sido", "")
        if sido in ("서울", "서울특별시"):
            try:
                kwargs = {"dong_no": dong_no, "ho_no": ho_no}
                result = etax_module.search(address, year, **kwargs)
                if result.success and result.results:
                    auto_results["building"] = {
                        "label": "주택외건물 시가표준액 (서울)",
                        "result": result,
                        "source_key": "building_etax",
                    }
            except Exception:
                pass

        # session에 auto 결과 저장 (PDF용)
        session["last_auto"] = {
            "address": address.get("_raw", ""),
            "year": year,
            "sections": {
                k: {
                    "label": v["label"],
                    "result": _result_to_dict(v["result"]),
                    "source_key": v.get("source_key", k),
                }
                for k, v in auto_results.items()
            },
        }

        return render_template(
            "results/auto.html",
            auto_results=auto_results,
            address=address.get("_raw", ""),
            year=year,
            source_info=SOURCE_INFO,
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

    # 출처 정보 (building은 서울/비서울 구분)
    if property_type == "building":
        src_info = SOURCE_INFO.get(
            "building_etax" if isinstance(module, SeoulETaxModule) else "building_wetax", {}
        )
    else:
        src_info = SOURCE_INFO.get(property_type, {})
    cached = lookup_cache.get(property_type, address, year)
    if cached:
        cached.cached = True
        session["last_result"] = _result_to_dict(cached)
        return render_template(template, result=cached, source_info=src_info)

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
    return render_template(template, result=result, source_info=src_info)


# ─── PDF 다운로드 ───

@app.route("/download/pdf", methods=["POST"])
def download_pdf():
    last = session.get("last_result")
    if not last:
        return "조회 결과가 없습니다.", 400
    result = _dict_to_result(last)
    return generate_pdf_response(result)


@app.route("/download/auto-pdf", methods=["POST"])
def download_auto_pdf():
    from modules.pdf import generate_auto_pdf_response
    last_auto = session.get("last_auto")
    if not last_auto:
        return "조회 결과가 없습니다.", 400
    return generate_auto_pdf_response(last_auto)


# ─── 주소 API ───

@app.route("/api/address/search")
def api_address_search():
    keyword = request.args.get("q", "").strip()
    if len(keyword) < 2:
        return jsonify({"items": []})
    # V-World API 우선, 실패 시 Juso.go.kr 폴백
    result = search_vworld(keyword, Config.VWORLD_API_KEY)
    if not result.get("items") and Config.JUSO_API_KEY:
        result = search_juso(keyword, Config.JUSO_API_KEY)
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


# ─── 배치 (엑셀 일괄 조회) ───

@app.route("/batch")
def batch_index():
    return render_template(
        "batch.html",
        years=list(range(2026, 2010, -1)),
    )


@app.route("/batch/upload", methods=["POST"])
def batch_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "파일을 선택해주세요."}), 400

    if not file.filename.lower().endswith((".xlsx", ".xls")):
        return jsonify({"error": "xlsx 파일만 지원합니다."}), 400

    file_bytes = file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return jsonify({"error": f"파일 크기가 {MAX_FILE_SIZE // (1024*1024)}MB를 초과합니다."}), 400

    default_year = request.form.get("year", "").strip()

    try:
        job_id = start_batch_job(
            file_bytes=file_bytes,
            default_year=default_year,
            vworld_api_key=Config.VWORLD_API_KEY,
            land_module=land_module,
            apartment_module=apartment_module,
            house_module=house_module,
        )
        return jsonify({"job_id": job_id})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"처리 오류: {e}"}), 500


@app.route("/batch/status/<job_id>")
def batch_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "작업을 찾을 수 없습니다."}), 404
    return jsonify({
        "status": job.status,
        "total": job.total,
        "processed": job.processed,
        "current_address": job.current_address,
        "error": job.error,
    })


@app.route("/batch/download/<job_id>")
def batch_download(job_id):
    import io
    job = get_job(job_id)
    if not job or job.status != "completed" or not job.output_bytes:
        return "결과를 찾을 수 없습니다.", 404

    return send_file(
        io.BytesIO(job.output_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"일괄조회결과_{job_id}.xlsx",
    )


@app.route("/batch/template")
def batch_template():
    import io
    template_bytes = generate_sample_template()
    return send_file(
        io.BytesIO(template_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="일괄조회_양식.xlsx",
    )


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
