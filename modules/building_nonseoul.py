"""주택외건물 비서울 지역 시가표준액 조회 — WeTax (Selenium)."""

import time
import traceback

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from .base import BaseLookupModule, LookupResult

WETAX_URL = "https://www.wetax.go.kr/tcp/loi/J030401M01.do"


class WeTaxModule(BaseLookupModule):

    @property
    def property_type(self) -> str:
        return "building"

    @property
    def property_type_label(self) -> str:
        return "주택외건물 (시가표준액)"

    @property
    def source_name(self) -> str:
        return "wetax"

    def search(self, address: dict, year: str = "", **kwargs) -> LookupResult:
        building_type = kwargs.get("building_type", "existing")  # "existing" or "factory"
        result = self._run_search(address, building_type)
        return LookupResult(
            success=result["success"],
            property_type=kwargs.get("override_type", self.property_type),
            property_type_label=kwargs.get("override_label", self.property_type_label),
            address=address.get("_raw", ""),
            year=year,
            results=result["results"],
            source=self.source_name,
            error=result.get("error"),
            message=result.get("message"),
            logs=result.get("logs", []),
            evidence=result.get("evidence"),
            evidence_type="png" if result.get("evidence") else "",
        )

    def _run_search(self, addr: dict, building_type: str = "existing") -> dict:
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
            driver.get(WETAX_URL)
            time.sleep(3)
            logs.append("위택스 페이지 접속 완료")

            # 건물 유형 라디오
            if building_type == "factory":
                try:
                    radio = driver.find_element(By.ID, "radio_02_02")
                    if not radio.is_selected():
                        _click_radio(driver, "radio_02_02")
                except NoSuchElementException:
                    _click_radio_by_label_text(driver, "공장")
            else:
                try:
                    radio = driver.find_element(By.ID, "radio_02_01")
                    if not radio.is_selected():
                        _click_radio(driver, "radio_02_01")
                except NoSuchElementException:
                    _click_radio_by_label_text(driver, "기존")
            time.sleep(1)

            # 시/도
            logs.append(f"시/도 선택: {addr.get('sido', '')}")
            if not _wait_and_select(driver, "selUpLgvCd", addr.get("sido", "")):
                logs.append("시/도 선택 실패")
            time.sleep(2)

            # 시/군/구 — 하위 구가 있으면 우선 사용 (고양시 일산동구 등)
            sigungu_kw = addr.get("sigungu_sub", "") or addr.get("sigungu", "")
            logs.append(f"시/군/구 선택: {sigungu_kw}")
            if not _wait_and_select(driver, "selLgvCd", sigungu_kw):
                # 하위 구로 실패 시 상위 시군으로 재시도
                if addr.get("sigungu_sub") and addr.get("sigungu"):
                    logs.append(f"시/군/구 재시도: {addr['sigungu']}")
                    _wait_and_select(driver, "selLgvCd", addr["sigungu"])
                else:
                    logs.append("시/군/구 선택 실패")
            time.sleep(2)

            # 읍/면/동
            logs.append(f"읍/면/동 선택: {addr.get('dong', '')}")
            if not _wait_and_select(driver, "selStdgCd", addr.get("dong", "")):
                logs.append("읍/면/동 선택 실패")
            time.sleep(1)

            # 기준년도
            _select_first_valid_option(driver, "selCrtrYr")
            time.sleep(0.5)

            # 특수번지
            if addr.get("san"):
                _select_option_containing(driver, "selExstSpeLotno", "산")
            else:
                _select_first_valid_option(driver, "selExstSpeLotno")
            time.sleep(0.5)

            # 본번지
            logs.append(f"본번지 입력: {addr.get('bonji', '')}")
            prlno_id = _find_visible_input(driver, ["txtExstPrlno", "txtPrlno"])
            if prlno_id:
                _fill_input(driver, prlno_id, addr.get("bonji", ""))

            # 부번지
            if addr.get("bunji"):
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
            dong_no = addr.get("dong_no", "")
            ho_no = addr.get("ho_no", "")
            _fill_dong_ho(driver, dong_no, ho_no)
            time.sleep(0.5)

            # 검색 실행 및 결과 수집
            results, evidence = _click_search_and_extract(driver, logs)

            # 재시도: 호만 입력했는데 결과 없으면 동=1로 재시도
            if not results and ho_no and not dong_no:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                if "존재하지 않습니다" in body_text or "호를 입력" in body_text:
                    logs.append("동 미입력 → 동=1로 재시도")
                    _fill_dong_ho(driver, "1", ho_no)
                    time.sleep(0.5)
                    results, evidence = _click_search_and_extract(driver, logs)

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

            return {"success": True, "results": results, "message": message,
                    "logs": logs, "evidence": evidence}

        except Exception as e:
            return {
                "success": False, "results": [], "message": f"오류 발생: {e}",
                "logs": logs, "error": traceback.format_exc(),
            }
        finally:
            driver.quit()


