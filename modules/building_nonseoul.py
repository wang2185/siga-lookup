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

            # 시/군/구
            logs.append(f"시/군/구 선택: {addr.get('sigungu', '')}")
            if not _wait_and_select(driver, "selLgvCd", addr.get("sigungu", "")):
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
            _fill_dong_ho(driver, addr.get("dong_no", ""), addr.get("ho_no", ""))
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
            try:
                alert = driver.switch_to.alert
                alert.accept()
            except Exception:
                pass

            # 결과 수집
            results = _extract_all_results(driver)
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

            return {"success": True, "results": results, "message": message, "logs": logs}

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


def _extract_all_results(driver):
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
