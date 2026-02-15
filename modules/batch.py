"""Excel 일괄 조회 처리 엔진."""

import io
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from .address import search_vworld, extract_address_components, parse_address

# 전역 작업 관리
_jobs: dict = {}
_jobs_lock = threading.Lock()

MAX_ROWS = 100
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_JOBS_KEPT = 20


@dataclass
class BatchJob:
    job_id: str
    total: int = 0
    processed: int = 0
    current_address: str = ""
    status: str = "pending"  # pending, processing, completed, error
    error: str = ""
    results: list = field(default_factory=list)
    output_bytes: bytes = b""
    created_at: float = field(default_factory=time.time)


def get_job(job_id: str) -> BatchJob | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def parse_excel(file_bytes: bytes) -> list[dict]:
    """엑셀 파일을 파싱하여 [{row, address, year}, ...] 리스트를 반환한다."""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    ws = wb.active
    rows = []
    for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not row[0]:
            continue
        address = str(row[0]).strip()
        if not address:
            continue
        year = ""
        if len(row) > 1 and row[1]:
            year = str(row[1]).strip()
        rows.append({"row": idx, "address": address, "year": year})
    wb.close()
    if len(rows) > MAX_ROWS:
        raise ValueError(f"최대 {MAX_ROWS}건까지 처리 가능합니다. (입력: {len(rows)}건)")
    return rows


def start_batch_job(
    file_bytes: bytes,
    default_year: str,
    vworld_api_key: str,
    land_module,
    apartment_module,
    house_module,
) -> str:
    """배치 작업을 시작하고 job_id를 반환한다."""
    rows = parse_excel(file_bytes)
    if not rows:
        raise ValueError("엑셀에 조회할 주소가 없습니다.")

    job_id = uuid.uuid4().hex[:12]
    job = BatchJob(job_id=job_id, total=len(rows))

    with _jobs_lock:
        _jobs[job_id] = job
        # 오래된 작업 정리
        if len(_jobs) > MAX_JOBS_KEPT:
            sorted_jobs = sorted(_jobs.values(), key=lambda j: j.created_at)
            for old in sorted_jobs[: len(_jobs) - MAX_JOBS_KEPT]:
                if old.job_id != job_id:
                    del _jobs[old.job_id]

    t = threading.Thread(
        target=_process_batch,
        args=(job, rows, default_year, vworld_api_key,
              land_module, apartment_module, house_module),
        daemon=True,
    )
    t.start()
    return job_id


def _process_batch(
    job: BatchJob,
    rows: list[dict],
    default_year: str,
    vworld_api_key: str,
    land_module,
    apartment_module,
    house_module,
):
    """백그라운드에서 각 주소를 조회한다."""
    job.status = "processing"

    for entry in rows:
        addr_str = entry["address"]
        year = entry["year"] or default_year
        job.current_address = addr_str

        result_row = {
            "row_num": entry["row"],
            "address": addr_str,
            "pnu": "",
            "year": year,
            "land_price_per_sqm": "",
            "land_area": "",
            "land_total_price": "",
            "apt_building_name": "",
            "apt_price": "",
            "house_price": "",
            "status": "",
        }

        try:
            # 1. 주소 검색 → PNU 추출
            address = _resolve_address_for_batch(addr_str, vworld_api_key)
            pnu = address.get("pnu", "")
            result_row["pnu"] = pnu

            if not pnu and not address.get("adm_cd", ""):
                result_row["status"] = "PNU 추출 실패"
                job.results.append(result_row)
                job.processed += 1
                time.sleep(0.3)
                continue

            found_types = []

            # 2. 토지 조회
            try:
                land_result = land_module.search(address, year)
                if land_result.success and land_result.results:
                    first = land_result.results[0]
                    result_row["land_price_per_sqm"] = first.get("price_per_sqm", "")
                    result_row["land_area"] = first.get("land_area", "")
                    result_row["land_total_price"] = first.get("total_price", "")
                    found_types.append("토지")
            except Exception:
                pass
            time.sleep(0.5)

            # 3. 공동주택 조회
            try:
                apt_result = apartment_module.search(address, year)
                if apt_result.success and apt_result.results:
                    first = apt_result.results[0]
                    result_row["apt_building_name"] = first.get("building_name", "")
                    result_row["apt_price"] = first.get("price", "")
                    found_types.append("공동주택")
            except Exception:
                pass
            time.sleep(0.5)

            # 4. 개별주택 조회
            try:
                house_result = house_module.search(address, year)
                if house_result.success and house_result.results:
                    first = house_result.results[0]
                    result_row["house_price"] = first.get("price", "")
                    found_types.append("개별주택")
            except Exception:
                pass

            if found_types:
                result_row["status"] = ", ".join(found_types)
            else:
                result_row["status"] = "결과없음"

        except Exception as e:
            result_row["status"] = f"오류: {e}"

        job.results.append(result_row)
        job.processed += 1
        time.sleep(0.3)

    # 결과 엑셀 생성
    try:
        job.output_bytes = _generate_output_excel(job.results)
        job.status = "completed"
    except Exception as e:
        job.status = "error"
        job.error = f"엑셀 생성 오류: {e}"