# ─── Selenium 헬퍼 함수들 ───

def _wait_and_select(driver, select_id, keyword, timeout=12):
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


def _click_radio(driver, radio_id):
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


def _click_radio_by_label_text(driver, label_text):
    for label in driver.find_elements(By.TAG_NAME, "label"):
        if label_text in label.text:
            try:
                label.click()
                return True
            except Exception:
                for_id = label.get_attribute("for")
                if for_id:
                    return _click_radio(driver, for_id)
    return False


def _fill_input(driver, element_id, value):
    try:
        el = driver.find_element(By.ID, element_id)
        if el.is_displayed():
            el.clear()
            el.send_keys(value)
            return True
    except NoSuchElementException:
        pass
    return False


def _find_visible_input(driver, id_candidates):
    for eid in id_candidates:
        try:
            el = driver.find_element(By.ID, eid)
            if el.is_displayed():
                return eid
        except NoSuchElementException:
            continue
    return None


def _select_first_valid_option(driver, select_id):
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


def _select_option_containing(driver, select_id, keyword):
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


def _fill_dong_ho(driver, dong_no, ho_no):
    if dong_no:
        did = _find_visible_input(driver, ["txtExstDongna"])
        if did:
            _fill_input(driver, did, dong_no)
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
        hid = _find_visible_input(driver, ["txtExstHoadr"])
        if hid:
            _fill_input(driver, hid, ho_no)
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


def _hide_security_popups(driver):
    """키보드 보안 팝업 등 불필요한 오버레이 요소를 숨긴다."""
    try:
        driver.execute_script("""
            // 키보드 보안 프로그램 관련 요소 제거
            var selectors = [
                '[class*="nppfs"]', '[class*="NPPFS"]',
                '[id*="nppfs"]', '[id*="NPPFS"]',
                '[class*="keyboard"]', '[class*="Keyboard"]',
                '[class*="astx"]', '[class*="ASTx"]',
                '[class*="touchen"]', '[class*="TouchEn"]',
                '[class*="nProtect"]', '[class*="nprotect"]',
                '[class*="initech"]', '[class*="INITECH"]',
                '[class*="KDefense"]', '[class*="kdefense"]',
                '[class*="npPfsTarget"]',
                'div.npPfsTarget',
                '#nppfs-wrapper',
                'iframe[src*="security"]',
                'iframe[src*="nppfs"]',
                'iframe[src*="touchen"]',
                'iframe[src*="astx"]'
            ];
            selectors.forEach(function(sel) {
                try {
                    document.querySelectorAll(sel).forEach(function(el) {
                        el.style.setProperty('display', 'none', 'important');
                        el.style.setProperty('visibility', 'hidden', 'important');
                    });
                } catch(e) {}
            });
            // 우측 하단 고정 위치 소형 요소 제거 (보안 팝업 특성)
            document.querySelectorAll('div, iframe, object, embed, span').forEach(function(el) {
                try {
                    var style = window.getComputedStyle(el);
                    if (style.position === 'fixed' || style.position === 'absolute') {
                        var rect = el.getBoundingClientRect();
                        var vw = window.innerWidth;
                        var vh = window.innerHeight;
                        if (rect.left > vw - 400 && rect.top > vh - 300 &&
                            rect.width < 400 && rect.height < 200 && rect.width > 0) {
                            el.style.setProperty('display', 'none', 'important');
                        }
                    }
                } catch(e) {}
            });
        """)
    except Exception:
        pass


