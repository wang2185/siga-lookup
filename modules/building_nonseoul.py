"""주택외건물 비서울 지역 시가표준액 조회 — WeTax (Selenium)."""

import base64
import os
import re
import shutil
import time
import traceback

import requests as _requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from .base import BaseLookupModule, LookupResult

WETAX_URL = "https://www.wetax.go.kr/tcp/loi/J030401M01.do"

# AntiCaptcha API
_ANTICAPTCHA_URL = "https://api.anti-captcha.com"
_CAPTCHA_MAX_RETRIES = 3

# 시/도 약칭 → 정식 명칭 매핑 (WeTax 드롭다운은 정식 명칭 사용)
_SIDO_FULL = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
    "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시",
    "울산": "울산광역시", "세종": "세종특별자치시",
    "경기": "경기도", "강원": "강원특별자치도",
    "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전남": "전라남도",
    "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
}

# 한글 → 영문 알파벳 매핑 (동호수 변환용)
_KOR_TO_ALPHA = {
    '에이': 'A', '비': 'B', '씨': 'C', '디': 'D',
    '이': 'E', '에프': 'F', '지': 'G', '에이치': 'H',
    '아이': 'I', '제이': 'J', '케이': 'K', '엘': 'L',
    '엠': 'M', '엔': 'N', '오': 'O', '피': 'P',
    '큐': 'Q', '알': 'R', '아르': 'R', '에스': 'S',
    '티': 'T', '유': 'U', '브이': 'V', '더블유': 'W',
    '엑스': 'X', '와이': 'Y', '제트': 'Z',
}
_ALPHA_TO_KOR = {v: k for k, v in _KOR_TO_ALPHA.items() if k != '아르'}


