"""
시가표준액/공시가격 종합 조회 포털
Flask + 모듈별 조회 (WeTax/ETAX/data.go.kr/HomeTax)
"""

from flask import Flask, render_template, request, jsonify, session, send_file

from config import Config
from modules.base import PROPERTY_TYPES, LookupResult, SOURCE_INFO
from modules.address import (
    parse_address, search_juso, search_vworld, extract_address_components,
    SIDO_MAP, normalize_dong_ho, filter_apartment_by_dong_ho,
)
from modules.building_nonseoul import WeTaxModule
from modules.building_seoul import (
    SeoulETaxModule, get_dong_cache, ETAX_SIGU, ETAX_TSJ,
)
from modules.factory import FactoryModule
from modules.land import LandPriceModule
from modules.apartment import ApartmentPriceModule
from modules.house import HousePriceModule
from modules.cache import LookupCache
from modules.pdf import generate_pdf_response
from modules.batch import (
    get_job, cancel_job, generate_sample_template, MAX_FILE_SIZE,
    preview_excel, store_upload, get_upload,
    parse_addresses_from_excel, generate_cleaned_excel,
    start_batch_job_from_parsed, _save_parsed,
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

lookup_cache = LookupCache()

# 서버 측 PDF 데이터 캐시 (파일 기반, 멀티 워커 호환)
import uuid as _uuid
import json as _json
import tempfile as _tempfile
import os as _os

_PDF_CACHE_DIR = _os.path.join(_tempfile.gettempdir(), "siga_pdf_cache")
_os.makedirs(_PDF_CACHE_DIR, exist_ok=True)


def _store_pdf_data(data: dict) -> str:
    """PDF용 데이터를 파일에 저장하고 키를 반환한다."""
    key = _uuid.uuid4().hex[:12]
    path = _os.path.join(_PDF_CACHE_DIR, f"{key}.json")
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False)
    # 오래된 파일 정리 (50개 초과 시)
    files = sorted(
        (_os.path.join(_PDF_CACHE_DIR, f) for f in _os.listdir(_PDF_CACHE_DIR) if f.endswith(".json")),
        key=lambda p: _os.path.getmtime(p),
    )
    for old in files[:-50]:
        try:
            _os.remove(old)
        except OSError:
            pass
    return key


def _store_evidence(evidence_bytes: bytes, evidence_type: str) -> str:
    """증거 파일(PDF/PNG)을 저장하고 키를 반환한다."""
    key = _uuid.uuid4().hex[:12]
    ext = evidence_type or "bin"
    path = _os.path.join(_PDF_CACHE_DIR, f"{key}_evidence.{ext}")
    with open(path, "wb") as f:
        f.write(evidence_bytes)
    return key