def _click_search_and_extract(driver, logs):
    """검색 버튼 클릭 → alert 처리 → 결과 추출 → 스크린샷 캡처."""
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

    try:
        alert = driver.switch_to.alert
        alert.accept()
    except Exception:
        pass

    results = _extract_all_results(driver)
    logs.append(f"결과 {len(results)}건 수집")

    # 스크린샷 전 키보드 보안 팝업 제거
    _hide_security_popups(driver)

    evidence = None
    try:
        evidence = driver.get_screenshot_as_png()
        logs.append("스크린샷 캡처 완료")
    except Exception:
        pass

    return results, evidence


# ─── 테이블 결과 dict 변환 ───

_HEADER_KEY_MAP = [
    (("소재지", "물건", "건물명", "건물소재"), "name"),
    (("시가표준액", "과세", "표준액"), "total"),
    (("면적", "연면적", "㎡", "m²"), "area"),
    (("기준년도", "년도", "기준년", "과세년"), "year"),
    (("지번", "번지", "본번"), "lot"),
    (("구조",), "structure"),
    (("용도",), "usage"),
]

# WeTax 테이블 ID별 알려진 컬럼 매핑 (헤더 파싱 실패 시 폴백)
_WETAX_KNOWN_COLUMNS = {
    "tb_BldsCpbInq": ["_idx", "year", "lot", "dong_no", "ho", "name", "total", "area"],
    "tb_BldsCpbInqTmp": ["_idx", "year", "lot", "dong_no", "ho", "name", "total", "area"],
    "tb_hos": ["_idx", "dong_no", "ho", "name", "total", "area"],
    "tb_mfh": ["_idx", "year", "name", "total"],
}

_ERROR_PATTERNS = [
    "존재하지 않습니다", "조회되지 않습니다",
    "결과가 없습니다", "입력해야 합니다",
]


def _map_header_to_key(header_text):
    """테이블 헤더 텍스트를 dict 키로 매핑한다."""
    text = header_text.strip()
    if text == "동":
        return "dong_no"
    if text == "호":
        return "ho"
    for keywords, key in _HEADER_KEY_MAP:
        for kw in keywords:
            if kw in text:
                return key
    return None


def _pick_best_header_row(thead_el):
    """다중 행 thead에서 최적의 헤더 행을 선택한다.

    단일 행이면 그대로 반환. 다중 행인 경우 colspan/rowspan 그룹 헤더가 아닌
    개별 컬럼 레벨 헤더(th 수가 가장 많은 행)를 선택한다.
    """
    header_trs = thead_el.find_elements(By.TAG_NAME, "tr")
    if not header_trs:
        return []
    if len(header_trs) == 1:
        return [th.text.strip() for th in header_trs[0].find_elements(By.TAG_NAME, "th")]

    # th 수가 가장 많은 행 선택 (개별 컬럼 레벨 = th가 가장 많음)
    best_row = max(header_trs, key=lambda tr: len(tr.find_elements(By.TAG_NAME, "th")))
    return [th.text.strip() for th in best_row.find_elements(By.TAG_NAME, "th")]