def _resolve_address_for_batch(addr_str: str, vworld_api_key: str) -> dict:
    """배치용 주소 해석: V-World 검색 → 첫 번째 결과에서 PNU 추출."""
    search_result = search_vworld(addr_str, vworld_api_key)
    items = search_result.get("items", [])

    if items:
        addr = extract_address_components(items[0])
        addr["_raw"] = addr_str
        return addr

    # V-World 검색 실패 시 파싱으로 폴백
    addr = parse_address(addr_str)
    addr["_raw"] = addr_str
    return addr


def _generate_output_excel(results: list[dict]) -> bytes:
    """결과 리스트로부터 엑셀 파일 바이트를 생성한다."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "일괄조회 결과"

    # 스타일
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )
    price_font = Font(bold=True, color="2563EB")

    headers = [
        "#", "주소", "PNU", "기준년도",
        "토지_공시지가(원/m²)", "토지_면적(m²)", "토지_총액(원)",
        "공동주택_건물명", "공동주택_공시가격(원)",
        "개별주택_공시가격(원)",
        "조회상태",
    ]

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    for row_idx, row_data in enumerate(results, 2):
        values = [
            row_idx - 1,
            row_data.get("address", ""),
            row_data.get("pnu", ""),
            row_data.get("year", ""),
            _to_number(row_data.get("land_price_per_sqm", "")),
            _to_number(row_data.get("land_area", "")),
            _to_number(row_data.get("land_total_price", "")),
            row_data.get("apt_building_name", ""),
            _to_number(row_data.get("apt_price", "")),
            _to_number(row_data.get("house_price", "")),
            row_data.get("status", ""),
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            # 가격 컬럼 스타일
            if col_idx in (5, 7, 9, 10) and val:
                cell.font = price_font
                cell.number_format = "#,##0"

    # 열 너비 설정
    widths = [5, 35, 22, 10, 18, 12, 18, 20, 20, 20, 15]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    # 필터 설정
    ws.auto_filter.ref = ws.dimensions

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _to_number(val):
    """문자열 숫자를 int/float로 변환, 실패 시 원본 반환."""
    if not val:
        return ""
    try:
        f = float(val)
        if f == int(f):
            return int(f)
        return f
    except (ValueError, TypeError):
        return val


def generate_sample_template() -> bytes:
    """샘플 양식 엑셀 파일을 생성한다."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "일괄조회 양식"

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")

    headers = ["주소 (필수)", "기준년도 (선택)"]
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align

    examples = [
        ("서울 강남구 역삼동 601", "2025"),
        ("부산 해운대구 우동 456", ""),
        ("수원시 팔달구 인계동 789", "2024"),
    ]
    for row_idx, (addr, yr) in enumerate(examples, 2):
        ws.cell(row=row_idx, column=1, value=addr)
        ws.cell(row=row_idx, column=2, value=yr)

    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 18

    # 안내 행
    note_row = len(examples) + 3
    note_cell = ws.cell(row=note_row, column=1, value="[안내] A열에 주소를 입력하세요. B열 기준년도는 선택사항입니다.")
    note_cell.font = Font(color="94A3B8", italic=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