def _load_evidence(key: str, evidence_type: str) -> bytes | None:
    """저장된 증거 파일을 로드한다."""
    if not key:
        return None
    ext = evidence_type or "bin"
    path = _os.path.join(_PDF_CACHE_DIR, f"{key}_evidence.{ext}")
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _load_pdf_data(key: str) -> dict | None:
    """파일에서 PDF 데이터를 로드한다."""
    if not key:
        return None
    path = _os.path.join(_PDF_CACHE_DIR, f"{key}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        return None


MODULES = {
    "land": land_module,
    "apartment": apartment_module,
    "house": house_module,
    "building": None,  # 서울/비서울 자동 분기
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


def _resolve_pnu(addr: dict, address_str: str) -> dict:
    """PNU가 없으면 V-World / Juso 주소 검색으로 자동 보정한다.

    parse_address()만으로는 PNU를 얻을 수 없기 때문에,
    주소 검색 API → extract_address_components() → PNU 추출 과정을 거친다.
    """
    if addr.get("pnu"):
        return addr

    # V-World 주소 검색 시도
    api_key = Config.VWORLD_API_KEY
    if api_key:
        result = search_vworld(address_str, api_key, count=3)
        items = result.get("items", [])
        if items:
            # 첫 번째 결과에서 PNU 추출
            comp = extract_address_components(items[0])
            if comp.get("pnu"):
                app.logger.info("[PNU-RESOLVE] V-World resolved PNU=%s for '%s'",
                                comp["pnu"], address_str)
                # parse_address 결과에 PNU 관련 필드 병합
                for key in ("pnu", "adm_cd", "bd_mgt_sn", "road_addr", "jibun_addr"):
                    if comp.get(key):
                        addr[key] = comp[key]
                # sido/sigungu/dong/bonji 보완 (비어 있을 때만)
                for key in ("sido", "sigungu", "dong", "bonji", "bunji"):
                    if not addr.get(key) and comp.get(key):
                        addr[key] = comp[key]
                return addr

    # V-World 실패 시 Juso.go.kr 폴백
    juso_key = Config.JUSO_API_KEY
    if juso_key:
        result = search_juso(address_str, juso_key, count=3)
        items = result.get("items", [])
        if items:
            comp = extract_address_components(items[0])
            if comp.get("pnu"):
                app.logger.info("[PNU-RESOLVE] Juso resolved PNU=%s for '%s'",
                                comp["pnu"], address_str)
                for key in ("pnu", "adm_cd", "bd_mgt_sn", "road_addr", "jibun_addr"):
                    if comp.get(key):
                        addr[key] = comp[key]
                for key in ("sido", "sigungu", "dong", "bonji", "bunji"):
                    if not addr.get(key) and comp.get(key):
                        addr[key] = comp[key]
                return addr

    app.logger.warning("[PNU-RESOLVE] Failed to resolve PNU for '%s'", address_str)
    return addr


def perform_search(address_str: str, property_type: str = "", year: str = "",
                   dong_no: str = "", ho_no: str = "") -> dict:
    """Core search logic for JSON API.

    Returns a plain dict suitable for JSON serialization.
    """
    addr = parse_address(address_str)
    addr["_raw"] = address_str

    # 주소 문자열에서 파싱된 동/호를 기본값으로 사용 (API 파라미터가 우선)
    if not dong_no:
        dong_no = addr.get("dong_no", "")
    if not ho_no:
        ho_no = addr.get("ho_no", "")

    # PNU 자동 보정: parse_address만으로는 PNU가 없으므로 주소 검색 API로 보완
    addr = _resolve_pnu(addr, address_str)

    # Auto mode (유형 미선택)
    if property_type not in PROPERTY_TYPES:
        auto_results = {}

        is_collective = bool(dong_no or ho_no)
        is_officetel = addr.get("building_type_hint") == "오피스텔"

        for type_key, mod, label in [
            ("land", land_module, "토지 개별공시지가"),
            ("apartment", apartment_module, "공동주택 공시가격"),
            ("house", house_module, "개별주택 공시가격"),
        ]:
            if type_key == "land" and is_collective:
                continue
            if type_key == "apartment" and is_officetel:
                continue
            try:
                result = mod.search(addr, year)
                if result.success and result.results:
                    items = result.results
                    if type_key == "apartment" and (dong_no or ho_no):
                        items = filter_apartment_by_dong_ho(items, dong_no, ho_no)
                    if items:
                        auto_results[type_key] = {
                            "label": label,
                            "results": items,
                            "source": result.source,
                            "property_type": result.property_type,
                        }
            except Exception as exc:
                app.logger.error("[API-AUTO] %s exception: %s", type_key, exc)

        # 주택외건물: 서울(ETAX) / 비서울(WeTax)
        sido = addr.get("sido", "")
        if sido in ("서울", "서울특별시"):
            try:
                kw = {"dong_no": dong_no, "ho_no": ho_no}
                result = etax_module.search(addr, year, **kw)
                if result.success and result.results:
                    auto_results["building"] = {
                        "label": "주택외건물 시가표준액 (서울)",
                        "results": result.results,
                        "source": result.source,
                        "property_type": result.property_type,
                    }
            except Exception:
                pass
        else:
            try:
                result = wetax_module.search(addr, year)
                if result.success and result.results:
                    # WeTax는 폼에서 이미 동/호 필터링됨 → 추가 필터 불필요
                    auto_results["building"] = {
                        "label": "주택외건물 시가표준액 (WeTax)",
                        "results": result.results,
                        "source": result.source,
                        "property_type": result.property_type,
                    }
            except Exception as exc:
                app.logger.error("[API-AUTO] wetax exception: %s", exc)

        all_results = []
        for type_key, info in auto_results.items():
            for item in info["results"]:
                item["_property_type"] = type_key
                item["_property_label"] = info["label"]
                item["_source"] = info.get("source", "")
                all_results.append(item)

        return {
            "success": len(all_results) > 0,
            "property_type": "auto",
            "address": address_str,
            "year": year,
            "results": all_results,
            "error": None if all_results else "조회 결과가 없습니다.",
        }

    # Specific type
    mod = _get_module(property_type, addr)
    if mod is None:
        return {
            "success": False,
            "property_type": property_type,
            "address": address_str,
            "year": year,
            "results": [],
            "error": "지원하지 않는 조회 유형입니다.",
        }

    kw = {}
    if isinstance(mod, SeoulETaxModule):
        kw["dong_no"] = dong_no
        kw["ho_no"] = ho_no

    result = mod.search(addr, year, **kw)

    if property_type == "apartment" and result.success and result.results:
        if dong_no or ho_no:
            result.results = filter_apartment_by_dong_ho(
                result.results, dong_no, ho_no)

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

    # 유형 미선택 → 자동 통합 조회 (토지/공동주택/개별주택 + 건물)
    if property_type not in PROPERTY_TYPES:
        address = _resolve_address(request.form)
        address = _resolve_pnu(address, address.get("_raw", ""))
        dong_no = request.form.get("dong_no", "").strip()
        ho_no = request.form.get("ho_no", "").strip()
        # address dict에서도 dong/ho 추출 (주소에서 파싱된 경우 보완)
        if not dong_no:
            dong_no = address.get("dong_no", "").strip()
        if not ho_no:
            ho_no = address.get("ho_no", "").strip()
        app.logger.info(
            "[AUTO] addr=%s pnu=%s dong_no=%r ho_no=%r year=%s",
            address.get("_raw", ""), address.get("pnu", ""), dong_no, ho_no, year,
        )
        auto_results = {}

        # 집합건물 판정: 동/호가 있으면 개별 토지 조회 생략
        is_collective = bool(dong_no or ho_no)
        # 오피스텔: 공동주택이 아니므로 공동주택 공시가격 조회 생략
        is_officetel = address.get("building_type_hint") == "오피스텔"

        for type_key, module, label in [
            ("land", land_module, "토지 개별공시지가"),
            ("apartment", apartment_module, "공동주택 공시가격"),
            ("house", house_module, "개별주택 공시가격"),
        ]:
            if type_key == "land" and is_collective:
                continue
            if type_key == "apartment" and is_officetel:
                continue
            try:
                result = module.search(address, year)
                app.logger.info(
                    "[AUTO] %s: success=%s count=%d err=%s",
                    type_key, result.success, len(result.results), result.error,
                )
                if result.success and result.results:
                    # 공동주택: 동/호 필터링 (단계적 — 동 → 호)
                    if type_key == "apartment" and (dong_no or ho_no):
                        result.results = filter_apartment_by_dong_ho(
                            result.results, dong_no, ho_no)
                        app.logger.info(
                            "[AUTO] apartment filter: dong=%r ho=%r -> %d results",
                            dong_no, ho_no, len(result.results),
                        )
                    # 필터 후 결과가 있을 때만 추가
                    if result.results:
                        auto_results[type_key] = {
                            "label": label,
                            "result": result,
                        }
            except Exception as exc:
                app.logger.error("[AUTO] %s exception: %s", type_key, exc)

        # 주택외건물 조회: 서울(ETAX) / 비서울(WeTax) 모두 시도
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
        else:
            # 비서울: WeTax로 주택외건물 조회 (폼에서 이미 동/호 필터됨)
            try:
                result = wetax_module.search(address, year)
                if result.success and result.results:
                    auto_results["building"] = {
                        "label": "주택외건물 시가표준액 (WeTax)",
                        "result": result,
                        "source_key": "building_wetax",
                    }
            except Exception as exc:
                app.logger.error("[AUTO] wetax exception: %s", exc)

        # 공동주택 결과가 많고 동/호 미입력 시 안내 플래그
        show_dong_ho_guide = False
        if "apartment" in auto_results and not (dong_no or ho_no):
            if len(auto_results["apartment"]["result"].results) > 10:
                show_dong_ho_guide = True

        # 서버 측 캐시에 auto 결과 저장 (PDF용, 세션 쿠키 크기 제한 우회)
        auto_data = {
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
        session["last_auto_key"] = _store_pdf_data(auto_data)

        # 건물 조회 증거 저장 (ETAX PDF / WeTax PNG)
        if "building" in auto_results:
            bldg_result = auto_results["building"]["result"]
            if bldg_result.evidence:
                ekey = _store_evidence(bldg_result.evidence, bldg_result.evidence_type)
                session["last_evidence_key"] = ekey
                session["last_evidence_type"] = bldg_result.evidence_type

        return render_template(
            "results/auto.html",
            auto_results=auto_results,
            address=address.get("_raw", ""),
            year=year,
            source_info=SOURCE_INFO,
            show_dong_ho_guide=show_dong_ho_guide,
            apartment_count=len(auto_results["apartment"]["result"].results) if "apartment" in auto_results else 0,
            has_evidence="building" in auto_results and auto_results["building"]["result"].evidence is not None,
        )

    address = _resolve_address(request.form)
    address = _resolve_pnu(address, address.get("_raw", ""))

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
        session["last_result_key"] = _store_pdf_data(_result_to_dict(cached))
        return render_template(template, result=cached, source_info=src_info,
                               has_evidence=False)

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

    # 공동주택: 동/호 필터링 (단계적 — 동 → 호)
    if property_type == "apartment" and result.success and result.results:
        dong_no = request.form.get("dong_no", "").strip()
        ho_no = request.form.get("ho_no", "").strip()
        if not dong_no:
            dong_no = address.get("dong_no", "").strip()
        if not ho_no:
            ho_no = address.get("ho_no", "").strip()
        app.logger.info(
            "[DIRECT APT] dong_no=%r ho_no=%r total=%d",
            dong_no, ho_no, len(result.results),
        )
        if dong_no or ho_no:
            result.results = filter_apartment_by_dong_ho(
                result.results, dong_no, ho_no)

    # 캐시 저장 (성공 시)
    if result.success and result.results:
        lookup_cache.set(property_type, address, year, result)

    session["last_result_key"] = _store_pdf_data(_result_to_dict(result))

    # 건물 조회 증거 저장
    has_evidence = False
    if property_type == "building" and result.evidence:
        ekey = _store_evidence(result.evidence, result.evidence_type)
        session["last_evidence_key"] = ekey
        session["last_evidence_type"] = result.evidence_type
        has_evidence = True

    return render_template(template, result=result, source_info=src_info,
                           has_evidence=has_evidence)


# ─── PDF 다운로드 ───

@app.route("/download/pdf", methods=["POST"])
def download_pdf():
    key = session.get("last_result_key")
    last = _load_pdf_data(key)
    if not last:
        return "조회 결과가 없습니다.", 400
    result = _dict_to_result(last)
    custom_filename = request.form.get("filename", "").strip() or None
    return generate_pdf_response(result, filename=custom_filename)


@app.route("/download/auto-pdf", methods=["POST"])
def download_auto_pdf():
    from modules.pdf import generate_auto_pdf_response
    key = session.get("last_auto_key")
    last_auto = _load_pdf_data(key)
    if not last_auto:
        return "조회 결과가 없습니다.", 400
    custom_filename = request.form.get("filename", "").strip() or None
    return generate_auto_pdf_response(last_auto, filename=custom_filename)


@app.route("/download/evidence", methods=["POST"])
def download_evidence():
    """조회 출처 증거 파일(ETAX 원본 PDF / WeTax 스크린샷)을 다운로드한다."""
    import io as _io
    from datetime import datetime as _dt
    ekey = session.get("last_evidence_key")
    etype = session.get("last_evidence_type", "")
    if not ekey:
        return "증거 파일이 없습니다.", 404
    data = _load_evidence(ekey, etype)
    if not data:
        return "증거 파일을 찾을 수 없습니다.", 404

    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    if etype == "pdf":
        return send_file(
            _io.BytesIO(data),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"ETAX_원본_{ts}.pdf",
        )
    else:
        return send_file(
            _io.BytesIO(data),
            mimetype="image/png",
            as_attachment=True,
            download_name=f"WeTax_스크린샷_{ts}.png",
        )


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


# ─── JSON 시가조회 API (WillSave 연동용) ───

@app.route("/api/search", methods=["POST"])
def api_search():
    """JSON API for property price lookup (for WillSave integration)."""
    data = request.get_json(silent=True) or request.form
    address = (data.get("address") or "").strip()
    if not address:
        return jsonify({"success": False, "error": "주소를 입력해주세요.", "results": []}), 400

    property_type = (data.get("property_type") or "").strip()
    year = (data.get("year") or "").strip()
    dong_no = (data.get("dong_no") or "").strip()
    ho_no = (data.get("ho_no") or "").strip()

    # year 검증
    if year and (not year.isdigit() or not (2010 <= int(year) <= 2030)):
        return jsonify({"success": False, "error": "유효하지 않은 기준년도입니다.", "results": []}), 400

    try:
        result = perform_search(address, property_type, year, dong_no, ho_no)
        return jsonify(result)
    except Exception as exc:
        app.logger.error("[API] search error: %s", exc)
        return jsonify({"success": False, "error": f"조회 중 오류가 발생했습니다: {exc}", "results": []}), 500


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
    """Step 1: 파일만 받아서 헤더 + 미리보기를 반환한다."""
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "파일을 선택해주세요."}), 400

    if not file.filename.lower().endswith((".xlsx", ".xls")):
        return jsonify({"error": "xlsx 파일만 지원합니다."}), 400

    file_bytes = file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return jsonify({"error": f"파일 크기가 {MAX_FILE_SIZE // (1024*1024)}MB를 초과합니다."}), 400

    try:
        info = preview_excel(file_bytes)
        import uuid as _uid
        upload_id = _uid.uuid4().hex[:12]
        store_upload(
            upload_id=upload_id,
            file_bytes=file_bytes,
            headers=info["headers"],
            row_count=info["row_count"],
            preview=info["preview"],
        )
        return jsonify({
            "upload_id": upload_id,
            "headers": info["headers"],
            "row_count": info["row_count"],
            "preview": info["preview"],
        })
    except Exception as e:
        return jsonify({"error": f"파일 읽기 오류: {e}"}), 400


@app.route("/batch/parse", methods=["POST"])
def batch_parse():
    """Step 2: 컬럼 선택 → 주소 파싱·분리 결과 반환."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "요청 데이터가 없습니다."}), 400

    upload_id = data.get("upload_id", "")
    cache = get_upload(upload_id)
    if not cache:
        return jsonify({"error": "업로드 세션이 만료되었습니다. 파일을 다시 업로드해주세요."}), 404

    address_col = data.get("address_col")
    if address_col is None:
        return jsonify({"error": "주소 컬럼을 선택해주세요."}), 400
    address_col = int(address_col)

    year_col = data.get("year_col")
    if year_col is not None and year_col != "":
        year_col = int(year_col)
    else:
        year_col = None

    share_col = data.get("share_col")
    if share_col is not None and share_col != "":
        share_col = int(share_col)
    else:
        share_col = None

    owner_col = data.get("owner_col")
    if owner_col is not None and owner_col != "":
        owner_col = int(owner_col)
    else:
        owner_col = None

    default_year = data.get("default_year", "")

    try:
        parsed = parse_addresses_from_excel(
            cache.file_bytes, address_col, year_col, default_year,
            share_col=share_col, owner_col=owner_col,
        )
        cache.parsed_addresses = parsed
        cache.default_year = default_year
        _save_parsed(upload_id, parsed, default_year)

        split_count = sum(1 for a in parsed if a.get("split_from"))
        original_count = len(set(a["original_row"] for a in parsed))

        return jsonify({
            "upload_id": upload_id,
            "total": len(parsed),
            "original_rows": original_count,
            "split_count": split_count,
            "addresses": parsed,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"파싱 오류: {e}"}), 500


@app.route("/batch/start", methods=["POST"])
def batch_start():
    """Step 3: 캐시된 파싱 결과로 배치 작업을 시작한다."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "요청 데이터가 없습니다."}), 400

    upload_id = data.get("upload_id", "")
    cache = get_upload(upload_id)
    if not cache or not cache.parsed_addresses:
        return jsonify({"error": "파싱 결과가 없습니다. 다시 진행해주세요."}), 404

    pdf_name_pattern = data.get("pdf_name_pattern", "{번호}_{소유자}_{주소}")

    try:
        job_id = start_batch_job_from_parsed(
            parsed_addresses=cache.parsed_addresses,
            default_year=cache.default_year,
            vworld_api_key=Config.VWORLD_API_KEY,
            land_module=land_module,
            apartment_module=apartment_module,
            house_module=house_module,
            building_seoul_module=etax_module,
            flask_app=app,
            pdf_name_pattern=pdf_name_pattern,
        )
        return jsonify({"job_id": job_id})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"처리 오류: {e}"}), 500