def _extract_table_rows(table):
    """단일 테이블에서 dict 행 리스트를 추출한다."""
    rows = []

    # 헤더 추출 (thead 우선 — 다중 행 헤더 지원)
    headers = []
    thead_els = table.find_elements(By.TAG_NAME, "thead")
    if thead_els:
        headers = _pick_best_header_row(thead_els[0])
    if not headers:
        tr_els = table.find_elements(By.TAG_NAME, "tr")
        if tr_els:
            for th in tr_els[0].find_elements(By.TAG_NAME, "th"):
                headers.append(th.text.strip())

    key_map = [_map_header_to_key(h) for h in headers] if headers else []

    # 첫 번째 데이터 행의 컬럼 수를 확인하여 key_map 유효성 검증
    first_data_len = 0
    for tr in table.find_elements(By.TAG_NAME, "tr"):
        cells = tr.find_elements(By.TAG_NAME, "td")
        if cells:
            first_data_len = len(cells)
            break

    # key_map 수와 데이터 컬럼 수가 불일치하면 헤더 매핑을 포기 (폴백에 맡김)
    if key_map and first_data_len and len(key_map) != first_data_len:
        key_map = []

    for tr in table.find_elements(By.TAG_NAME, "tr"):
        cells = tr.find_elements(By.TAG_NAME, "td")
        if not cells:
            continue
        data = [c.text.strip() for c in cells]
        if not any(data):
            continue

        # 에러 메시지 행 제외
        joined = " ".join(data)
        if any(p in joined for p in _ERROR_PATTERNS):
            continue

        # dict 변환
        if key_map:
            row_dict = {}
            for i, val in enumerate(data):
                if i < len(key_map) and key_map[i] and val:
                    row_dict[key_map[i]] = val
            if row_dict:
                rows.append(row_dict)
        else:
            # 헤더 없는 경우: 컬럼 수에 따라 휴리스틱 매핑
            if len(data) >= 3:
                rows.append({"name": data[0], "total": data[1], "area": data[2]})
            elif len(data) == 2:
                rows.append({"name": data[0], "total": data[1]})
            elif len(data) == 1 and data[0]:
                rows.append({"name": data[0]})

    return rows


def _extract_table_rows_by_columns(table, column_keys):
    """알려진 컬럼 매핑으로 테이블 데이터 행을 추출한다 (헤더 파싱 실패 시 폴백)."""
    rows = []
    for tr in table.find_elements(By.TAG_NAME, "tr"):
        cells = tr.find_elements(By.TAG_NAME, "td")
        if not cells:
            continue
        data = [c.text.strip() for c in cells]
        if not any(data):
            continue
        joined = " ".join(data)
        if any(p in joined for p in _ERROR_PATTERNS):
            continue
        row_dict = {}
        for i, val in enumerate(data):
            if i < len(column_keys) and val:
                key = column_keys[i]
                if not key.startswith("_"):  # _로 시작하는 키는 건너뜀
                    row_dict[key] = val
        if row_dict:
            rows.append(row_dict)
    return rows


def _extract_all_results(driver):
    """테이블에서 결과를 dict 리스트로 추출한다."""
    results = []
    for tid in ["tb_BldsCpbInq", "tb_BldsCpbInqTmp", "tb_hos", "tb_mfh"]:
        try:
            table = driver.find_element(By.ID, tid)
            if not table.is_displayed():
                continue
            rows = _extract_table_rows(table)
            # 헤더 파싱 실패 시 알려진 컬럼 매핑으로 재시도
            if not rows and tid in _WETAX_KNOWN_COLUMNS:
                rows = _extract_table_rows_by_columns(table, _WETAX_KNOWN_COLUMNS[tid])
            results.extend(rows)
        except NoSuchElementException:
            continue

    if not results:
        for sel in ["div.cfGrid table", "div.grid-body table",
                     "table.tbl_list", "div[id*='grid'] table"]:
            try:
                for table in driver.find_elements(By.CSS_SELECTOR, sel):
                    if not table.is_displayed():
                        continue
                    results.extend(_extract_table_rows(table))
            except Exception:
                continue
    return results
