"""
위택스(WeTax) + 서울시 ETAX 시가표준액 조회 웹앱
Flask + 서버 사이드 Selenium(위택스) / requests(ETAX)
"""

import re
import ssl
import time
import traceback

import requests as http_requests
import urllib3
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify
from requests.adapters import HTTPAdapter
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
    """ETAX용 requests.Session을 생성한다."""
    s = http_requests.Session()
    s.mount("https://", _LegacySSLAdapter())
    return s

app = Flask(__name__)

URL = "https://www.wetax.go.kr/tcp/loi/J030401M01.do"

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


def parse_address(addr_str):
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


# ─── Selenium 헬퍼 ───

def wait_and_select(driver, select_id, keyword, timeout=12):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            el = driver.find_element(By.ID, select_id)
            for opt in el.find_elements(By.TAG_NAME, "option"):
                text = opt.text.strip()
                if keyword in text and text not in ("", "선택", "전체"):
                    value = opt.get_attribute("value")
                    driver.execute_script(
                        "var sel=document.getElementById(arguments[0]);"
                        "sel.value=arguments[1];"
                        "sel.dispatchEvent(new Event('change',{bubbles:true}));",
                        select_id, value,
                    )
                    return True
        except StaleElementReferenceException:
            pass
        time.sleep(0.5)
    return False


def click_radio(driver, radio_id):
    try:
        el = driver.find_element(By.ID, radio_id)
        driver.execute_script("arguments[0].click();", el)
        return True
    except NoSuchElementException:
        pass
    try:
        label = driver.find_element(By.CSS_SELECTOR, f"label[for='{radio_id}']")
        label.click()
        return True
    except NoSuchElementException:
        pass
    return False


def click_radio_by_label_text(driver, label_text):
    for label in driver.find_elements(By.TAG_NAME, "label"):
        if label_text in label.text:
            try:
                label.click()
                return True
            except Exception:
                for_id = label.get_attribute("for")
                if for_id:
                    return click_radio(driver, for_id)
    for radio in driver.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
        try:
            parent = radio.find_element(By.XPATH, "./..")
            if label_text in parent.text:
                driver.execute_script("arguments[0].click();", radio)
                return True
        except Exception:
            continue
    return False


def fill_input(driver, element_id, value):
    try:
        el = driver.find_element(By.ID, element_id)
        if el.is_displayed():
            el.clear()
            el.send_keys(value)
            return True
    except NoSuchElementException:
        pass
    return False


def find_visible_input(driver, id_candidates):
    for eid in id_candidates:
        try:
            el = driver.find_element(By.ID, eid)
            if el.is_displayed():
                return eid
        except NoSuchElementException:
            continue
    return None


def select_first_valid_option(driver, select_id):
    try:
        el = driver.find_element(By.ID, select_id)
        if not el.is_displayed():
            return
        for opt in el.find_elements(By.TAG_NAME, "option"):
            val = opt.get_attribute("value")
            text = opt.text.strip()
            if val and text not in ("", "선택", "전체"):
                driver.execute_script(
                    "var sel=document.getElementById(arguments[0]);"
                    "sel.value=arguments[1];"
                    "sel.dispatchEvent(new Event('change',{bubbles:true}));",
                    select_id, val,
                )
                return
    except NoSuchElementException:
        pass


def select_option_containing(driver, select_id, keyword):
    try:
        el = driver.find_element(By.ID, select_id)
        if not el.is_displayed():
            return False
        for opt in el.find_elements(By.TAG_NAME, "option"):
            text = opt.text.strip()
            if keyword in text and text not in ("", "선택", "전체"):
                val = opt.get_attribute("value")
                driver.execute_script(
                    "var sel=document.getElementById(arguments[0]);"
                    "sel.value=arguments[1];"
                    "sel.dispatchEvent(new Event('change',{bubbles:true}));",
                    select_id, val,
                )
                return True
    except NoSuchElementException:
        pass
    return False