@app.route("/batch/cancel/<job_id>", methods=["POST"])
def batch_cancel(job_id):
    """배치 작업을 취소한다."""
    if cancel_job(job_id):
        return jsonify({"ok": True})
    return jsonify({"error": "작업을 찾을 수 없습니다."}), 404


@app.route("/batch/download-cleaned/<upload_id>")
def batch_download_cleaned(upload_id):
    """정리된 주소 엑셀을 다운로드한다."""
    import io as _io
    cache = get_upload(upload_id)
    if not cache or not cache.parsed_addresses:
        return "파싱 결과가 없습니다.", 404

    cleaned_bytes = generate_cleaned_excel(cache.parsed_addresses)
    return send_file(
        _io.BytesIO(cleaned_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"정리된주소_{upload_id}.xlsx",
    )


@app.route("/batch/status/<job_id>")
def batch_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "작업을 찾을 수 없습니다."}), 404
    resp = {
        "status": job.status,
        "total": job.total,
        "processed": job.processed,
        "current_address": job.current_address,
        "error": job.error,
    }
    # cancelled 상태에서도 다운로드 가능하도록
    if job.status == "cancelled" and job.output_bytes:
        resp["has_output"] = True
    return jsonify(resp)


@app.route("/batch/download/<job_id>")
def batch_download(job_id):
    import io as _io
    job = get_job(job_id)
    if not job or job.status not in ("completed", "cancelled") or not job.output_bytes:
        return "결과를 찾을 수 없습니다.", 404

    return send_file(
        _io.BytesIO(job.output_bytes),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"일괄조회결과_{job_id}.zip",
    )


@app.route("/batch/download-excel/<job_id>")
def batch_download_excel(job_id):
    """요약 엑셀만 별도 다운로드한다."""
    import io as _io
    import os
    from modules.batch import _JOBS_DIR
    xlsx_path = os.path.join(_JOBS_DIR, job_id, "output.xlsx")
    if not os.path.isfile(xlsx_path):
        return "엑셀 파일을 찾을 수 없습니다.", 404

    with open(xlsx_path, "rb") as f:
        xlsx_bytes = f.read()
    return send_file(
        _io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"조회결과_{job_id}.xlsx",
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
