"""주택외건물 서울 지역 시가표준액 조회 — Seoul ETAX (HTTP POST)."""

import html as _html
import re
import ssl

import requests as http_requests
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from .base import BaseLookupModule, LookupResult

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ETAX_BASE = "https://etax.seoul.go.kr"
ETAX_VIEW_URL = f"{ETAX_BASE}/BldnStndAmtLstAction.view?gnb_id=0709&lnb_id=0709&gl_gubun=l"
ETAX_TRAN_URL = f"{ETAX_BASE}/BldnStndAmtLstAction.tran"

ETAX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": ETAX_VIEW_URL,
    "Content-Type": "application/x-www-form-urlencoded",
}

ETAX_SIGU = {
    "강남구": "680", "강동구": "740", "강북구": "305", "강서구": "500",
    "관악구": "620", "광진구": "215", "구로구": "530", "금천구": "545",
    "노원구": "350", "도봉구": "320", "동대문구": "230", "동작구": "590",
    "마포구": "440", "서대문구": "410", "서초구": "650", "성동구": "200",
    "성북구": "290", "송파구": "710", "양천구": "470", "영등포구": "560",
    "용산구": "170", "은평구": "380", "종로구": "110", "중구": "140",
    "중랑구": "260",
}

ETAX_TSJ = {
    "일반번지": "1", "산번지": "2", "도로번지": "3", "기타번지(4)": "4",
    "기획번지": "5", "임천번지": "6", "산복번지": "7", "기타번지(8)": "8",
    "특수번지": "0",
}


