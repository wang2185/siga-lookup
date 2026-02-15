"""개별주택가격 조회 — data.go.kr API."""

import requests

from .base import BaseLookupModule, LookupResult

API_URL = "http://apis.data.go.kr/1611000/nsdi/IndvdHousingPriceService/attr/getIndvdHousingPriceAttr"


class HousePriceModule(BaseLookupModule):

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def property_type(self) -> str:
        return "house"

    @property
    def property_type_label(self) -> str:
        return "개별주택 (개별주택가격)"

    @property
    def source_name(self) -> str:
        return "data.go.kr"

    def search(self, address: dict, year: str = "", **kwargs) -> LookupResult:
        if not self.api_key:
            return LookupResult(
                success=False, property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""), year=year,
                source=self.source_name,
                error="공공데이터포털 API 키가 설정되지 않았습니다.",
            )

        pnu = address.get("pnu", "")
        if not pnu:
            return LookupResult(
                success=False, property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""), year=year,
                source=self.source_name,
                error="PNU(필지고유번호)를 추출할 수 없습니다. 주소를 다시 선택해주세요.",
            )

        from datetime import datetime
        stdr_year = year or str(datetime.now().year)

        try:
            params = {
                "serviceKey": self.api_key,
                "pnu": pnu,
                "stdrYear": stdr_year,
                "format": "json",
                "numOfRows": 50,
                "pageNo": 1,
            }
            resp = requests.get(API_URL, params=params, timeout=15)
            data = resp.json()

            items = (data.get("indvdHousingPrices", {})
                        .get("field", []))
            if not isinstance(items, list):
                items = [items] if items else []

            results = []
            for item in items:
                results.append({
                    "pnu": item.get("pnu", ""),
                    "year": item.get("stdrYear", ""),
                    "price": item.get("pblntfPc", ""),
                    "building_area": item.get("buldTotAr", ""),
                    "land_area": item.get("buldPlotAr", ""),
                    "announcement_date": item.get("pblntfDe", ""),
                })

            return LookupResult(
                success=True, property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""), year=stdr_year,
                results=results, source=self.source_name,
            )

        except Exception as e:
            return LookupResult(
                success=False, property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""), year=stdr_year,
                source=self.source_name,
                error=f"API 조회 오류: {e}",
            )
