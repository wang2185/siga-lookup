"""주택외건물 서울 지역 시가표준액 조회 — Seoul ETAX (HTTP POST)."""

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
        sigu_code = kwargs.get("sigu_code", "")
        hdong_code = kwargs.get("hdong_code", "")
        bonbun = address.get("bonji", "")
        bubun = address.get("bunji", "")
        tsj_gubun = kwargs.get("tsj_gubun", "1")
        dong = kwargs.get("dong_no", address.get("dong_no", ""))
        hosu = kwargs.get("ho_no", address.get("ho_no", ""))

        try:
            results = etax_search(
                sigu_code, hdong_code, bonbun, bubun, tsj_gubun, year, dong, hosu
            )
            return LookupResult(
                success=True,
                property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""),
                year=year or "전체",
                results=results,
                source=self.source_name,
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
    """서울시 ETAX 주택외건물 시가표준액을 조회한다."""
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
    return _parse_results(html)


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
