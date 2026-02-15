"""주소 파싱 및 V-World / Juso.go.kr 주소 자동완성."""

import re
import requests


SIDO_MAP = {
    "서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천",
    "광주": "광주", "대전": "대전", "울산": "울산", "세종": "세종",
    "경기": "경기", "강원": "강원", "충북": "충북", "충남": "충남",
    "전북": "전북", "전남": "전남", "경북": "경북", "경남": "경남",
    "제주": "제주",
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구",
    "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
    "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기",
    "강원도": "강원", "강원특별자치도": "강원",
    "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남",
    "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주",
}

VWORLD_SEARCH_URL = "https://api.vworld.kr/req/search"
JUSO_API_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"


def parse_address(addr_str: str) -> dict:
    """자유형식 한국어 주소를 구조화된 딕셔너리로 파싱한다."""
    result = {
        "sido": "", "sigungu": "", "dong": "",
        "bonji": "", "bunji": "", "bldg_name": "",
        "dong_no": "", "ho_no": "", "san": False,
    }
    tokens = addr_str.strip().split()
    remaining = []

    for token in tokens:
        if not result["sido"] and token in SIDO_MAP:
            result["sido"] = SIDO_MAP[token]
            continue
        if not result["sigungu"] and re.match(r".+[시군구]$", token):
            result["sigungu"] = re.sub(r"[시군구]$", "", token)
            continue
        if not result["dong"] and re.match(r".+[읍면동가리]$", token):
            result["dong"] = re.sub(r"[읍면동가리]\d*$", "", token)
            result["dong"] = re.sub(r"\d+$", "", result["dong"])
            continue
        if token == "산":
            result["san"] = True
            continue
        if not result["bonji"] and re.match(r"^\d+(-\d+)?$", token):
            parts = token.split("-")
            result["bonji"] = parts[0]
            if len(parts) > 1:
                result["bunji"] = parts[1]
            continue
        m = re.match(r"^([A-Za-z\d]+)동$", token)
        if m:
            result["dong_no"] = m.group(1)
            continue
        m = re.match(r"^(\d+)호$", token)
        if m:
            result["ho_no"] = m.group(1)
            continue
        remaining.append(token)

    if remaining:
        result["bldg_name"] = " ".join(remaining)
    return result


def search_vworld(keyword: str, api_key: str, page: int = 1, count: int = 10) -> dict:
    """V-World 검색 API로 주소를 검색한다."""
    if not api_key or len(keyword.strip()) < 2:
        return {"total": 0, "items": []}

    params = {
        "service": "search",
        "request": "search",
        "version": "2.0",
        "query": keyword,
        "type": "address",
        "category": "parcel",
        "format": "json",
        "size": count,
        "page": page,
        "key": api_key,
    }
    try:
        resp = requests.get(VWORLD_SEARCH_URL, params=params, timeout=10)
        data = resp.json()
        response = data.get("response", {})

        if response.get("status") != "OK":
            # parcel 결과 없으면 road로 재시도
            params["category"] = "road"
            resp = requests.get(VWORLD_SEARCH_URL, params=params, timeout=10)
            data = resp.json()
            response = data.get("response", {})

        if response.get("status") != "OK":
            return {"total": 0, "items": []}

        record = response.get("record", {})
        result_data = response.get("result", {})
        items = result_data.get("items", [])

        # V-World 결과를 Juso.go.kr 호환 형식으로 변환
        converted = []
        for item in items:
            addr = item.get("address", {})
            title = item.get("title", "")
            converted.append({
                "roadAddr": addr.get("road", title),
                "jibunAddr": addr.get("parcel", title),
                "bdMgtSn": item.get("id", ""),
                "admCd": "",
                "lnbrMnnm": "",
                "lnbrSlno": "",
            })

        return {
            "total": int(record.get("total", 0)),
            "items": converted,
        }
    except Exception as e:
        return {"total": 0, "items": [], "error": str(e)}


def search_juso(keyword: str, api_key: str, page: int = 1, count: int = 10) -> dict:
    """Juso.go.kr API로 주소를 검색한다."""
    if not api_key or len(keyword.strip()) < 2:
        return {"total": 0, "items": []}

    params = {
        "confmKey": api_key,
        "currentPage": page,
        "countPerPage": count,
        "keyword": keyword,
        "resultType": "json",
    }
    resp = requests.get(JUSO_API_URL, params=params, timeout=10)
    data = resp.json()
    results = data.get("results", {})
    common = results.get("common", {})

    if common.get("errorCode") != "0":
        return {"total": 0, "items": [], "error": common.get("errorMessage", "")}

    return {
        "total": int(common.get("totalCount", 0)),
        "items": results.get("juso", []),
    }


def extract_pnu(bd_mgt_sn: str) -> str:
    """건물관리번호에서 PNU(필지고유번호 19자리)를 추출한다."""
    if bd_mgt_sn and len(bd_mgt_sn) >= 19:
        return bd_mgt_sn[:19]
    return ""


def extract_address_components(juso_item: dict) -> dict:
    """Juso.go.kr 또는 V-World API 결과에서 주소 컴포넌트를 추출한다."""
    bd_mgt_sn = juso_item.get("bdMgtSn", "")
    adm_cd = juso_item.get("admCd", "")

    sido = juso_item.get("siNm", "")
    sigungu = juso_item.get("sggNm", "")
    dong = juso_item.get("emdNm", "")

    # siNm/sggNm/emdNm이 없으면 jibunAddr에서 파싱 시도
    if not sido:
        jibun = juso_item.get("jibunAddr", "")
        if jibun:
            parsed = parse_address(jibun)
            sido = sido or parsed.get("sido", "")
            sigungu = sigungu or parsed.get("sigungu", "")
            dong = dong or parsed.get("dong", "")

    return {
        "road_addr": juso_item.get("roadAddr", ""),
        "jibun_addr": juso_item.get("jibunAddr", ""),
        "sido": sido,
        "sigungu": sigungu,
        "dong": dong,
        "bonji": juso_item.get("lnbrMnnm", ""),
        "bunji": juso_item.get("lnbrSlno", ""),
        "bldg_name": juso_item.get("bdNm", ""),
        "pnu": extract_pnu(bd_mgt_sn),
        "adm_cd": adm_cd,
        "bd_mgt_sn": bd_mgt_sn,
        "zip_no": juso_item.get("zipNo", ""),
    }
