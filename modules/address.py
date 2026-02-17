"""주소 파싱 및 V-World / Juso.go.kr 주소 자동완성."""

import re
import requests

_HTML_TAG_RE = re.compile(r"<[^>]+>")

# 한글 → 영문 알파벳 매핑 (공동주택 동명 변환용)
_KOREAN_TO_ALPHA = {
    '에이': 'A', '비': 'B', '씨': 'C', '디': 'D',
    '이': 'E', '에프': 'F', '지': 'G', '에이치': 'H',
    '아이': 'I', '제이': 'J', '케이': 'K', '엘': 'L',
    '엠': 'M', '엔': 'N', '오': 'O', '피': 'P',
    '큐': 'Q', '알': 'R', '아르': 'R', '에스': 'S',
    '티': 'T', '유': 'U', '브이': 'V', '더블유': 'W',
    '엑스': 'X', '와이': 'Y', '제트': 'Z',
}


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
        "sido": "", "sigungu": "", "sigungu_sub": "", "dong": "",
        "bonji": "", "bunji": "", "bldg_name": "",
        "dong_no": "", "ho_no": "", "floor": "", "san": False,
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
        # 하위 구 (고양시 → 일산동구, 수원시 → 팔달구 등)
        if result["sigungu"] and not result["sigungu_sub"] and not result["dong"] \
                and re.match(r".+구$", token):
            result["sigungu_sub"] = token
            continue
        if not result["dong"] and re.match(r".+[읍면동가리]$", token):
            result["dong"] = re.sub(r"[읍면동가리]\d*$", "", token)
            result["dong"] = re.sub(r"\d+$", "", result["dong"])
            continue
        if token == "산":
            result["san"] = True
            continue
        # 번지 with suffix (64번지, 494-15번지)
        if not result["bonji"] and re.match(r"^\d+(-\d+)?번지$", token):
            cleaned = token[:-2]  # strip 번지
            parts = cleaned.split("-")
            result["bonji"] = parts[0]
            if len(parts) > 1:
                result["bunji"] = parts[1]
            continue
        if not result["bonji"] and re.match(r"^\d+(-\d+)?$", token):
            parts = token.split("-")
            result["bonji"] = parts[0]
            if len(parts) > 1:
                result["bunji"] = parts[1]
            continue
        # bonji가 이미 있을 때 NNN-NNNN → dong_no/ho_no (703-406 등)
        if (result["bonji"] and not result["dong_no"] and not result["ho_no"]
                and re.match(r"^\d+-\d+$", token)):
            parts = token.split("-")
            result["dong_no"] = parts[0]
            result["ho_no"] = parts[1]
            continue
        # 한글동숫자호 결합 (에프동2218호)
        m = re.match(r"^제?([가-힣]{1,4})동(\d+)호$", token)
        if m:
            result["dong_no"] = m.group(1)
            result["ho_no"] = m.group(2)
            continue
        m = re.match(r"^제?([가-힣A-Za-z\d]+)동$", token)
        if m:
            result["dong_no"] = m.group(1)
            continue
        # 한글+숫자+호 (씨3401호, 에이2007호, 비106호)
        m = re.match(r"^제?([가-힣]{1,4})(\d+)호$", token)
        if m:
            if not result["dong_no"]:
                result["dong_no"] = m.group(1)
            result["ho_no"] = m.group(2)
            continue
        m = re.match(r"^제?(\d+(?:-\d+)?)호$", token)
        if m:
            result["ho_no"] = m.group(1)
            continue
        # 한글-숫자 (에이-502, 나-103)
        m = re.match(r"^([가-힣]{1,4})-(\d+)$", token)
        if m:
            result["dong_no"] = m.group(1)
            result["ho_no"] = m.group(2)
            continue
        m = re.match(r"^제?(\w+)층$", token)
        if m and not result["floor"]:
            result["floor"] = m.group(1)
            continue
        remaining.append(token)

    if remaining:
        result["bldg_name"] = " ".join(remaining)

    # "N-N호" 패턴에서 dong_no가 비어있으면 자동 분리 (제1-2108호 → dong=1, ho=2108)
    if not result["dong_no"] and result["ho_no"] and "-" in result["ho_no"]:
        parts = result["ho_no"].split("-", 1)
        result["dong_no"] = parts[0]
        result["ho_no"] = parts[1]

    # dong_no가 dong과 동일하면 클리어 (중복 행정동명: "개포동 ... 개포동 개포자이")
    if result["dong_no"] and result["dong"] and result["dong_no"] == result["dong"]:
        result["dong_no"] = ""

    return result