class _LegacySSLAdapter(HTTPAdapter):
    """ETAX 서버의 약한 DH 키를 허용하기 위한 커스텀 SSL 어댑터."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _etax_session():
    s = http_requests.Session()
    s.mount("https://", _LegacySSLAdapter())
    return s


# 법정동 캐시
_dong_cache: dict = {}


class SeoulETaxModule(BaseLookupModule):

    @property
    def property_type(self) -> str:
        return "building"

    @property
    def property_type_label(self) -> str:
        return "주택외건물 (시가표준액)"

    @property
    def source_name(self) -> str:
        return "etax"

    def search(self, address: dict, year: str = "", **kwargs) -> LookupResult:
        from datetime import datetime
        if not year:
            year = str(datetime.now().year - 1)
        sigu_code = kwargs.get("sigu_code", "")
        hdong_code = kwargs.get("hdong_code", "")
        bonbun = address.get("bonji", "")
        bubun = address.get("bunji", "")
        tsj_gubun = kwargs.get("tsj_gubun", "1")
        dong = kwargs.get("dong_no", address.get("dong_no", ""))
        hosu = kwargs.get("ho_no", address.get("ho_no", ""))

        # 메인 폼에서 sigu_code가 없으면 주소 정보로 자동 추출
        if not sigu_code:
            sigungu = address.get("sigungu", "")
            for name, code in ETAX_SIGU.items():
                if sigungu and (sigungu in name or name in sigungu):
                    sigu_code = code
                    break

        if not hdong_code and sigu_code:
            dong_name = address.get("dong", "")
            if dong_name:
                dong_cache = get_dong_cache()
                dongs = dong_cache.get(sigu_code, {})
                for code, name in dongs.items():
                    if dong_name in name or name.replace("동", "") == dong_name:
                        hdong_code = code
                        break

        if not sigu_code or not bonbun:
            return LookupResult(
                success=False,
                property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""),
                year=year or "전체",
                results=[],
                source=self.source_name,
                error="자치구 또는 본번을 추출할 수 없습니다. ETAX 전용 페이지에서 직접 조회해주세요.",
            )

        try:
            results, raw_html = etax_search(
                sigu_code, hdong_code, bonbun, bubun, tsj_gubun, year, dong, hosu
            )
            evidence = None
            if results and raw_html:
                evidence = _build_evidence_pdf(
                    raw_html, address.get("_raw", ""), year)
            return LookupResult(
                success=True,
                property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""),
                year=year or "전체",
                results=results,
                source=self.source_name,
                evidence=evidence,
                evidence_type="pdf" if evidence else "",
            )
        except Exception as e:
            return LookupResult(
                success=False,
                property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""),
                year=year or "전체",
                results=[],
                source=self.source_name,
                error=f"조회 중 오류 발생: {e}",
            )

    @staticmethod
    def get_sigu_list():
        return sorted(ETAX_SIGU.items())

    @staticmethod
    def get_tsj_list():
        return ETAX_TSJ

    @staticmethod
    def get_years():
        return list(range(2026, 2011, -1))


def fetch_dong_list() -> dict:
    """ETAX VIEW 페이지에서 자치구별 법정동 목록을 파싱한다."""
    sess = _etax_session()
    resp = sess.get(ETAX_VIEW_URL, headers=ETAX_HEADERS, verify=False, timeout=15)
    html = resp.content.decode("euc-kr", errors="replace")
    dong_map = {}
    for sigu_name, sigu_code in ETAX_SIGU.items():
        pattern = rf'<select[^>]*name=["\']HDONG{sigu_code}["\'][^>]*>(.*?)</select>'
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            continue
        options = re.findall(
            r'<option\s+value=["\']([^"\']*)["\'][^>]*>([^<]*)</option>',
            match.group(1),
        )
        dongs = {}
        for val, label in options:
            if val == "000":
                continue
            dongs[val] = label.strip()
        dong_map[sigu_code] = dongs
    return dong_map


def get_dong_cache() -> dict:
    global _dong_cache
    if not _dong_cache:
        try:
            _dong_cache = fetch_dong_list()
        except Exception:
            _dong_cache = {}
    return _dong_cache


def etax_search(sigu_code, hdong_code, bonbun, bubun="",
                tsj_gubun="1", gwapo_year="", dong="", hosu=""):
    """서울시 ETAX 주택외건물 시가표준액을 조회한다.

    Returns (results, raw_html) 튜플.
    """
    data = {
        "sysCode": "EAX", "transSeq1": "1", "isLogin": "", "transKey": "",
        "lastCmd": "", "enc_data": "", "param_r1": "", "param_r2": "",
        "param_r3": "", "SIGU_NAME": "null", "PRE_SIGU_CD": sigu_code,
        "HDONG_CD": hdong_code, "BDONG_CD": "99999", "SIGU_CD": sigu_code,
        f"HDONG{sigu_code}": hdong_code, "tsj_gubun": tsj_gubun,
        "bonbun": bonbun, "bubun": bubun, "dong": dong, "hosu": hosu,
        "downExcel": "N", "GWAPO_YEAR": gwapo_year, "INPUT": "",
        "r_bonbun": "", "r_bubun": "", "r_dong": "", "r_hosu": "",
        "r_gwapo": "", "r_area_total": "", "r_gwapo_year": "",
    }
    sess = _etax_session()
    resp = sess.post(
        ETAX_TRAN_URL, data=data, headers=ETAX_HEADERS, verify=False, timeout=15,
    )
    html = resp.content.decode("euc-kr", errors="replace")
    return _parse_results(html), html


def _etax_evidence_url_fetcher(url, timeout=10, ssl_context=None):
    """ETAX 캡처 전용 URL fetcher.

    etax.seoul.go.kr 자체 자산(CSS/이미지)과 폰트 CDN만 허용한다.
    그 외 호스트와 file:// 등 로컬 스킴은 빈 응답으로 무시한다.
    예외를 던지지 않아 단일 자산 실패가 PDF 렌더링 전체를 깨뜨리지 않는다.
    """
    from urllib.parse import urlparse
    from weasyprint import default_url_fetcher
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        # file://, data:, javascript: 등은 모두 빈 응답으로 차단
        return {"string": b"", "mime_type": "text/plain"}
    allowed = {"etax.seoul.go.kr", "fonts.googleapis.com", "fonts.gstatic.com"}
    hostname = (parsed.hostname or "").lower()
    if hostname not in allowed:
        return {"string": b"", "mime_type": "text/plain"}
    return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)


def _build_evidence_pdf(raw_html: str, address: str, year: str) -> bytes | None:
    """ETAX 응답 HTML을 그대로 PDF로 캡처한다.

    etax.seoul.go.kr가 반환한 원본 HTML을 base_url과 함께 WeasyPrint로
    렌더링하여 실제 ETAX 사이트의 모습을 증거 PDF로 생성한다.
    조회 메타정보(주소·기준년도·조회일시)는 상단 배너로 삽입한다.
    """
    if not raw_html:
        return None
    try:
        from weasyprint import HTML as WpHTML
    except ImportError:
        return None

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # int 등 비문자열도 안전하게 escape (호출부가 항상 str을 보장하지는 않음)
    safe_address = _html.escape(str(address) if address else "")
    safe_year = _html.escape(str(year) if year else "전체")

    # 조회 메타정보 헤더 배너 (원본 캡처임을 명시)
    banner = (
        '<div style="border:2px solid #c00;padding:10px;margin:0 0 12px 0;'
        'font-family:\'Malgun Gothic\',\'Noto Sans KR\',sans-serif;font-size:10pt;'
        'color:#333;background:#fff;">'
        '<strong style="color:#c00;font-size:11pt;">'
        '서울시 ETAX 주택외건물 시가표준액 — 원본 캡처</strong><br>'
        f'조회 주소: {safe_address}<br>'
        f'기준년도: {safe_year}<br>'
        f'조회일시: {now}<br>'
        '출처: 서울특별시 ETAX (etax.seoul.go.kr)'
        '</div>'
    )

    # 상대 URL은 WeasyPrint의 base_url 파라미터로 해석되므로 <base> 태그 주입은 불필요.
    # 메타정보 배너를 <body> 시작 직후에 삽입하여 PDF 첫 페이지에 표시한다.
    # <body class="..."> 같이 속성이 붙은 경우도 매칭하도록 정규식 사용.
    if re.search(r"<body[\s>]", raw_html, re.IGNORECASE):
        injected = re.sub(
            r"(<body[^>]*>)",
            lambda m: m.group(1) + banner,
            raw_html,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        # body가 없는 단편 HTML(테이블 등)은 표준 골격으로 감싼다
        injected = f"<html><body>{banner}{raw_html}</body></html>"

    try:
        return WpHTML(
            string=injected,
            base_url=ETAX_BASE + "/",
            url_fetcher=_etax_evidence_url_fetcher,
        ).write_pdf()
    except Exception:
        return None


def _parse_results(html):
    """ETAX 응답 HTML에서 결과 테이블을 파싱한다."""
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 2:
        return []
    result_table = tables[1]
    rows = result_table.find_all("tr")
    if len(rows) <= 1:
        return []

    results = []
    current = None
    for row in rows[1:]:
        tds = row.find_all("td")
        if not tds:
            continue
        cells = [td.get_text(strip=True) for td in tds]
        if len(cells) >= 8:
            area = cells[8] if len(cells) > 8 else ""
            area = area.replace("(m²)", "").replace("(m\u00b2)", "").strip()
            current = {
                "no": cells[0],
                "year": cells[1],
                "lot": cells[2],
                "dong_no": cells[3],
                "ho": cells[4],
                "name": cells[5],
                "total": cells[7],
                "area": area,
                "building": "",
                "land": "",
            }
            results.append(current)
        elif len(cells) == 2 and current:
            label, value = cells
            if "건물" in label:
                current["building"] = value
            elif "토지" in label:
                current["land"] = value
    return results
