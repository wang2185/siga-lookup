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


_NON_APT_KEYWORDS = ("오피스텔",)


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
        if re.match(r".+[읍면동가리]$", token):
            # 읍/면 뒤에 리가 오면 리를 dong으로 갱신 (부발읍 무촌리 → dong=무촌)
            if result["dong"] and re.match(r".+리$", token):
                result["dong"] = re.sub(r"리$", "", token)
                continue
            if not result["dong"]:
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
        # 한글+숫자+호 — '동' 없이 붙어있는 패턴 (씨3401호, 에이2007호, 비106호)
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
        # 영문+숫자 조합-숫자+호 (A09-0043호, B11-0201호)
        m = re.match(r"^제?([A-Za-z]\d+)-(\d+)호$", token)
        if m:
            result["ho_no"] = m.group(1) + "-" + m.group(2)
            continue
        # 영문-숫자+호 (C-2302호, A-502호 — 갤러리아팰리스 등)
        m = re.match(r"^제?([A-Za-z])-?(\d+)호$", token)
        if m:
            result["ho_no"] = m.group(1).upper() + "-" + m.group(2)
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
    # 단, 첫 부분이 숫자인 경우만 (A-1210 같은 영문 접두어는 원본 보존)
    if not result["dong_no"] and result["ho_no"] and "-" in result["ho_no"]:
        parts = result["ho_no"].split("-", 1)
        if parts[0].isdigit():
            result["dong_no"] = parts[0]
            result["ho_no"] = parts[1]
        # "A-1210" → ho_no="A-1210" 그대로 유지 (변환은 variation generator에서)

    # dong_no가 dong과 동일하면 클리어 (중복 행정동명: "개포동 ... 개포동 개포자이")
    if result["dong_no"] and result["dong"] and result["dong_no"] == result["dong"]:
        result["dong_no"] = ""

    # 건물 유형 키워드 감지 (오피스텔 등 → 공동주택이 아닌 주택외건물)
    for kw in _NON_APT_KEYWORDS:
        if kw in addr_str:
            result["building_type_hint"] = kw
            # dong_no에 키워드가 포함되어 있으면 분리 ("오피스텔103" → "103")
            if result["dong_no"] and kw in result["dong_no"]:
                result["dong_no"] = result["dong_no"].replace(kw, "")
            break

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

    1단계: 동/호를 그대로(한글 포함) 분리하여 필터링
    2단계(폴백): 한글 동을 영문 변환 후 동+호 합산 매칭
              (예: dong='씨', ho='3401' → 'C3401')
    3단계(폴백): 영문 변환 후 분리 매칭
              (예: dong='씨' → 'C'로 변환하여 dong='C' 매칭)

    동이 없으면 호만으로 필터링 시도.

    결과 dict의 동 필드명은 'dong' (공동주택) 또는 'dong_no' (ETAX 건물) 모두 지원.
    호 필드명은 'ho' (공통).

    동/호가 지정되었으나 매치되는 결과가 없으면 빈 리스트를 반환한다 (Fail-Closed).
    단, API가 동 정보를 비워두는 경우가 있으므로 동 필터는 결과에 동 값이
    하나라도 존재할 때만 엄격 적용하고, 모두 비어있으면 동 필터를 건너뛴다.
    """
    if not dong_no and not ho_no:
        return results

    def _get_dong(r):
        return (r.get("dong", "") or r.get("dong_no", "")).strip()

    current = results

    # 1단계: 동/호 분리 필터링 (한글 그대로)
    if dong_no:
        norm_dong = normalize_dong_ho(dong_no)
        has_dong_data = any(_get_dong(r) for r in current)
        if has_dong_data:
            dong_filtered = [
                r for r in current
                if normalize_dong_ho(_get_dong(r)) == norm_dong
            ]
            if dong_filtered:
                current = dong_filtered
            else:
                # 동 매치 실패 → 합산 폴백 (dong+ho를 합쳐 ho에서 검색)
                if ho_no:
                    norm_ho = normalize_dong_ho(ho_no)
                    combined_ho = norm_dong + norm_ho
                    combined_filtered = [
                        r for r in results
                        if normalize_dong_ho(r.get("ho", "")) == combined_ho
                    ]
                    if combined_filtered:
                        return combined_filtered
                return []  # 분리도 합산도 매치 없음

    if ho_no:
        norm_ho = normalize_dong_ho(ho_no)
        ho_filtered = [r for r in current
                       if normalize_dong_ho(r.get("ho", "")) == norm_ho]
        if ho_filtered:
            current = ho_filtered
        else:
            # 폴백 1: API ho에 동 접두어가 포함된 경우 (ho="C-2302" → "2302"로 비교)
            # 동이 이미 매치된 상태에서, ho에서 "동-" 접두어를 제거하고 재비교
            if dong_no:
                norm_dong = normalize_dong_ho(dong_no)
                stripped_filtered = [
                    r for r in current
                    if _strip_dong_prefix(normalize_dong_ho(r.get("ho", "")), norm_dong) == norm_ho
                ]
                if stripped_filtered:
                    return stripped_filtered
                # 폴백 2: 동+호 합산 (dong=씨 + ho=3401 → C3401)
                combined_ho = norm_dong + norm_ho
                combined_filtered = [
                    r for r in results
                    if normalize_dong_ho(r.get("ho", "")) == combined_ho
                ]
                if combined_filtered:
                    return combined_filtered
            return []  # 호가 지정되었으나 매치 없음

    return current


def _strip_dong_prefix(ho_val: str, dong_val: str) -> str:
    """호 값에서 동 접두어를 제거한다.

    API가 ho="C-2302"처럼 동 접두어를 포함하는 경우,
    dong="C"가 이미 매치된 상태에서 호 비교를 위해 접두어를 제거.
    (C-2302 → 2302, A502 → 502)
    """
    if not ho_val or not dong_val:
        return ho_val
    # "C-2302" → dong="C" → strip "C-" → "2302"
    prefix_dash = dong_val + "-"
    if ho_val.startswith(prefix_dash):
        return ho_val[len(prefix_dash):]
    # "C2302" → dong="C" → strip "C" → "2302"
    if ho_val.startswith(dong_val) and len(ho_val) > len(dong_val):
        rest = ho_val[len(dong_val):]
        if rest[0].isdigit():
            return rest
    return ho_val


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