def normalize_dong_ho(val: str) -> str:
    """동/호 값을 비교용으로 정규화한다.

    '101동' → '101', '301호' → '301', '제101동' → '101',
    '씨동' → 'C', '에이동' → 'A', '0101' → '101'.
    """
    val = str(val).strip()
    val = re.sub(r'[동호]$', '', val).strip()
    val = re.sub(r'^제', '', val).strip()
    # 한글 → 영문 변환
    mapped = _KOREAN_TO_ALPHA.get(val)
    if mapped:
        return mapped
    # 숫자만으로 구성된 경우 선행 0 제거 (0101 → 101)
    if val.isdigit():
        val = val.lstrip('0') or '0'
    return val.upper()


def filter_apartment_by_dong_ho(results: list, dong_no: str, ho_no: str) -> list:
    """공동주택/건물 결과를 동/호로 단계적 필터링한다.

    동과 호가 모두 있는 경우:
      1차 시도: 동+호를 합쳐 호에서 검색 (씨3401호 → ho="C3401")
      2차 시도(폴백): 동/호를 분리하여 필터링 (dong="C", ho="3401")

    동이 없으면 호만으로 필터링 시도.

    결과 dict의 동 필드명은 'dong' (공동주택) 또는 'dong_no' (ETAX 건물) 모두 지원.
    호 필드명은 'ho' (공통).

    동/호가 지정되었으나 매치되는 결과가 없으면 빈 리스트를 반환한다 (Fail-Closed).
    단, API가 동 정보를 비워두는 경우가 있으므로 동 필터는 결과에 동 값이
    하나라도 존재할 때만 엄격 적용하고, 모두 비어있으면 동 필터를 건너뛴다.
    """
    if not dong_no and not ho_no:
        return results

    current = results

    # 동+호 모두 있으면, 합쳐서 호 필드에서 먼저 시도
    # (예: 씨3401호 → "C3401"로 호 매칭 시도)
    if dong_no and ho_no:
        norm_dong = normalize_dong_ho(dong_no)
        norm_ho = normalize_dong_ho(ho_no)
        combined_ho = norm_dong + norm_ho
        combined_filtered = [
            r for r in current
            if normalize_dong_ho(r.get("ho", "")) == combined_ho
        ]
        if combined_filtered:
            return combined_filtered
        # 합친 값으로 매치 안 되면 아래 분리 필터링으로 폴백

    if dong_no:
        norm_dong = normalize_dong_ho(dong_no)
        # API가 동 정보를 비워두는 단지가 있으므로, 결과에 동 값이 하나라도 있는지 확인
        has_dong_data = any(
            (r.get("dong", "") or r.get("dong_no", "")).strip()
            for r in current
        )
        if has_dong_data:
            dong_filtered = [
                r for r in current
                if normalize_dong_ho(r.get("dong", "") or r.get("dong_no", "")) == norm_dong
            ]
            if dong_filtered:
                current = dong_filtered
            else:
                return []  # 동이 지정되었으나 매치 없음

    if ho_no:
        norm_ho = normalize_dong_ho(ho_no)
        ho_filtered = [r for r in current
                       if normalize_dong_ho(r.get("ho", "")) == norm_ho]
        if ho_filtered:
            current = ho_filtered
        else:
            return []  # 호가 지정되었으나 매치 없음

    return current


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
            # V-World title에 <b> 태그가 포함될 수 있으므로 제거
            title = _HTML_TAG_RE.sub("", item.get("title", ""))
            road = addr.get("road") or title
            parcel = addr.get("parcel") or title
            converted.append({
                "roadAddr": _HTML_TAG_RE.sub("", road),
                "jibunAddr": _HTML_TAG_RE.sub("", parcel),
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

    # siNm/sggNm/emdNm이 없으면 jibunAddr → roadAddr 순으로 파싱 시도
    bonji = juso_item.get("lnbrMnnm", "")
    bunji = juso_item.get("lnbrSlno", "")
    parsed = {}
    if not sido or not bonji:
        for addr_field in ("jibunAddr", "roadAddr"):
            addr_text = juso_item.get(addr_field, "")
            if addr_text:
                parsed = parse_address(addr_text)
                sido = sido or parsed.get("sido", "")
                sigungu = sigungu or parsed.get("sigungu", "")
                dong = dong or parsed.get("dong", "")
                bonji = bonji or parsed.get("bonji", "")
                bunji = bunji or parsed.get("bunji", "")
            if sido and bonji:
                break

    return {
        "road_addr": juso_item.get("roadAddr", ""),
        "jibun_addr": juso_item.get("jibunAddr", ""),
        "sido": sido,
        "sigungu": sigungu,
        "dong": dong,
        "bonji": bonji,
        "bunji": bunji,
        "bldg_name": juso_item.get("bdNm", ""),
        "pnu": extract_pnu(bd_mgt_sn),
        "adm_cd": adm_cd,
        "bd_mgt_sn": bd_mgt_sn,
        "zip_no": juso_item.get("zipNo", ""),
    }