def _generate_dong_ho_variations(dong_no: str, ho_no: str) -> list:
    """동호수의 다양한 해석 조합을 생성한다.

    예: dong=씨, ho=1000 → [(씨,1000), (C,1000), (,C1000), (,씨1000)]
        dong=B, ho=2423 → [(B,2423), (비,2423), (,B2423), (,B-2423)]
        dong=에이, ho=502 → [(에이,502), (A,502), (,A502)]
        dong=101, ho=4304 → [(101,4304), (,101-4304)]
        dong=, ho=B-2423 → [(,B-2423), (B,2423), (비,2423)]
    """
    seen = set()
    variations = []

    def _add(d, h):
        key = (str(d).strip(), str(h).strip())
        if key not in seen and (key[0] or key[1]):
            seen.add(key)
            variations.append(key)

    dong = str(dong_no or "").strip()
    ho = str(ho_no or "").strip()

    # 0) 원본 그대로
    _add(dong, ho)

    # 1) 한글동 → 영문 변환 (에이→A, 비→B, 씨→C ...)
    if dong:
        alpha = _KOR_TO_ALPHA.get(dong)
        if alpha:
            _add(alpha, ho)
            _add("", alpha + ho)  # 합쳐서 호에
        kor = _ALPHA_TO_KOR.get(dong.upper())
        if kor:
            _add(kor, ho)
            _add("", kor + ho)

    # 2) ho에 영문 접두어: ho=B239 or B-239 → dong=B, ho=239
    if ho:
        m = re.match(r'^([A-Za-z])[-]?(\d+)$', ho)
        if m:
            letter, num = m.group(1).upper(), m.group(2)
            _add(letter, num)
            kor = _ALPHA_TO_KOR.get(letter)
            if kor:
                _add(kor, num)
            _add("", letter + num)
            _add("", ho)

    # 3) ho에 한글 접두어: ho=씨1000 → dong=씨, ho=1000 / dong=C, ho=1000
    if ho:
        m = re.match(r'^([가-힣]{1,4})(\d+)$', ho)
        if m:
            kor_part, num = m.group(1), m.group(2)
            _add(kor_part, num)
            alpha = _KOR_TO_ALPHA.get(kor_part)
            if alpha:
                _add(alpha, num)
                _add("", alpha + num)

    # 4) dong+ho 합산: dong=101, ho=4304 → 호에 "101-4304"
    if dong and ho and dong.isdigit() and ho.isdigit():
        _add("", f"{dong}-{ho}")

    # 5) dong 비어있고 ho에 하이픈: ho=B-2423 → dong=B, ho=2423
    if not dong and ho and "-" in ho:
        parts = ho.split("-", 1)
        _add(parts[0], parts[1])
        if re.match(r'^[A-Za-z]$', parts[0]):
            letter = parts[0].upper()
            _add(letter, parts[1])
            kor = _ALPHA_TO_KOR.get(letter)
            if kor:
                _add(kor, parts[1])
        elif parts[0] in _KOR_TO_ALPHA:
            _add(_KOR_TO_ALPHA[parts[0]], parts[1])

    # 6) dong만 있고 ho 없는 경우: dong을 ho로 이동
    if dong and not ho:
        _add("", dong)
        _add("1", dong)

    # 7) ho 선행 0 제거/추가
    if ho and ho.isdigit():
        stripped = ho.lstrip('0') or '0'
        _add(dong, stripped)
        if len(ho) < 4:
            _add(dong, ho.zfill(4))

    # 8) dong 없이 ho만
    if dong and ho:
        _add("", ho)

    # 9) 동=1로 시도
    if ho and dong != "1":
        _add("1", ho)

    return variations


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
        result = self._run_search(address)
        return LookupResult(
            success=result["success"],
            property_type=self.property_type,
            property_type_label=self.property_type_label,
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

    def _run_search(self, addr: dict) -> dict:
        logs = []
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_argument("--window-size=1400,900")

        # 서버 환경에서 PATH가 제한적일 수 있으므로 Chrome 바이너리 위치 명시
        chrome_bin = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome_bin:
            for p in ("/usr/bin/google-chrome", "/opt/google/chrome/google-chrome", "/snap/bin/chromium"):
                if os.path.isfile(p):
                    chrome_bin = p
                    break
        if chrome_bin:
            chrome_options.binary_location = chrome_bin

        driver = webdriver.Chrome(options=chrome_options)
        try:
            logs.append("Chrome 브라우저 시작")
            driver.get(WETAX_URL)
            time.sleep(1.5)
            _dismiss_alerts(driver)
            logs.append("위택스 페이지 접속 완료")
            _hide_security_popups(driver)
            _dismiss_alerts(driver)

            # 기존건물 라디오 확인
            try:
                radio = driver.find_element(By.ID, "radio_02_01")
                if not radio.is_selected():
                    _click_radio(driver, "radio_02_01")
            except NoSuchElementException:
                _click_radio_by_label_text(driver, "기존")
            time.sleep(0.3)
            _dismiss_alerts(driver)

            # 시/도 (약칭 → 정식 명칭 변환)
            sido_kw = addr.get("sido", "")
            sido_full = _SIDO_FULL.get(sido_kw, sido_kw)
            logs.append(f"시/도 선택: {sido_kw}")
            if not _wait_and_select(driver, "selUpLgvCd", sido_full):
                # 정식명칭 실패 시 약칭으로 재시도
                if sido_full != sido_kw:
                    _wait_and_select(driver, "selUpLgvCd", sido_kw)
                else:
                    logs.append("시/도 선택 실패")
            time.sleep(1)
            _dismiss_alerts(driver)

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
            time.sleep(1)
            _dismiss_alerts(driver)

            # 읍/면/동
            logs.append(f"읍/면/동 선택: {addr.get('dong', '')}")
            if not _wait_and_select(driver, "selStdgCd", addr.get("dong", "")):
                logs.append("읍/면/동 선택 실패")
            time.sleep(0.5)
            _dismiss_alerts(driver)

            # 기준년도
            _select_first_valid_option(driver, "selCrtrYr")
            selected_year = _get_selected_text(driver, "selCrtrYr")
            time.sleep(0.2)

            # 특수번지
            if addr.get("san"):
                _select_option_containing(driver, "selExstSpeLotno", "산")
            else:
                _select_first_valid_option(driver, "selExstSpeLotno")
            time.sleep(0.2)

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

            # 동/호 — 여러 변환 조합을 시도하여 결과 찾기
            dong_no = addr.get("dong_no", "")
            ho_no = addr.get("ho_no", "")
            anticaptcha_key = os.getenv("ANTICAPTCHA_API_KEY", "")

            # 동호 미입력 → variation 없이 캡차 1회만 소비
            # 동호 입력 → 모든 variation 시도 (제한 없음)
            if dong_no or ho_no:
                variations = _generate_dong_ho_variations(dong_no, ho_no)
            else:
                variations = [("", "")]
            results = []
            evidence = None

            for vi, (try_dong, try_ho) in enumerate(variations):
                if vi > 0:
                    logs.append(f"동호 변환 재시도 [{vi+1}/{len(variations)}]: 동={try_dong!r} 호={try_ho!r}")

                _fill_dong_ho(driver, try_dong, try_ho)
                time.sleep(0.2)

                _solve_captcha_anticaptcha(driver, anticaptcha_key, logs)
                time.sleep(0.2)

                results, evidence = _click_search_and_extract(driver, logs)

                if results:
                    if vi > 0:
                        logs.append(f"동호 변환 성공: 동={try_dong!r} 호={try_ho!r}")
                    break

            # 테이블에 없는 키를 입력 주소에서 보충
            lot_str = addr.get("bonji", "")
            if addr.get("bunji"):
                lot_str += f"-{addr['bunji']}"
            fill_defaults = {
                "year": selected_year,
                "lot": lot_str,
                "dong_no": addr.get("dong_no", ""),
                "ho": addr.get("ho_no", ""),
            }
            for row in results:
                for key, val in fill_defaults.items():
                    if not row.get(key) and val:
                        row[key] = val

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
        _dismiss_alerts(driver)
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
        except (StaleElementReferenceException, NoSuchElementException):
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


def _get_selected_text(driver, select_id):
    """select 요소에서 현재 선택된 option의 텍스트를 반환한다."""
    try:
        el = driver.find_element(By.ID, select_id)
        for opt in el.find_elements(By.TAG_NAME, "option"):
            if opt.is_selected():
                return opt.text.strip()
    except Exception:
        pass
    return ""


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


def _wait_loading_done(driver, timeout=30):
    """WeTax 로딩 오버레이('업무데이터 수신중입니다')가 사라질 때까지 대기."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        loading = driver.execute_script("""
            var overlays = document.querySelectorAll('.loading, .blockUI, [class*="loading"]');
            for (var i = 0; i < overlays.length; i++) {
                if (overlays[i].offsetParent !== null ||
                    window.getComputedStyle(overlays[i]).display !== 'none') {
                    return true;
                }
            }
            if (document.body.innerText.indexOf('수신중') >= 0) return true;
            return false;
        """)
        if not loading:
            return
        time.sleep(1)


def _solve_captcha_anticaptcha(driver, api_key, logs):
    """WeTax 캡차 이미지를 AntiCaptcha로 풀어서 입력한다."""
    if not api_key:
        logs.append("ANTICAPTCHA_API_KEY 미설정 — 캡차 미처리")
        return False

    # 캡차 이미지를 base64로 추출
    captcha_b64 = driver.execute_script("""
        var imgs = document.querySelectorAll('img');
        for (var i = 0; i < imgs.length; i++) {
            var src = imgs[i].src || '';
            var id = imgs[i].id || '';
            var alt = imgs[i].alt || '';
            if (src.indexOf('captcha') >= 0 || id.indexOf('captcha') >= 0 ||
                alt.indexOf('자동입력') >= 0 || alt.indexOf('보안') >= 0 ||
                src.indexOf('captchaImg') >= 0) {
                var canvas = document.createElement('canvas');
                canvas.width = imgs[i].naturalWidth || imgs[i].width;
                canvas.height = imgs[i].naturalHeight || imgs[i].height;
                var ctx = canvas.getContext('2d');
                ctx.drawImage(imgs[i], 0, 0);
                return canvas.toDataURL('image/png').replace(/^data:image\\/png;base64,/, '');
            }
        }
        // 폴백: 캡차 입력란 근처의 이미지
        var captchaInput = document.querySelector(
            'input[title*="자동입력"], input[title*="보안문자"], input[id*="captcha"]'
        );
        if (captchaInput) {
            var parent = captchaInput.closest('tr, div, td');
            if (parent) {
                var img = parent.querySelector('img');
                if (img && img.naturalWidth > 50) {
                    var c2 = document.createElement('canvas');
                    c2.width = img.naturalWidth || img.width;
                    c2.height = img.naturalHeight || img.height;
                    c2.getContext('2d').drawImage(img, 0, 0);
                    return c2.toDataURL('image/png').replace(/^data:image\\/png;base64,/, '');
                }
            }
        }
        return null;
    """)

    if not captcha_b64:
        logs.append("캡차 이미지를 찾을 수 없음")
        return False

    logs.append("캡차 이미지 추출 완료")

    # AntiCaptcha에 제출
    for attempt in range(_CAPTCHA_MAX_RETRIES):
        try:
            resp = _requests.post(f"{_ANTICAPTCHA_URL}/createTask", json={
                "clientKey": api_key,
                "task": {
                    "type": "ImageToTextTask",
                    "body": captcha_b64,
                    "phrase": False,
                    "case": False,
                    "numeric": 1,
                    "math": False,
                    "minLength": 4,
                    "maxLength": 6,
                },
                "languagePool": "en",
            }, timeout=10)
            data = resp.json()

            if data.get("errorCode") == "ERROR_NO_SLOT_AVAILABLE":
                time.sleep(3 + attempt * 2)
                continue

            task_id = data.get("taskId")
            if not task_id:
                logs.append(f"캡차 태스크 생성 실패: {data.get('errorDescription', '')}")
                return False
            break
        except Exception as e:
            logs.append(f"AntiCaptcha 요청 실패: {e}")
            return False
    else:
        logs.append("AntiCaptcha 슬롯 부족 — 재시도 소진")
        return False

    # 결과 대기 (최대 60초)
    answer = None
    for _ in range(30):
        time.sleep(2)
        try:
            resp = _requests.post(f"{_ANTICAPTCHA_URL}/getTaskResult", json={
                "clientKey": api_key,
                "taskId": task_id,
            }, timeout=10)
            result = resp.json()
            if result.get("status") == "processing":
                continue
            if result.get("status") == "ready":
                answer = result.get("solution", {}).get("text", "")
                break
            logs.append(f"캡차 풀기 오류: {result.get('errorDescription', '')}")
            return False
        except Exception:
            continue

    if not answer:
        logs.append("캡차 풀기 타임아웃")
        return False

    logs.append(f"캡차 답: {answer}")

    # 캡차 입력란에 답 입력
    filled = driver.execute_script("""
        var inputs = document.querySelectorAll('input[type="text"]');
        for (var i = 0; i < inputs.length; i++) {
            var inp = inputs[i];
            var title = (inp.title || '').toLowerCase();
            var id = (inp.id || '').toLowerCase();
            var name = (inp.name || '').toLowerCase();
            var ph = (inp.placeholder || '').toLowerCase();
            if (title.indexOf('자동입력') >= 0 || title.indexOf('보안문자') >= 0 ||
                id.indexOf('captcha') >= 0 || name.indexOf('captcha') >= 0 ||
                ph.indexOf('자동입력') >= 0 || ph.indexOf('보안') >= 0) {
                inp.value = '';
                inp.focus();
                inp.value = arguments[0];
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
                return true;
            }
        }
        // 폴백: 캡차 이미지 근처의 빈 입력란
        var captchaSection = document.querySelector(
            'img[src*="captcha"], img[id*="captcha"]'
        );
        if (captchaSection) {
            var parent = captchaSection.closest('tr, div, td, table');
            if (parent) {
                var inp = parent.querySelector('input[type="text"]');
                if (inp) {
                    inp.value = arguments[0];
                    inp.dispatchEvent(new Event('input', {bubbles:true}));
                    return true;
                }
            }
        }
        return false;
    """, answer)

    if filled:
        logs.append("캡차 입력 완료")
    else:
        logs.append("캡차 입력란을 찾을 수 없음")
    return filled


def _dismiss_alerts(driver):
    """JavaScript alert가 있으면 모두 닫는다 (보안프로그램 설치 등).

    보안프로그램 설치 alert는 '확인' 시 설치페이지로 이동하므로
    dismiss(취소)로 닫아야 현재 페이지를 유지할 수 있다.
    """
    for _ in range(3):
        try:
            alert = driver.switch_to.alert
            alert.dismiss()
            time.sleep(0.3)
        except Exception:
            break


def _hide_security_popups(driver):
    """키보드 보안 팝업(NOS 등)을 DOM에서 직접 제거한다.

    X 버튼 클릭 시 보안프로그램 설치 JS alert가 트리거되어
    페이지를 깨뜨리므로, 버튼을 클릭하지 않고 DOM 제거만 수행한다.
    """
    try:
        driver.execute_script("""
            var nosPop = document.getElementById('nos_pop');
            if (nosPop) nosPop.remove();
            // 배경 오버레이도 제거
            var overlays = document.querySelectorAll('.pop_bg, .dim_layer');
            overlays.forEach(function(o) { o.remove(); });
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

    time.sleep(1)

    try:
        alert = driver.switch_to.alert
        alert.accept()
    except Exception:
        pass

    # 로딩 오버레이("업무데이터 수신중입니다") 완료 대기
    _wait_loading_done(driver, timeout=30)

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
# 컬럼 수별 다중 매핑: WeTax 페이지 상태에 따라 테이블 구조가 달라질 수 있음
_WETAX_KNOWN_COLUMNS = {
    "tb_BldsCpbInq": {
        8: ["_idx", "year", "lot", "dong_no", "ho", "name", "total", "area"],
        3: ["name", "total", "area"],
    },
    "tb_BldsCpbInqTmp": {
        8: ["_idx", "year", "lot", "dong_no", "ho", "name", "total", "area"],
        3: ["name", "total", "area"],
    },
    "tb_hos": {
        6: ["_idx", "dong_no", "ho", "name", "total", "area"],
        3: ["name", "total", "area"],
    },
    "tb_mfh": {
        4: ["_idx", "year", "name", "total"],
        3: ["name", "total", "area"],
    },
}

_ERROR_PATTERNS = [
    "존재하지 않습니다", "조회되지 않습니다",
    "결과가 없습니다", "입력해야 합니다", "입력하셔야 합니다",
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


def _resolve_known_columns(tid, col_count):
    """테이블 ID와 데이터 컬럼 수에 맞는 알려진 컬럼 매핑을 반환한다."""
    mappings = _WETAX_KNOWN_COLUMNS.get(tid)
    if not mappings:
        return None
    # 정확한 컬럼 수 매칭 우선
    if col_count in mappings:
        return mappings[col_count]
    # 가장 가까운 매핑 반환
    closest = min(mappings.keys(), key=lambda k: abs(k - col_count))
    return mappings[closest]


def _extract_all_results(driver):
    """테이블에서 결과를 dict 리스트로 추출한다."""
    results = []
    for tid in ["tb_BldsCpbInq", "tb_BldsCpbInqTmp", "tb_hos", "tb_mfh"]:
        try:
            table = driver.find_element(By.ID, tid)
            if not table.is_displayed():
                continue
            rows = _extract_table_rows(table)
            # 헤더 파싱 실패 또는 핵심 키(total) 누락 시 알려진 컬럼 매핑으로 재시도
            needs_fallback = (
                not rows
                or (rows and not any(r.get("total") for r in rows))
            )
            if needs_fallback and tid in _WETAX_KNOWN_COLUMNS:
                # 데이터 컬럼 수 확인
                col_count = 0
                for tr in table.find_elements(By.TAG_NAME, "tr"):
                    tds = tr.find_elements(By.TAG_NAME, "td")
                    if tds:
                        col_count = len(tds)
                        break
                known_cols = _resolve_known_columns(tid, col_count)
                if known_cols:
                    fallback_rows = _extract_table_rows_by_columns(table, known_cols)
                    if fallback_rows and any(r.get("total") for r in fallback_rows):
                        rows = fallback_rows
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