def fill_dong_ho(driver, dong_no, ho_no):
    if dong_no:
        did = find_visible_input(driver, ["txtExstDongna"])
        if did:
            fill_input(driver, did, dong_no)
        else:
            for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='text']"):
                if not inp.is_displayed():
                    continue
                attrs = " ".join([
                    inp.get_attribute("placeholder") or "",
                    inp.get_attribute("title") or "",
                    inp.get_attribute("id") or "",
                    inp.get_attribute("name") or "",
                ])
                if "동" in attrs and "읍" not in attrs and "stdg" not in attrs:
                    inp.clear()
                    inp.send_keys(dong_no)
                    break

    if ho_no:
        hid = find_visible_input(driver, ["txtExstHoadr"])
        if hid:
            fill_input(driver, hid, ho_no)
        else:
            for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='text']"):
                if not inp.is_displayed():
                    continue
                attrs = " ".join([
                    inp.get_attribute("placeholder") or "",
                    inp.get_attribute("title") or "",
                    inp.get_attribute("id") or "",
                    inp.get_attribute("name") or "",
                ])
                if "호" in attrs and "전화" not in attrs:
                    inp.clear()
                    inp.send_keys(ho_no)
                    break


def extract_all_results(driver):
    results = []
    for tid in ["tb_BldsCpbInq", "tb_hos", "tb_mfh"]:
        try:
            table = driver.find_element(By.ID, tid)
            if not table.is_displayed():
                continue
            for row in table.find_elements(By.TAG_NAME, "tr"):
                cells = row.find_elements(By.TAG_NAME, "td")
                if cells:
                    data = [c.text.strip() for c in cells]
                    if any(data):
                        results.append(data)
        except NoSuchElementException:
            continue

    if not results:
        for sel in ["div.cfGrid table", "div.grid-body table",
                     "table.tbl_list", "div[id*='grid'] table"]:
            try:
                for table in driver.find_elements(By.CSS_SELECTOR, sel):
                    if not table.is_displayed():
                        continue
                    for row in table.find_elements(By.TAG_NAME, "tr"):
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if cells:
                            data = [c.text.strip() for c in cells]
                            if any(data):
                                results.append(data)
            except Exception:
                continue
    return results


def run_search(addr):
    """Selenium으로 위택스 조회를 수행하고 결과를 반환한다."""
    logs = []

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("--window-size=1400,900")

    driver = webdriver.Chrome(options=chrome_options)

    try:
        logs.append("Chrome 브라우저 시작")
        driver.get(URL)
        time.sleep(3)
        logs.append("위택스 페이지 접속 완료")

        # 기존건물 라디오
        try:
            radio = driver.find_element(By.ID, "radio_02_01")
            if not radio.is_selected():
                click_radio(driver, "radio_02_01")
        except NoSuchElementException:
            click_radio_by_label_text(driver, "기존")
        time.sleep(1)

        # 시/도
        logs.append(f"시/도 선택: {addr['sido']}")
        if not wait_and_select(driver, "selUpLgvCd", addr["sido"]):
            logs.append("시/도 선택 실패")
        time.sleep(2)

        # 시/군/구
        logs.append(f"시/군/구 선택: {addr['sigungu']}")
        if not wait_and_select(driver, "selLgvCd", addr["sigungu"]):
            logs.append("시/군/구 선택 실패")
        time.sleep(2)

        # 읍/면/동
        logs.append(f"읍/면/동 선택: {addr['dong']}")
        if not wait_and_select(driver, "selStdgCd", addr["dong"]):
            logs.append("읍/면/동 선택 실패")
        time.sleep(1)

        # 기준년도
        select_first_valid_option(driver, "selCrtrYr")
        time.sleep(0.5)

        # 특수번지
        if addr["san"]:
            select_option_containing(driver, "selExstSpeLotno", "산")
        else:
            select_first_valid_option(driver, "selExstSpeLotno")
        time.sleep(0.5)

        # 본번지
        logs.append(f"본번지 입력: {addr['bonji']}")
        prlno_id = find_visible_input(driver, ["txtExstPrlno", "txtPrlno"])
        if prlno_id:
            fill_input(driver, prlno_id, addr["bonji"])

        # 부번지
        if addr["bunji"]:
            for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='text']"):
                if not inp.is_displayed():
                    continue
                attrs = " ".join([
                    inp.get_attribute("id") or "",
                    inp.get_attribute("name") or "",
                    inp.get_attribute("title") or "",
                ])
                if "bsno" in attrs.lower() or "부번" in attrs:
                    inp.clear()
                    inp.send_keys(addr["bunji"])
                    break

        # 동/호
        fill_dong_ho(driver, addr["dong_no"], addr["ho_no"])
        time.sleep(0.5)

        # 검색 클릭
        logs.append("검색 실행")
        try:
            btn = driver.find_element(By.ID, "btnSrchBldsCpb")
            driver.execute_script("arguments[0].click();", btn)
        except NoSuchElementException:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                if "조회" in btn.text or "검색" in btn.text:
                    driver.execute_script("arguments[0].click();", btn)
                    break

        time.sleep(5)

        # alert 처리
        alert_msg = None
        try:
            alert = driver.switch_to.alert
            alert_msg = alert.text
            alert.accept()
        except Exception:
            pass

        # 결과 수집
        results = extract_all_results(driver)
        logs.append(f"결과 {len(results)}건 수집")

        message = None
        if not results:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            if "존재하지 않습니다" in body_text:
                message = "검색하신 건물동-호가 존재하지 않습니다."
            elif "호를 입력" in body_text:
                message = "집합건물입니다. 호를 입력해야 합니다."
            elif "조회되지 않습니다" in body_text:
                message = "조회 결과가 없습니다."
            else:
                message = "결과를 자동 파싱하지 못했습니다."

        return {
            "success": True,
            "results": results,
            "message": message,
            "alert": alert_msg,
            "logs": logs,
        }

    except Exception as e:
        return {
            "success": False,
            "results": [],
            "message": f"오류 발생: {e}",
            "alert": None,
            "logs": logs,
            "error": traceback.format_exc(),
        }
    finally:
        driver.quit()


