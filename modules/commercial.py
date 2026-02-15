"""상가/오피스텔 기준시가 조회 — HomeTax."""

import requests

from .base import BaseLookupModule, LookupResult

HOMETAX_URL = "https://mob.tbht.hometax.go.kr/jsonAction.do"


class CommercialPriceModule(BaseLookupModule):

    @property
    def property_type(self) -> str:
        return "commercial"

    @property
    def property_type_label(self) -> str:
        return "상가/오피스텔 (기준시가)"

    @property
    def source_name(self) -> str:
        return "hometax"

    def search(self, address: dict, year: str = "", **kwargs) -> LookupResult:
        # TODO: HomeTax 모바일 API 리버스 엔지니어링 필요
        # 현재는 미구현 상태로 안내 메시지 반환
        return LookupResult(
            success=False,
            property_type=self.property_type,
            property_type_label=self.property_type_label,
            address=address.get("_raw", ""),
            year=year,
            source=self.source_name,
            error="상가/오피스텔 기준시가 조회는 준비 중입니다. "
                  "국세청 홈택스(hometax.go.kr)에서 직접 조회해주세요.",
        )
