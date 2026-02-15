"""PDF 생성 모듈 — WeasyPrint."""

from datetime import datetime
from urllib.parse import urlparse

from flask import render_template, make_response

try:
    from weasyprint import HTML
    from weasyprint import default_url_fetcher
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


# 허용된 외부 도메인 (폰트 등)
_ALLOWED_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}


def _safe_url_fetcher(url, timeout=10, ssl_context=None):
    """file:// 프로토콜 차단, 허용된 호스트만 외부 접근 허용."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        raise ValueError(f"로컬 파일 접근 차단: {url}")
    if parsed.scheme in ("http", "https"):
        if parsed.hostname and parsed.hostname not in _ALLOWED_HOSTS:
            raise ValueError(f"허용되지 않은 외부 호스트: {parsed.hostname}")
    return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)


def generate_pdf_response(result, filename=None):
    """조회 결과를 PDF로 변환하여 Flask Response를 반환한다."""
    if not WEASYPRINT_AVAILABLE:
        return make_response("WeasyPrint가 설치되지 않았습니다.", 500)

    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"시가조회_{timestamp}.pdf"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_string = render_template(
        "pdf/result_pdf.html",
        result=result,
        now=now,
    )
    pdf_bytes = HTML(
        string=html_string,
        url_fetcher=_safe_url_fetcher,
    ).write_pdf()

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response