# ─── Flask 라우트 ───

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search", methods=["POST"])
def search():
    addr_str = request.form.get("address", "").strip()
    if not addr_str:
        return render_template("index.html", error="주소를 입력해주세요.")

    addr = parse_address(addr_str)

    if not addr["sido"] or not addr["sigungu"] or not addr["dong"] or not addr["bonji"]:
        return render_template("index.html",
                               error="시/도, 시/군/구, 읍/면/동, 번지는 필수입니다.",
                               address=addr_str, parsed=addr)

    result = run_search(addr)
    return render_template("result.html",
                           address=addr_str, parsed=addr, result=result)


# ─── 서울시 ETAX 주택외건물 시가표준액 조회 ───

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


def etax_fetch_dong_list():
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
    return _etax_parse_results(html)


def _etax_parse_results(html):
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


# ETAX 법정동 캐시
_etax_dong_cache = {}


@app.route("/etax")
def etax_index():
    global _etax_dong_cache
    if not _etax_dong_cache:
        try:
            _etax_dong_cache = etax_fetch_dong_list()
        except Exception:
            _etax_dong_cache = {}
    return render_template(
        "etax.html",
        sigu_list=sorted(ETAX_SIGU.items()),
        tsj_list=ETAX_TSJ,
        years=list(range(2026, 2011, -1)),
    )


@app.route("/etax/dongs")
def etax_dongs():
    """자치구 코드에 해당하는 법정동 목록을 JSON으로 반환한다."""
    global _etax_dong_cache
    sigu_code = request.args.get("sigu", "")
    if not _etax_dong_cache:
        try:
            _etax_dong_cache = etax_fetch_dong_list()
        except Exception:
            return jsonify([])
    dongs = _etax_dong_cache.get(sigu_code, {})
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

    try:
        results = etax_search(
            sigu_code, hdong_code, bonbun, bubun, tsj, year, dong, hosu,
        )
    except Exception as e:
        return render_template(
            "etax_result.html",
            error=f"조회 중 오류 발생: {e}",
            results=[], query={},
        )

    query = {
        "sigu_name": sigu_name, "bonbun": bonbun, "bubun": bubun,
        "year": year or "전체", "dong": dong, "hosu": hosu,
    }
    return render_template("etax_result.html", results=results, query=query)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
